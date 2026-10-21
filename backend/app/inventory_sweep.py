"""Packages and checks, asked for: the sweep and Read now (the rules are in app/inventory.py).

Every few seconds the sweep asks the connected minions for each source they're due a read of,
in one job per source, BATCH minions at a time. Read now for the whole fleet makes every online
minion due, so the sweep asks them over the next sweeps; for one minion it asks straight away.
The answers come back on the event bus like any job's, and the collector stores them.

Kept apart from app/inventory.py, which `Ingest` imports: this side needs the running app.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

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
from app.presence import CONNECTED, connected_minions, is_fresh, read_presence
from app.runtime import Runtime
from app.salt.client import SaltApiError, SaltApiForbidden

log = logging.getLogger(__name__)

SWEEP_SECONDS = 15
# One sweep asks at most this many minions per source; the rest follow on the next sweeps.
BATCH = 200
ASK_ALL_EVERY = 60.0  # Read now for the whole fleet: at most once a minute
ASK_ONE_EVERY = 10.0  # and for one minion, at most every ten seconds
# Read now for one minion: at most this many a minute, whichever minions, so a script asking
# each in turn can't get round the fleet's once a minute. One sweep's worth.
ONE_BY_ONE_PER_MINUTE = BATCH
_MINUTE = 60.0
# In the sweep's turns, a minion never asked counts as asked before anyone.
_NEVER = datetime.min.replace(tzinfo=UTC)

# Why Read now asked nobody, as the UI shows it after "Nobody was asked: ".
STALE = "brine hasn't checked who's online recently; try again in a minute"
NOBODY = "no minions are online"

# runtime.memo keys: the last fleet-wide Read now; each minion's (with its ID after the colon);
# and the times of recent one-minion asks, for the cap.
_FLEET_KEY = "inventory-ask"
_ONE_KEY = "inventory-ask:"
_ONE_BY_ONE_KEY = "inventory-ask-one-by-one"


class Throttled(Exception):
    """Read now came too soon. The message says so; `retry_after` is in whole seconds."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = max(1, math.ceil(retry_after))


@dataclass
class Asked:
    """What Read now did."""

    asked: list[str]  # the minions asked, or for the whole fleet, made due for the sweep
    queued: bool  # the whole fleet was made due: the sweep asks them, BATCH at a time
    failed: dict[str, str] = field(default_factory=dict)  # source -> why it wasn't asked
    reason: str | None = None  # why no minion was asked


async def ask(runtime: Runtime, source: str, mids: list[str], now: datetime) -> SaltApiError | None:
    """Ask these minions for one source, in one job. `now` is brine's clock, read before
    sending. Returns why it couldn't (salt-api refused or failed), or None."""
    if not mids:
        return None
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
        return exc
    except SaltApiError as exc:
        log.warning("couldn't ask %d minion(s) for %s: %s", len(mids), source, exc)
        return exc
    await runtime.ingest.set_state_entry(REFUSED_STATE, source, None)
    # The answer can only be matched to this ask once it's recorded. One that beats it counts
    # as someone else's (no credit, the want stays), and the next ask settles it.
    await runtime.ingest.inventory_asked(mids, source, at=now, jid=jid)
    return None


def _state(read: InventoryRead | None) -> ReadState | None:
    if read is None:
        return None
    return ReadState(
        asked_jid=read.asked_jid,
        asked_at=read.asked_at,
        answered_at=read.answered_at,
        wanted_at=read.wanted_at,
    )


def _asked_at(read: InventoryRead | None) -> datetime:
    return read.asked_at if read is not None and read.asked_at is not None else _NEVER


