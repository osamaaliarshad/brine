"""Packages and checks, asked for: the sweep and Ask now (the rules are in app/inventory.py).

Every few seconds the sweep asks the connected minions for each source they're due a read of,
in one job per source. Ask now asks every source at once, for the fleet or one minion. The
answers come back on the event bus like any job's, and the collector stores them.

Kept apart from app/inventory.py, which `Ingest` imports: this side needs the running app.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.fleet import presence_info
from app.inventory import (
    CHECK_FUN,
    PACKAGES,
    PACKAGES_FUN,
    REFUSED_STATE,
    ReadState,
    is_due,
    sources,
)
from app.models import InventoryRead, Minion, PresenceChange
from app.runtime import Runtime
from app.salt.client import SaltApiError, SaltApiForbidden

log = logging.getLogger(__name__)

SWEEP_SECONDS = 15
# One sweep asks at most this many minions per source; the rest follow on the next sweeps.
BATCH = 200
ASK_ALL_EVERY = 60.0  # Ask now for the whole fleet: at most once a minute
ASK_ONE_EVERY = 10.0  # and for one minion, at most every ten seconds

# Accepted minions the last presence check found connected.
_CONNECTED = (Minion.connected.is_(True), Minion.key_state == "accepted")


async def ask(runtime: Runtime, source: str, mids: list[str], now: datetime) -> bool:
    """Ask these minions for one source, in one job. `now` is brine's clock, read before
    sending. False if salt-api refused or failed."""
    if not mids:
        return True
    target = ",".join(mids)
    try:
        if source == PACKAGES:
            jid = await runtime.client.local_async(target, PACKAGES_FUN, tgt_type="list")
        else:
            command = runtime.settings.inventory.checks[source]
            jid = await runtime.client.local_async(
                target, CHECK_FUN, arg=[command], tgt_type="list"
            )
    except SaltApiForbidden as exc:
        # Shown in Settings and Issues. No job started, so it's waited for like an ask that
        # matched no minion: each refusal makes brine log in to salt-api again, so it isn't
        # asked again on every sweep.
        await runtime.ingest.set_state_entry(REFUSED_STATE, source, str(exc))
        await runtime.ingest.inventory_asked(mids, source, at=now, jid=None)
        return False
    except SaltApiError as exc:
        log.warning("couldn't ask %d minion(s) for %s: %s", len(mids), source, exc)
        return False
    await runtime.ingest.set_state_entry(REFUSED_STATE, source, None)
    # The answer can only be matched to this ask once it's recorded. One that beats it counts
    # as someone else's (no credit, the want stays), and the next ask settles it.
    await runtime.ingest.inventory_asked(mids, source, at=now, jid=jid)
    return True


async def _online(
    s: AsyncSession, runtime: Runtime, now: datetime, only: str | None = None
) -> list[str]:
    presence = await presence_info(s)
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    # Only trust "connected" from a fresh presence check.
    if presence.checked_at is None or now - presence.checked_at > stale_after:
        return []
    query = select(Minion.id).where(*_CONNECTED)
    if only is not None:
        query = query.where(Minion.id == only)
    return list((await s.scalars(query.order_by(Minion.id))).all())


async def online(runtime: Runtime, now: datetime, only: str | None = None) -> list[str]:
    """Accepted minions a fresh presence check says are connected (just `only`, if given)."""
    async with runtime.sessions() as s:
        return await _online(s, runtime, now, only)


def _state(read: InventoryRead | None) -> ReadState | None:
    if read is None:
        return None
    return ReadState(
        asked_jid=read.asked_jid,
        asked_at=read.asked_at,
        answered_at=read.answered_at,
        wanted_at=read.wanted_at,
    )


async def sweep(runtime: Runtime, now: datetime | None = None) -> None:
    """Ask the connected minions for each source they're due, BATCH at a time per source."""
    now = now or datetime.now(UTC)
    every = timedelta(hours=runtime.settings.inventory.refresh_hours)
    async with runtime.sessions() as s:
        mids = await _online(s, runtime, now)
        if not mids:
            return
        reads = {
            (read.minion_id, read.source): read
            for read in await s.scalars(
                select(InventoryRead)
                .join(Minion, Minion.id == InventoryRead.minion_id)
                .where(*_CONNECTED)
            )
        }
        # When each last came online: one back since its last answer is read again.
        back = {
            mid: at
            for mid, at in await s.execute(
                select(PresenceChange.minion_id, func.max(PresenceChange.at))
                .join(Minion, Minion.id == PresenceChange.minion_id)
                .where(PresenceChange.connected.is_(True), *_CONNECTED)
                .group_by(PresenceChange.minion_id)
            )
        }
    for source in sources(runtime.settings):
        due = [
            mid
            for mid in mids
            if is_due(_state(reads.get((mid, source))), now=now, every=every, back_at=back.get(mid))
        ]
        await ask(runtime, source, due[:BATCH], now)


async def ask_now(runtime: Runtime, minion: str | None, now: datetime) -> list[str] | None:
    """Ask now: every source, from the online minions (or `minion`, if it's online), whether
    they're due or not. Returns the minions asked; None when asked too recently."""
    if minion is None:
        key, every = "inventory-ask", ASK_ALL_EVERY
    else:
        key, every = f"inventory-ask:{minion}", ASK_ONE_EVERY
    last = runtime.memo.get(key)
    if last is not None and time.monotonic() - last[0] < every:
        return None
    runtime.memo[key] = (time.monotonic(), None)
    mids = await online(runtime, now, only=minion)
    for source in sources(runtime.settings):
        await ask(runtime, source, mids, now)
    return mids


async def run_forever(runtime: Runtime) -> None:
    while True:
        try:
            await sweep(runtime)
        except Exception:  # a bad sweep mustn't stop the next one
            log.exception("inventory sweep failed")
        await asyncio.sleep(SWEEP_SECONDS)
