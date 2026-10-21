"""Packages and checks: the explorer, changes, one minion's entries, and Ask now.

Keys are `@packages:<name>` for a package, `@<check>:<name>` for a check's entry, and
`@<check>` for a check that prints a single value (see app/inventory.py).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import inventory
from app.api.deps import RuntimeDep, SessionDep
from app.api.errors import salt_http_error
from app.api.schemas import (
    AskRequest,
    AskResult,
    GrainValue,
    InventoryChangeView,
    InventoryDistribution,
    InventoryEntry,
    InventoryKey,
    InventorySource,
    MinionInventory,
)
from app.config import Settings
from app.inventory_sweep import Throttled, ask_now
from app.models import InventoryChange, InventoryItem, InventoryRead, Minion, SystemState
from app.runtime import Runtime
from app.salt.client import SaltApiError

router = APIRouter()


def _kind(source: str) -> Literal["package", "check"]:
    return "package" if source == inventory.PACKAGES else "check"


def _split(key: str, runtime: Runtime) -> tuple[str, str]:
    """`(source, name)` of a package's or a configured check's key; 422 for anything else,
    such as a grain."""
    parsed = inventory.configured_key(runtime.settings, key)
    if parsed is None:
        raise HTTPException(422, f"{key!r} isn't a package or a configured check")
    return parsed


async def refused_sources(session: AsyncSession, settings: Settings) -> dict[str, str]:
    """Why salt-api refuses to ask for each source it does, packages then each check. Only
    configured sources: a check removed from the config is never asked again, so its last
    refusal is never cleared."""
    row = await session.get(SystemState, inventory.REFUSED_STATE)
    why = (row.value or {}) if row is not None else {}
    return {source: why[source] for source in inventory.sources(settings) if source in why}


async def inventory_cells(
    session: AsyncSession, settings: Settings, keys: Iterable[str], minion: str | None = None
) -> dict[str, dict[str, str | None]]:
    """What the accepted minions (or just `minion`) have for each key: the value, or None
    (missing) when the minion's last good read of that source is whole and doesn't list it.
    A key left out is unknown: no good read yet, or one cut short that doesn't list it. A key
    that isn't a package or a configured check is unknown everywhere (a browser may keep a
    removed check's column). The explorer and the fleet's columns both go by this."""
    by_entry: dict[tuple[str, str], list[str]] = {}  # (source, name) -> its keys
    by_source: dict[str, list[str]] = {}
    for key in dict.fromkeys(keys):
        if (parsed := inventory.configured_key(settings, key)) is not None:
            by_entry.setdefault(parsed, []).append(key)
            by_source.setdefault(parsed[0], []).append(key)
    if not by_entry:
        return {}
    whose = [Minion.key_state == "accepted"]
    if minion is not None:
        whose.append(Minion.id == minion)
    whole = (
        select(InventoryRead.minion_id, InventoryRead.source)
        .join(Minion, Minion.id == InventoryRead.minion_id)
        .where(
            *whose,
            InventoryRead.source.in_(list(by_source)),
            InventoryRead.read_at.is_not(None),
            InventoryRead.truncated.is_(False),
        )
    )
    entries = or_(*(and_(InventoryItem.source == s, InventoryItem.name == n) for s, n in by_entry))
    held = (
        select(
            InventoryItem.minion_id, InventoryItem.source, InventoryItem.name, InventoryItem.value
        )
        .join(Minion, Minion.id == InventoryItem.minion_id)
        .where(*whose, entries)
    )
    cells: dict[str, dict[str, str | None]] = {}
    for mid, source in await session.execute(whole):
        for key in by_source[source]:
            cells.setdefault(mid, {})[key] = None
    for mid, source, name, value in await session.execute(held):
        for key in by_entry[(source, name)]:
            cells.setdefault(mid, {})[key] = value
    return cells


def _has(column: Any, needle: str) -> Any:
    """Case-insensitively contains `needle`, taken as typed (% and _ aren't wildcards)."""
    return func.lower(column).contains(needle, autoescape=True)


@router.get("/inventory/keys", response_model=list[InventoryKey])
async def inventory_keys(
    runtime: RuntimeDep,
    session: SessionDep,
    q: str = Query("", description="part of a name; packages are only listed for a search"),
    limit: int = Query(50, ge=1, le=200),
) -> list[InventoryKey]:
    """Packages and check entries the fleet has, with how many minions have each: every
    configured check's entries, and the packages whose name contains `q`. With `q`, checks
    are searched too (by entry or check name). Feeds the explorer's picker."""
    checks = list(runtime.settings.inventory.checks)
    needle = q.strip().lower()
    if needle:
        wanted = or_(
            and_(InventoryItem.source == inventory.PACKAGES, _has(InventoryItem.name, needle)),
            and_(
                InventoryItem.source.in_(checks),
                or_(_has(InventoryItem.name, needle), _has(InventoryItem.source, needle)),
            ),
        )
    elif checks:
        wanted = InventoryItem.source.in_(checks)
    else:
        return []
    rows = await session.execute(
        select(InventoryItem.source, InventoryItem.name, func.count())
        .join(Minion, Minion.id == InventoryItem.minion_id)
        .where(Minion.key_state == "accepted", wanted)
        .group_by(InventoryItem.source, InventoryItem.name)
        .order_by(InventoryItem.source, InventoryItem.name)
        .limit(limit)
    )
    return [
        InventoryKey(
            key=inventory.key_of(source, name),
            source=source,
            name=name,
            kind=_kind(source),
            minions=count,
        )
        for source, name, count in rows
    ]


@router.get("/inventory/values", response_model=InventoryDistribution)
async def inventory_values(
    runtime: RuntimeDep,
    session: SessionDep,
    key: str = Query(..., min_length=1, description="`@packages:<name>`, or a check's key"),
) -> InventoryDistribution:
    """How one package's versions (or one check entry's values) are spread across the fleet:
    which minions have which, which answered without it, and which haven't answered yet."""
    source, name = _split(key, runtime)
    accepted = (
        await session.scalars(
            select(Minion.id).where(Minion.key_state == "accepted").order_by(Minion.id)
        )
    ).all()
    cells = await inventory_cells(session, runtime.settings, [key])
    groups: dict[str, list[str]] = {}
    missing: list[str] = []
    unknown: list[str] = []
    for mid in accepted:
        cell = cells.get(mid, {})
        if key not in cell:
            unknown.append(mid)
        elif (value := cell[key]) is None:
            missing.append(mid)
        else:
            groups.setdefault(value, []).append(mid)
    # How old the accepted minions' last good reads of the source are (cut short or not).
    times = [
        at
        for at in await session.scalars(
            select(InventoryRead.read_at)
            .join(Minion, Minion.id == InventoryRead.minion_id)
            .where(Minion.key_state == "accepted", InventoryRead.source == source)
        )
        if at is not None
    ]
    package = source == inventory.PACKAGES
    newest_first = sorted(
        groups.items(),
        key=lambda g: (inventory.version_key(g[0], package=package), g[0]),
        reverse=True,
    )
    refused = await refused_sources(session, runtime.settings)
    return InventoryDistribution(
        key=inventory.key_of(source, name),
        source=source,
        name=name,
        kind=_kind(source),
        total=len(accepted),
        values=[GrainValue(value=v, text=v, minions=mids) for v, mids in newest_first],
        missing=missing,
        unknown=unknown,
        oldest_read_at=min(times, default=None),
        newest_read_at=max(times, default=None),
        refused=refused.get(source),
    )


@router.get("/inventory/changes", response_model=list[InventoryChangeView])
async def inventory_changes(
    runtime: RuntimeDep,
    session: SessionDep,
    key: str | None = Query(None, description="only this package or check entry"),
    minion: str | None = Query(None, description="only this minion"),
    limit: int = Query(100, ge=1, le=500),
) -> list[InventoryChangeView]:
    """What appeared, changed or went away, newest first."""
    query = select(InventoryChange)
    if key is not None:
        source, name = _split(key, runtime)
        query = query.where(InventoryChange.source == source, InventoryChange.name == name)
    if minion is not None:
        query = query.where(InventoryChange.minion_id == minion)
    rows = await session.scalars(
        query.order_by(InventoryChange.at.desc(), InventoryChange.id.desc()).limit(limit)
    )
    return [InventoryChangeView.model_validate(c, from_attributes=True) for c in rows]


@router.get("/minions/{minion_id}/inventory", response_model=MinionInventory)
async def minion_inventory(
    minion_id: str, runtime: RuntimeDep, session: SessionDep
) -> MinionInventory:
    """Everything one minion said it has, per source (packages, then each configured check),
    with when it was read. Sources never read are listed too, empty."""
    if await session.get(Minion, minion_id) is None:
        raise HTTPException(404, f"no minion {minion_id!r}")
    reads = {
        read.source: read
        for read in await session.scalars(select(InventoryRead).filter_by(minion_id=minion_id))
    }
    entries: dict[str, list[InventoryEntry]] = {}
    for item in await session.scalars(
        select(InventoryItem).filter_by(minion_id=minion_id).order_by(InventoryItem.name)
    ):
        entries.setdefault(item.source, []).append(
            InventoryEntry(name=item.name, value=item.value, since=item.since)
        )
    found = []
    for source in inventory.sources(runtime.settings):
        read = reads.get(source)
        found.append(
            InventorySource(
                source=source,
                kind=_kind(source),
                read_at=read.read_at if read else None,
                first_read_at=read.first_read_at if read else None,
                answered_at=read.answered_at if read else None,
                error=read.error if read else None,
                truncated=bool(read and read.truncated),
                entries=entries.get(source, []),
            )
        )
    return MinionInventory(sources=found)


@router.post("/inventory/ask", response_model=AskResult)
async def inventory_ask(body: AskRequest, runtime: RuntimeDep, session: SessionDep) -> AskResult:
    """Ask the online minions (or one) for their packages and checks now, due or not. The
    whole fleet is queued for the sweep; one minion is asked straight away. Open to every
    role, as it only reads; the answers arrive as they come.

    429 (with Retry-After) when asked too soon; salt-api's error when nothing could be
    asked."""
    if body.minion is not None and await session.get(Minion, body.minion) is None:
        raise HTTPException(404, f"no minion {body.minion!r}")
    try:
        done = await ask_now(runtime, body.minion, datetime.now(UTC))
    except Throttled as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)}) from exc
    except SaltApiError as exc:
        raise salt_http_error(exc) from exc
    return AskResult(asked=done.asked, queued=done.queued, failed=done.failed, reason=done.reason)
