"""Packages and checks: the explorer, changes, one minion's entries, and Read now.

Keys are `@packages:<name>` for a package, `@<check>:<name>` for a check's entry, and
`@<check>` for a check that prints a single value (see app/inventory.py).
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, and_, case, func, inspect, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import aliased
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.selectable import FromClause, Join

from app import inventory
from app.api.deps import RuntimeDep, SessionDep
from app.api.errors import salt_http_error
from app.api.schemas import (
    AskRequest,
    AskResult,
    ComparedMinion,
    FleetComparison,
    GrainValue,
    InventoryChangeView,
    InventoryDifference,
    InventoryDistribution,
    InventoryEntry,
    InventoryKey,
    InventorySource,
    MinionComparison,
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
) -> tuple[dict[str, dict[str, str | None]], dict[str, dict[str, datetime | None]]]:
    """What the accepted minions (or just `minion`) have for each key: the value, or None
    (missing) when the minion's last good read of that source is whole and doesn't list it.
    A key left out is unknown: no good read yet, or one cut short that doesn't list it. A key
    that isn't a package or a configured check is unknown everywhere (a browser may keep a
    removed check's column). The explorer and the fleet's columns both go by this.

    Also when each minion's last whole read of each of those sources was: what its cells are as
    of. A read cut short has no time, as what it doesn't list isn't known as of then."""
    by_entry: dict[tuple[str, str], list[str]] = {}  # (source, name) -> its keys
    by_source: dict[str, list[str]] = {}
    for key in dict.fromkeys(keys):
        if (parsed := inventory.configured_key(settings, key)) is not None:
            by_entry.setdefault(parsed, []).append(key)
            by_source.setdefault(parsed[0], []).append(key)
    if not by_entry:
        return {}, {}
    whose = [Minion.key_state == "accepted"]
    if minion is not None:
        whose.append(Minion.id == minion)
    whole = (
        select(InventoryRead.minion_id, InventoryRead.source, InventoryRead.read_at)
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
    read_at: dict[str, dict[str, datetime | None]] = {}
    for mid, source, at in await session.execute(whole):
        read_at.setdefault(mid, {})[source] = at
        for key in by_source[source]:
            cells.setdefault(mid, {})[key] = None
    for mid, source, name, value in await session.execute(held):
        for key in by_entry[(source, name)]:
            cells.setdefault(mid, {})[key] = value
    return cells, read_at


def _has(column: Any, needle: str) -> Any:
    """Case-insensitively contains `needle`, taken as typed (% and _ aren't wildcards)."""
    return func.lower(column).contains(needle, autoescape=True)


DIFFERING_SECONDS = 60
_DIFFERING_MEMO = "inventory-differing"


async def differing_packages(runtime: Runtime, session: AsyncSession) -> list[str]:
    """The packages that differ across the fleet, by name: those the accepted minions with a
    whole good read of their packages don't all have at one version, or don't all have.
    Minions without such a read don't count. Worked out in the database, but it goes through
    every package row (500 robots with 1,500 packages each are 750,000 rows, a third of a second
    or so), so the list is kept in runtime.memo for a minute."""
    cached = runtime.memo.get(_DIFFERING_MEMO)
    if cached and time.monotonic() - cached[0] < DIFFERING_SECONDS:
        return list(cached[1])
    whole = (
        _whole_reads(runtime.settings)
        .join(Minion, Minion.id == InventoryRead.minion_id)
        .where(Minion.key_state == "accepted", InventoryRead.source == inventory.PACKAGES)
        .subquery()
    )
    read = await session.scalar(select(func.count()).select_from(whole))
    names = list(
        await session.scalars(
            select(InventoryItem.name)
            .where(
                InventoryItem.source == inventory.PACKAGES,
                InventoryItem.minion_id.in_(select(whole.c.minion_id)),
            )
            .group_by(InventoryItem.name)
            .having(or_(func.count(InventoryItem.value.distinct()) > 1, func.count() < read))
            .order_by(InventoryItem.name)
        )
    )
    runtime.memo[_DIFFERING_MEMO] = (time.monotonic(), names)
    return list(names)


@router.get("/inventory/keys", response_model=list[InventoryKey])
async def inventory_keys(
    runtime: RuntimeDep,
    session: SessionDep,
    q: str = Query("", description="part of a name; without it, packages that differ"),
    limit: int = Query(50, ge=1, le=200),
) -> list[InventoryKey]:
    """Packages and check entries the fleet has, with how many minions have each. Without `q`:
    every configured check's entries, then the packages that differ across the fleet (see
    differing_packages). With `q`: the packages whose name contains it, and the check entries
    whose name or check's name does. Feeds the explorer's picker."""
    checks = list(runtime.settings.inventory.checks)
    needle = q.strip().lower()
    packages = InventoryItem.source == inventory.PACKAGES
    if needle:
        wanted = or_(
            and_(packages, _has(InventoryItem.name, needle)),
            and_(
                InventoryItem.source.in_(checks),
                or_(_has(InventoryItem.name, needle), _has(InventoryItem.source, needle)),
            ),
        )
        order: list[Any] = [InventoryItem.source, InventoryItem.name]
    else:
        differing = (await differing_packages(runtime, session))[:limit]
        if not checks and not differing:
            return []
        wanted = or_(
            InventoryItem.source.in_(checks), and_(packages, InventoryItem.name.in_(differing))
        )
        # The checks first, as the picker lists them first.
        order = [case((packages, 1), else_=0), InventoryItem.source, InventoryItem.name]
    rows = await session.execute(
        select(InventoryItem.source, InventoryItem.name, func.count())
        .join(Minion, Minion.id == InventoryItem.minion_id)
        .where(Minion.key_state == "accepted", wanted)
        .group_by(InventoryItem.source, InventoryItem.name)
        .order_by(*order)
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
    which minions have which, which answered without it, which couldn't say, and which haven't
    answered yet."""
    source, name = _split(key, runtime)
    accepted = (
        await session.scalars(
            select(Minion.id).where(Minion.key_state == "accepted").order_by(Minion.id)
        )
    ).all()
    cells, _ = await inventory_cells(session, runtime.settings, [key])
    # Whose last answer for the source was an error.
    errored = set(
        await session.scalars(
            select(InventoryRead.minion_id).where(
                InventoryRead.source == source, InventoryRead.error.is_not(None)
            )
        )
    )
    groups: dict[str, list[str]] = {}
    missing: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []
    for mid in accepted:
        cell = cells.get(mid, {})
        if key not in cell:
            (failed if mid in errored else unknown).append(mid)
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
        failed=failed,
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
    limit: int = Query(100, ge=1, le=1000),
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
    refused = await refused_sources(session, runtime.settings)
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
                refused=refused.get(source),
                entries=entries.get(source, []),
            )
        )
    return MinionInventory(sources=found)


async def _accepted(session: AsyncSession, minion_id: str) -> None:
    """404 unless brine has the minion and its key is accepted."""
    minion = await session.get(Minion, minion_id)
    if minion is None or minion.key_state != "accepted":
        raise HTTPException(404, f"no accepted minion {minion_id!r}")


class _CrossJoin(Join):
    """``left CROSS JOIN right``: SQLite always loops over `left` first, whatever its statistics
    say (PostgreSQL takes it as a plain join). What joins them goes in the WHERE clause. See
    "Manual Control Of Query Plans Using CROSS JOIN" in SQLite's query optimizer overview:
    https://www.sqlite.org/optoverview.html#crossjoin"""

    inherit_cache = True

    def __init__(self, left: FromClause, right: FromClause) -> None:
        super().__init__(left, right, true())


@compiles(_CrossJoin)
def _cross_join(join: _CrossJoin, compiler: SQLCompiler, **kw: Any) -> str:
    kw["asfrom"] = True
    return f"{compiler.process(join.left, **kw)} CROSS JOIN {compiler.process(join.right, **kw)}"


def _whole_reads(settings: Settings) -> Select[str, str]:
    """`(minion_id, source)` of each good read not cut short, of a configured source. Only
    these are compared: a source missing from one side, or cut short, would count as gone."""
    return select(InventoryRead.minion_id, InventoryRead.source).where(
        InventoryRead.source.in_(inventory.sources(settings)),
        InventoryRead.read_at.is_not(None),
        InventoryRead.truncated.is_(False),
    )


@router.get("/inventory/compare", response_model=FleetComparison)
async def compare_fleet(
    runtime: RuntimeDep,
    session: SessionDep,
    reference: str = Query(..., description="the minion every other one is compared with"),
) -> FleetComparison:
    """How each other accepted minion's packages and checks differ from `reference`'s, over the
    sources both have read whole. Counted in the database: a fleet can be 500 minions with 1,500
    packages each."""
    await _accepted(session, reference)
    ref_reads = _whole_reads(runtime.settings).where(InventoryRead.minion_id == reference)
    whole = _whole_reads(runtime.settings).subquery()
    shared = (
        select(whole.c.minion_id, whole.c.source)
        .join(Minion, Minion.id == whole.c.minion_id)
        .where(
            Minion.key_state == "accepted",
            Minion.id != reference,
            whole.c.source.in_(ref_reads.with_only_columns(InventoryRead.source)),
        )
        .subquery()
    )
    ref, theirs = aliased(InventoryItem), aliased(InventoryItem)
    # Each of the reference's entries, looked up on the minion: there (with the same value or
    # another), or missing. Both lookups go by the primary key. A cross join, so it stays one
    # minion at a time: with statistics (ANALYZE), SQLite would rather go through the
    # reference's entries first and sort every row to group them, about ten times slower.
    from_reference = (
        select(
            shared.c.minion_id,
            shared.c.source,
            func.count(theirs.name).label("both"),
            func.sum(case((theirs.name.is_(None), 1), else_=0)).label("missing"),
            func.sum(case((theirs.value != ref.value, 1), else_=0)).label("different"),
        )
        .select_from(_CrossJoin(shared, inspect(ref).selectable))
        .where(ref.minion_id == reference, ref.source == shared.c.source)
        .outerjoin(
            theirs,
            and_(
                theirs.minion_id == shared.c.minion_id,
                theirs.source == ref.source,
                theirs.name == ref.name,
            ),
        )
        .group_by(shared.c.minion_id, shared.c.source)
        .subquery()
    )
    # How many entries each minion has of each source both read: those the reference doesn't
    # have are the rest. Counted per source by the primary key; joined to the entries instead,
    # SQLite goes through the name index and sorts them all, several times slower.
    entries = (
        select(func.count())
        .where(
            InventoryItem.minion_id == shared.c.minion_id,
            InventoryItem.source == shared.c.source,
        )
        .scalar_subquery()
    )
    # One statement, so a read stored in between can't put the two counts out of step.
    counted = await session.execute(
        select(
            shared.c.minion_id,
            shared.c.source,
            entries.label("total"),
            func.coalesce(from_reference.c.both, 0).label("both"),
            func.coalesce(from_reference.c.missing, 0).label("missing"),
            func.coalesce(from_reference.c.different, 0).label("different"),
        )
        .select_from(shared)
        .outerjoin(
            from_reference,
            and_(
                from_reference.c.minion_id == shared.c.minion_id,
                from_reference.c.source == shared.c.source,
            ),
        )
    )
    order = inventory.sources(runtime.settings)
    found: dict[str, ComparedMinion] = {}
    for row in counted.mappings():
        mid = row["minion_id"]
        m = found.setdefault(
            mid,
            ComparedMinion(
                minion_id=mid,
                read=True,
                sources_compared=[],
                different=0,
                only_reference=0,
                only_minion=0,
            ),
        )
        m.sources_compared.append(row["source"])
        m.different += int(row["different"])
        m.only_reference += int(row["missing"])
        m.only_minion += max(0, int(row["total"]) - int(row["both"]))
    for m in found.values():
        m.sources_compared.sort(key=order.index)
    others = await session.scalars(
        select(Minion.id)
        .where(Minion.key_state == "accepted", Minion.id != reference)
        .order_by(Minion.id)
    )
    rows = [
        found.get(mid)
        or ComparedMinion(
            minion_id=mid,
            read=False,
            sources_compared=[],
            different=0,
            only_reference=0,
            only_minion=0,
        )
        for mid in others
    ]
    ref_sources = set(await session.scalars(ref_reads.with_only_columns(InventoryRead.source)))
    return FleetComparison(
        reference=reference,
        reference_sources=[s for s in order if s in ref_sources],
        minions=rows,
    )


@router.get("/inventory/compare/{minion_id}", response_model=MinionComparison)
async def compare_minion(
    minion_id: str,
    runtime: RuntimeDep,
    session: SessionDep,
    reference: str = Query(..., description="the minion to compare it with"),
) -> MinionComparison:
    """Every package or check entry where `minion_id` differs from `reference`, over the
    sources both have read whole: a different value, or there on one side only."""
    await _accepted(session, reference)
    await _accepted(session, minion_id)
    both = [reference, minion_id]
    order = inventory.sources(runtime.settings)
    whole = set(
        await session.execute(
            _whole_reads(runtime.settings).where(InventoryRead.minion_id.in_(both))
        )
    )
    compared = [s for s in order if (reference, s) in whole and (minion_id, s) in whole]
    items: dict[str, dict[tuple[str, str], str]] = {reference: {}, minion_id: {}}
    for mid, source, name, value in await session.execute(
        select(
            InventoryItem.minion_id, InventoryItem.source, InventoryItem.name, InventoryItem.value
        ).where(InventoryItem.minion_id.in_(both), InventoryItem.source.in_(compared))
    ):
        items[mid][(source, name)] = value
    ours, theirs = items[reference], items[minion_id]
    rank = {source: i for i, source in enumerate(order)}
    entries = sorted(ours.keys() | theirs.keys(), key=lambda e: (rank[e[0]], e[1]))
    return MinionComparison(
        reference=reference,
        minion=minion_id,
        sources_compared=compared,
        differences=[
            InventoryDifference(source=entry[0], name=entry[1], reference=a, minion=b)
            for entry in entries
            if (a := ours.get(entry)) != (b := theirs.get(entry))
        ],
    )


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
