from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import RuntimeDep, SessionDep
from app.api.schemas import (
    Column,
    Fleet,
    FleetSummary,
    GrainsChange,
    MinionDetail,
    MinionJob,
    MinionSummary,
    PresenceInfo,
    PresencePoint,
)
from app.ingest import PRESENCE_STATE
from app.models import GrainsSnapshot, Job, JobReturn, Minion, PresenceChange, SystemState
from app.runtime import Runtime
from app.status import Status, minion_status

router = APIRouter()


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
    row = await session.get(SystemState, PRESENCE_STATE)
    value = row.value if row is not None else {}
    at = value.get("at") if isinstance(value, dict) else None
    return PresenceInfo(
        method=value.get("method") if isinstance(value, dict) else None,
        checked_at=datetime.fromisoformat(at) if at else None,
    )


def summarize(
    minion: Minion, runtime: Runtime, presence: PresenceInfo, now: datetime
) -> MinionSummary:
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    return MinionSummary(
        id=minion.id,
        status=minion_status(
            connected=minion.connected,
            last_seen_at=minion.last_seen_at,
            presence_at=presence.checked_at,
            now=now,
            stale_after=stale_after,
        ),
        connected=minion.connected,
        last_seen_at=minion.last_seen_at,
        key_state=minion.key_state,
        os=os_label(minion.grains),
        salt_version=grain_value(minion.grains, "saltversion"),
        ip=primary_ip(minion.grains),
        grains_at=minion.grains_at,
        grains_source=minion.grains_source,
        columns={
            c.grain: grain_value(minion.grains, c.grain) for c in runtime.settings.fleet.columns
        },
    )


@router.get("/fleet", response_model=Fleet)
async def fleet(runtime: RuntimeDep, session: SessionDep) -> Fleet:
    now = datetime.now(UTC)
    presence = await presence_info(session)
    rows = (await session.scalars(select(Minion).order_by(Minion.id))).all()
    accepted = [summarize(m, runtime, presence, now) for m in rows if m.key_state == "accepted"]
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
        columns=[
            Column(grain=c.grain, label=c.label or c.grain) for c in runtime.settings.fleet.columns
        ],
        presence=presence,
        minions=accepted,
    )


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
    summary = summarize(minion, runtime, presence, datetime.now(UTC))

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
    return MinionDetail(
        **summary.model_dump(),
        first_seen_at=minion.first_seen_at,
        grains=minion.grains,
        presence_history=[PresencePoint(at=c.at, connected=c.connected) for c in changes],
        recent_jobs=[MinionJob.model_validate(r, from_attributes=True) for r in recent],
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
