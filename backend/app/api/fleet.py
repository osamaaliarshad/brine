from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import inventory
from app.api.deps import RuntimeDep, SessionDep
from app.api.inventory import inventory_cells
from app.api.schemas import (
    CatchUpRun,
    Column,
    Fleet,
    FleetSummary,
    GrainDistribution,
    GrainKey,
    GrainsChange,
    GrainValue,
    MinionDetail,
    MinionJob,
    MinionSummary,
    PresenceInfo,
    PresencePoint,
)
from app.ingest import PRESENCE_BLIND_STATE
from app.models import (
    GrainsSnapshot,
    Job,
    JobReturn,
    Minion,
    PendingRun,
    PresenceChange,
    SystemState,
)
from app.presence import is_fresh, read_presence
from app.runtime import Runtime
from app.status import Status, minion_status

router = APIRouter()

MAX_COLUMNS = 30


def grain_value(grains: dict[str, Any] | None, path: str) -> Any:
    """Look up a grain, allowing `a:b` paths into nested dicts (as Salt does)."""
    node: Any = grains or {}
    for part in path.split(":"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def os_label(grains: dict[str, Any] | None) -> str | None:
    if not grains:
        return None
    name, release = grains.get("os"), grains.get("osrelease")
    if name and release:
        return f"{name} {release}"
    return grains.get("osfinger") or name


def primary_ip(grains: dict[str, Any] | None) -> str | None:
    """The address most likely to be useful: fqdn_ip4 first, then any non-loopback IPv4."""
    for key in ("fqdn_ip4", "ipv4"):
        for value in grain_value(grains, key) or []:
            try:
                ip = ipaddress.ip_address(value)
            except ValueError:
                continue
            if not (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
                return str(ip)
    return None


async def presence_info(session: SessionDep) -> PresenceInfo:
    method, checked_at = await read_presence(session)
    return PresenceInfo(method=method, checked_at=checked_at)


async def reachable(runtime: Runtime, session: AsyncSession) -> tuple[list[str], list[str]]:
    """Accepted minions worth asking live, and those skipped because a fresh presence check says
    they're offline (asking them would only wait out Salt's timeout). Without fresh presence, or
    for minions presence can't see, brine can't tell, so it asks."""
    presence = await presence_info(session)
    blind = await presence_blind(session)
    fresh = is_fresh(presence.checked_at, datetime.now(UTC), runtime.settings)
    rows = (
        await session.execute(
            select(Minion.id, Minion.connected)
            .where(Minion.key_state == "accepted")
            .order_by(Minion.id)
        )
    ).all()
    ask = [mid for mid, connected in rows if connected or not fresh or mid in blind]
    return ask, [mid for mid, _ in rows if mid not in ask]


async def presence_blind(session: SessionDep) -> set[str]:
    row = await session.get(SystemState, PRESENCE_BLIND_STATE)
    return set(row.value or []) if row is not None else set()


def column_label(grain: str) -> str:
    """A column's label when none is configured: the grain path, or for an `@` key the
    package's or entry's name (a single-value check's own name)."""
    parsed = inventory.parse_key(grain)
    if parsed is None:
        return grain
    source, name = parsed
    return name or source


def configured_columns(runtime: Runtime) -> list[Column]:
    return [
        Column(grain=c.grain, label=c.label or column_label(c.grain))
        for c in runtime.settings.fleet.columns
    ]


def requested_columns(runtime: Runtime, grains: list[str] | None) -> list[Column]:
    """The columns a request asked for (`?column=a&column=b:c&column=@packages:bash`), or the
    configured defaults. Configured labels are reused for configured columns."""
    if grains is None:
        return configured_columns(runtime)
    labels = {c.grain: c.label for c in configured_columns(runtime)}
    picked = list(dict.fromkeys(g.strip() for g in grains if g.strip()))[:MAX_COLUMNS]
    return [Column(grain=g, label=labels.get(g) or column_label(g)) for g in picked]


def column_values(
    minion: Minion, columns: list[Column], cells: Mapping[str, str | None]
) -> dict[str, Any]:
    """Each column's value: a grain column always has one (None when it isn't reported), an
    `@` column only when it's known (`cells`, the minion's from `inventory_cells`)."""
    values: dict[str, Any] = {}
    for c in columns:
        if not inventory.is_key(c.grain):
            values[c.grain] = grain_value(minion.grains, c.grain)
        elif c.grain in cells:
            values[c.grain] = cells[c.grain]
    return values


def column_sources(runtime: Runtime, columns: list[Column]) -> list[str]:
    """The sources the `@` columns come from ("packages", a check's name), each once."""
    keys = (inventory.configured_key(runtime.settings, c.grain) for c in columns)
    return list(dict.fromkeys(parsed[0] for parsed in keys if parsed is not None))


def summarize(
    minion: Minion,
    runtime: Runtime,
    presence: PresenceInfo,
    now: datetime,
    *,
    columns: list[Column],
    cells: Mapping[str, Mapping[str, str | None]],
    read_at: Mapping[str, Mapping[str, datetime | None]],
    blind: set[str] | frozenset[str] = frozenset(),
) -> MinionSummary:
    """`cells` and `read_at`: the `@` columns' cells per minion, and when each of their sources
    was read, from `inventory_cells`."""
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    reads = read_at.get(minion.id, {})
    return MinionSummary(
        id=minion.id,
        status=minion_status(
            connected=minion.connected,
            last_seen_at=minion.last_seen_at,
            presence_at=presence.checked_at,
            now=now,
            stale_after=stale_after,
            observable=minion.id not in blind,
        ),
        connected=minion.connected,
        last_seen_at=minion.last_seen_at,
        key_state=minion.key_state,
        os=os_label(minion.grains),
        salt_version=grain_value(minion.grains, "saltversion"),
        ip=primary_ip(minion.grains),
        grains_at=minion.grains_at,
        grains_source=minion.grains_source,
        columns=column_values(minion, columns, cells.get(minion.id, {})),
        read_at={source: reads.get(source) for source in column_sources(runtime, columns)},
    )


@router.get("/fleet", response_model=Fleet)
async def fleet(
    runtime: RuntimeDep,
    session: SessionDep,
    column: Annotated[
        list[str] | None,
        Query(
            max_length=MAX_COLUMNS,
            description="columns to include (repeatable): a grain (`a:b` for nested), or a "
            "package's or check's key (`@packages:bash`); defaults to fleet.columns from the "
            "config",
        ),
    ] = None,
) -> Fleet:
    now = datetime.now(UTC)
    presence = await presence_info(session)
    columns = requested_columns(runtime, column)
    blind = await presence_blind(session)
    cells, read_at = await inventory_cells(session, runtime.settings, (c.grain for c in columns))
    rows = (await session.scalars(select(Minion).order_by(Minion.id))).all()
    accepted = [
        summarize(
            m, runtime, presence, now, columns=columns, cells=cells, read_at=read_at, blind=blind
        )
        for m in rows
        if m.key_state == "accepted"
    ]
    counts = {s: sum(1 for m in accepted if m.status is s) for s in Status}
    return Fleet(
        summary=FleetSummary(
            total=len(accepted),
            online=counts[Status.ONLINE],
            offline=counts[Status.OFFLINE],
            stale=counts[Status.STALE],
            unknown=counts[Status.UNKNOWN],
            pending_keys=sum(1 for m in rows if m.key_state == "pending"),
        ),
        columns=columns,
        default_columns=configured_columns(runtime),
        presence=presence,
        minions=accepted,
    )


@router.get("/grains/keys", response_model=list[GrainKey])
async def grain_keys(session: SessionDep) -> list[GrainKey]:
    """Every grain the fleet reports (one level into nested dicts, as `a:b`), with how many
    minions have it. Feeds the column picker's autocomplete."""
    counts: dict[str, int] = {}
    rows = await session.scalars(select(Minion.grains).where(Minion.key_state == "accepted"))
    for grains in rows:
        for key, value in (grains or {}).items():
            counts[key] = counts.get(key, 0) + 1
            if isinstance(value, dict):
                for sub in value:
                    path = f"{key}:{sub}"
                    counts[path] = counts.get(path, 0) + 1
    return [GrainKey(key=k, minions=n) for k, n in sorted(counts.items())]


def grain_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(grain_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


@router.get("/grains/values", response_model=GrainDistribution)
async def grain_values(
    session: SessionDep,
    grain: str = Query(..., min_length=1, description="grain name, or `a:b` for nested"),
) -> GrainDistribution:
    """How one grain's values are spread across the fleet (the Grains explorer)."""
    groups: dict[str, GrainValue] = {}
    missing: list[str] = []
    rows = (
        await session.execute(
            select(Minion.id, Minion.grains)
            .where(Minion.key_state == "accepted")
            .order_by(Minion.id)
        )
    ).all()
    for mid, grains in rows:
        value = grain_value(grains, grain)
        if value is None:
            missing.append(mid)
            continue
        key = json.dumps(value, sort_keys=True, default=str)
        group = groups.get(key)
        if group is None:
            group = groups[key] = GrainValue(value=value, text=grain_text(value), minions=[])
        group.minions.append(mid)
    values = sorted(groups.values(), key=lambda g: (-len(g.minions), g.text))
    return GrainDistribution(grain=grain, total=len(rows), values=values, missing=missing)


@router.get("/minions/{minion_id}", response_model=MinionDetail)
async def minion_detail(
    minion_id: str,
    runtime: RuntimeDep,
    session: SessionDep,
    history: int = Query(50, ge=0, le=500, description="presence changes to include"),
    jobs: int = Query(20, ge=0, le=200, description="recent jobs to include"),
) -> MinionDetail:
    minion = await session.get(Minion, minion_id)
    if minion is None:
        raise HTTPException(404, f"no minion {minion_id!r}")
    presence = await presence_info(session)
    columns = configured_columns(runtime)
    keys = (c.grain for c in columns)
    cells, read_at = await inventory_cells(session, runtime.settings, keys, minion=minion_id)
    summary = summarize(
        minion,
        runtime,
        presence,
        datetime.now(UTC),
        columns=columns,
        cells=cells,
        read_at=read_at,
        blind=await presence_blind(session),
    )

    changes = await session.scalars(
        select(PresenceChange)
        .where(PresenceChange.minion_id == minion_id)
        .order_by(PresenceChange.at.desc())
        .limit(history)
    )
    recent = await session.execute(
        select(
            Job.jid,
            Job.fun,
            Job.started_at,
            JobReturn.returned_at,
            JobReturn.success,
            JobReturn.retcode,
        )
        .join(JobReturn, JobReturn.jid == Job.jid)
        .where(JobReturn.minion_id == minion_id)
        .order_by(Job.started_at.desc())
        .limit(jobs)
    )
    waiting = await session.scalars(
        select(PendingRun)
        .where(PendingRun.minion_id == minion_id, PendingRun.state == "waiting")
        .order_by(PendingRun.created_at)
    )
    return MinionDetail(
        **summary.model_dump(),
        first_seen_at=minion.first_seen_at,
        grains=minion.grains,
        presence_history=[PresencePoint(at=c.at, connected=c.connected) for c in changes],
        recent_jobs=[MinionJob.model_validate(r, from_attributes=True) for r in recent],
        waiting_runs=[CatchUpRun.model_validate(r) for r in waiting],
    )


def diff_grains(old: dict[str, Any], new: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    added = {k: new[k] for k in new.keys() - old.keys()}
    removed = {k: old[k] for k in old.keys() - new.keys()}
    changed = {
        k: {"from": old[k], "to": new[k]} for k in new.keys() & old.keys() if old[k] != new[k]
    }
    return added, removed, changed


@router.get("/minions/{minion_id}/grains/history", response_model=list[GrainsChange])
async def grains_history(
    minion_id: str, session: SessionDep, limit: int = Query(20, ge=1, le=200)
) -> list[GrainsChange]:
    """Newest first. Each entry is what changed compared with the snapshot before it; the
    oldest entry shows every grain as "added"."""
    if await session.get(Minion, minion_id) is None:
        raise HTTPException(404, f"no minion {minion_id!r}")
    snapshots = (
        await session.scalars(
            select(GrainsSnapshot)
            .where(GrainsSnapshot.minion_id == minion_id)
            .order_by(GrainsSnapshot.collected_at.desc())
            .limit(limit + 1)
        )
    ).all()
    result = []
    for i, snap in enumerate(snapshots[:limit]):
        previous = snapshots[i + 1].grains if i + 1 < len(snapshots) else {}
        added, removed, changed = diff_grains(previous, snap.grains)
        result.append(
            GrainsChange(
                collected_at=snap.collected_at, added=added, removed=removed, changed=changed
            )
        )
    return result