async def sweep(runtime: Runtime, now: datetime | None = None) -> None:
    """Ask the connected minions for each source they're due, BATCH at a time per source."""
    now = now or datetime.now(UTC)
    every = timedelta(hours=runtime.settings.inventory.refresh_hours)
    async with runtime.sessions() as s:
        mids = await connected_minions(s, runtime.settings, now)
        if not mids:
            return
        reads = {
            (read.minion_id, read.source): read
            for read in await s.scalars(
                select(InventoryRead)
                .join(Minion, Minion.id == InventoryRead.minion_id)
                .where(*CONNECTED)
            )
        }
        # When each last came online: one back since its last answer is read again.
        back = {
            mid: at
            for mid, at in await s.execute(
                select(PresenceChange.minion_id, func.max(PresenceChange.at))
                .join(Minion, Minion.id == PresenceChange.minion_id)
                .where(PresenceChange.connected.is_(True), *CONNECTED)
                .group_by(PresenceChange.minion_id)
            )
        }
    for source in sources(runtime.settings):
        # Whoever was asked longest ago goes first (never asked, before anyone), so a fleet of
        # more than BATCH can't keep the same minions waiting. The job's target is by ID.
        due = sorted(
            (_asked_at(reads.get((mid, source))), mid)
            for mid in mids
            if is_due(_state(reads.get((mid, source))), now=now, every=every, back_at=back.get(mid))
        )
        await ask(runtime, source, sorted(mid for _, mid in due[:BATCH]), now)


async def _online(
    runtime: Runtime, now: datetime, only: str | None
) -> tuple[list[str], str | None]:
    """The online minions (or just `only`), or why there are none."""
    async with runtime.sessions() as s:
        _, checked_at = await read_presence(s)
        if not is_fresh(checked_at, now, runtime.settings):
            return [], STALE
        mids = await connected_minions(s, runtime.settings, now, only)
    if mids:
        return mids, None
    return [], NOBODY if only is None else f"{only} isn't online"


def _take_throttle(runtime: Runtime, minion: str | None) -> str:
    """Hold Read now's throttle for the fleet or `minion`; Throttled if it's held, or if too
    many minions were asked one by one in the last minute. Returns its memo key."""
    clock = time.monotonic()
    if minion is None:
        key, every, when = _FLEET_KEY, ASK_ALL_EVERY, "in a minute"
    else:
        key, every, when = _ONE_KEY + minion, ASK_ONE_EVERY, "in a few seconds"
    last = runtime.memo.get(key)
    if last is not None and clock - last[0] < every:
        raise Throttled(f"Already reading; try again {when}.", every - (clock - last[0]))
    if minion is not None:
        _, times = runtime.memo.get(_ONE_BY_ONE_KEY, (clock, []))
        recent = [t for t in times if clock - t < _MINUTE]
        if len(recent) >= ONE_BY_ONE_PER_MINUTE:
            raise Throttled(
                f"{len(recent)} minions were asked one by one in the last minute; try again "
                "in a minute, or ask for the whole fleet.",
                _MINUTE - (clock - recent[0]),
            )
        runtime.memo[_ONE_BY_ONE_KEY] = (clock, [*recent, clock])
    runtime.memo[key] = (clock, None)
    return key


async def ask_now(runtime: Runtime, minion: str | None, now: datetime) -> Asked:
    """Read now: every source, from the online minions (or `minion`, if it's online), due or
    not. The whole fleet is made due, for the sweep to ask; one minion is asked straight away.

    Throttled when asked too soon. Raises salt-api's error when no source could be asked.
    Nothing asked or made due leaves the throttle free. An attempt for one minion still counts
    towards ONE_BY_ONE_PER_MINUTE even then, on purpose: it may have reached salt-api, and a
    script trying minion after minion mustn't get round the cap by failing."""
    key = _take_throttle(runtime, minion)
    try:
        mids, reason = await _online(runtime, now, minion)
        if not mids:
            runtime.memo.pop(key, None)
            return Asked([], queued=False, reason=reason)
        if minion is None:
            await runtime.ingest.inventory_want_now(mids, at=now)
            return Asked(mids, queued=True)
        errors: dict[str, SaltApiError] = {}
        for source in sources(runtime.settings):
            if (error := await ask(runtime, source, mids, now)) is not None:
                errors[source] = error
    except Exception:
        runtime.memo.pop(key, None)
        raise
    if len(errors) == len(sources(runtime.settings)):  # nothing went out
        runtime.memo.pop(key, None)
        raise next(iter(errors.values()))
    return Asked(mids, queued=False, failed={s: str(e) for s, e in errors.items()})


async def run_forever(runtime: Runtime) -> None:
    while True:
        try:
            await sweep(runtime)
        except Exception:  # a bad sweep mustn't stop the next one
            log.exception("inventory sweep failed")
        await asyncio.sleep(SWEEP_SECONDS)
