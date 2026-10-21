"""Presence: who the last presence check found connected, and whether that can be trusted.

The collector records each check (app/ingest.py, PRESENCE_STATE) and each minion's `connected`.
"Connected" is only trusted while the check is fresh: no older than `fleet.stale_after_minutes`.

Plain helpers with no app.api imports, so background work (catch-up runs, the inventory sweep)
and the API can share them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ingest import PRESENCE_STATE
from app.models import Minion, SystemState

# Accepted minions the last presence check found connected (trust it only when fresh).
CONNECTED = (Minion.connected.is_(True), Minion.key_state == "accepted")


async def read_presence(s: AsyncSession) -> tuple[str | None, datetime | None]:
    """`(method, checked_at)` of the last presence check; Nones if there hasn't been one."""
    row = await s.get(SystemState, PRESENCE_STATE)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    at = value.get("at")
    return value.get("method"), datetime.fromisoformat(at) if at else None


def is_fresh(checked_at: datetime | None, now: datetime, settings: Settings) -> bool:
    """Whether a presence check made at `checked_at` can still be trusted at `now`."""
    stale_after = timedelta(minutes=settings.fleet.stale_after_minutes)
    return checked_at is not None and now - checked_at <= stale_after


async def connected_minions(
    s: AsyncSession, settings: Settings, now: datetime, only: str | None = None
) -> list[str]:
    """Accepted minions a fresh presence check found connected (just `only`, if given), by ID.
    Empty when presence is stale."""
    _, checked_at = await read_presence(s)
    if not is_fresh(checked_at, now, settings):
        return []
    query = select(Minion.id).where(*CONNECTED)
    if only is not None:
        query = query.where(Minion.id == only)
    return list((await s.scalars(query.order_by(Minion.id))).all())
