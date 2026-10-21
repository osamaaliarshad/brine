"""Packages and checks: the explorer, changes, one minion's entries, and Ask now.

Keys are `@packages:<name>` for a package, `@<check>:<name>` for a check's entry, and
`@<check>` for a check that prints a single value (see app/inventory.py).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, or_, select

# inventory_sweep imports app.api, so it may still be loading here: use it as a module, not
# `from app.inventory_sweep import ...`.
from app import inventory, inventory_sweep
from app.api.deps import RuntimeDep, SessionDep
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
from app.models import InventoryChange, InventoryItem, InventoryRead, Minion, SystemState
from app.runtime import Runtime

router = APIRouter()

_DIGITS = re.compile(r"([0-9]+)")


def version_key(text: str) -> list[tuple[int, int | str]]:
    """Natural order, so 2.10 comes after 2.9: runs of digits compare as numbers."""
    # Split with a group, so the digit runs are every other part.
    parts = _DIGITS.split(text)
    return [(0, int(part)) if i % 2 else (1, part) for i, part in enumerate(parts) if part]


def _kind(source: str) -> Literal["package", "check"]:
    return "package" if source == inventory.PACKAGES else "check"


def _split(key: str, runtime: Runtime) -> tuple[str, str]:
    """`(source, name)` of a package's or a configured check's key; 422 for anything else,
    such as a grain."""
    parsed = inventory.parse_key(key)
    if (
        parsed is None
        or parsed[0] not in inventory.sources(runtime.settings)
        or parsed == (inventory.PACKAGES, "")
    ):
        raise HTTPException(422, f"{key!r} isn't a package or a configured check")
    return parsed


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
    # Minions with a good read of the source (a failed answer only isn't one).
    read_at: dict[str, datetime] = {
        mid: at
        for mid, at in await session.execute(
            select(InventoryRead.minion_id, InventoryRead.read_at).where(
                InventoryRead.source == source
            )
        )
        if at is not None
    }
    held: dict[str, str] = {
        mid: value
        for mid, value in await session.execute(
            select(InventoryItem.minion_id, InventoryItem.value).where(
                InventoryItem.source == source, InventoryItem.name == name
            )
        )
    }
    groups: dict[str, list[str]] = {}
    missing: list[str] = []
    unknown: list[str] = []
    for mid in accepted:
        if mid in held:
            groups.setdefault(held[mid], []).append(mid)
        elif mid in read_at:
            missing.append(mid)
        else:
            unknown.append(mid)
    times = [read_at[mid] for mid in accepted if mid in read_at]
    newest_first = sorted(groups.items(), key=lambda g: (version_key(g[0]), g[0]), reverse=True)
    refused = await session.get(SystemState, inventory.REFUSED_STATE)
    return InventoryDistribution(
        key=key,
        source=source,
        name=name,
        kind=_kind(source),
        total=len(accepted),
        values=[GrainValue(value=v, text=v, minions=mids) for v, mids in newest_first],
        missing=missing,
        unknown=unknown,
        oldest_read_at=min(times, default=None),
        newest_read_at=max(times, default=None),
        refused=(refused.value or {}).get(source) if refused is not None else None,
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
async def ask_now(body: AskRequest, runtime: RuntimeDep, session: SessionDep) -> AskResult:
    """Ask the online minions (or one) for their packages and checks now, due or not. Open to
    every role, as it only reads; the answers arrive as they come."""
    if body.minion is not None and await session.get(Minion, body.minion) is None:
        raise HTTPException(404, f"no minion {body.minion!r}")
    asked = await inventory_sweep.ask_now(runtime, body.minion, datetime.now(UTC))
    if asked is None:
        raise HTTPException(429, "Asked a moment ago; try again in a minute.")
    return AskResult(asked=asked)
