"""Keeps brine's database in step with the Salt master.

One connected "session" looks like this:

1. Open salt-api's event stream (events arriving from here on are queued, not lost).
2. Sync a snapshot: key states, an initial presence observation, grains, and jobs the
   master ran while brine wasn't listening.
3. Process events forever, while side loops poll presence (if the master doesn't send
   presence events) and periodically refresh grains.

If anything breaks (salt-api restarts, the master goes away, the network drops) the session
ends and a new one starts after a backoff. Because every write is idempotent, re-syncing after a
reconnect is always safe.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app import inventory
from app.bus import EventBus
from app.commands import actor_of
from app.config import Settings
from app.eventlog import EventLog
from app.ingest import Changes, Ingest
from app.salt.client import SaltApiAuthError, SaltApiError
from app.salt.events import SaltEvent, parse_job_start_time

log = logging.getLogger(__name__)

_JOB_RET = re.compile(r"^salt/job/(?P<jid>[^/]+)/ret/(?P<mid>.+)$")
_JOB_NEW = re.compile(r"^salt/job/(?P<jid>[^/]+)/new$")
_RUN_NEW = re.compile(r"^salt/run/(?P<jid>[^/]+)/new$")
_RUN_RET = re.compile(r"^salt/run/(?P<jid>[^/]+)/ret$")
_MINION_START = re.compile(r"^salt/minion/(?P<mid>[^/]+)/start$")


class SaltApi(Protocol):
    """What the collector needs from a salt-api client (lets tests use a fake)."""

    @property
    def username(self) -> str: ...
    def events(self) -> AsyncIterator[SaltEvent]: ...
    async def runner(self, fun: str, **kwargs: Any) -> Any: ...
    async def wheel(self, fun: str, **kwargs: Any) -> Any: ...
    async def local_async(
        self, tgt: str, fun: str, *, arg: list[Any] | None = None, tgt_type: str = "glob"
    ) -> str | None: ...


@dataclass
class CollectorStatus:
    connected: bool = False
    since: datetime | None = None  # when the current state (connected or not) began
    last_event_at: datetime | None = None
    error: str | None = None
    presence_method: str | None = None  # what's actually providing presence right now


class _StreamEnded(Exception):
    pass


# A stream that closes cleanly after at least this long (a proxy's idle timeout, brine's own
# silence limit) is picked straight back up: no "disconnected", no backoff.
QUIET_RECONNECT_AFTER = timedelta(seconds=30)


class Backoff:
    def __init__(self, base: float = 1.0, cap: float = 30.0) -> None:
        self.base, self.cap, self.attempt = base, cap, 0

    def next(self) -> float:
        delay = min(self.cap, self.base * float(2**self.attempt))
        self.attempt += 1
        return delay * random.uniform(0.8, 1.2)  # noqa: S311 (jitter, not crypto)

    def reset(self) -> None:
        self.attempt = 0


class Collector:
    def __init__(
        self,
        client: SaltApi,
        ingest: Ingest,
        settings: Settings,
        bus: EventBus,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        backoff_sleep: Callable[[float], Any] = asyncio.sleep,
        event_log: EventLog | None = None,
    ) -> None:
        self.client = client
        self.ingest = ingest
        self.settings = settings
        self.bus = bus
        self.clock = clock
        # Only the reconnect wait is injectable (tests skip it); the poll loops use real time.
        self.backoff_sleep = backoff_sleep
        self.event_log = event_log or EventLog()
        self.status = CollectorStatus(since=clock())
        self._presence_event_at: datetime | None = None
        # When brine last asked every minion for fresh grains (survives reconnects).
        self._grains_asked_at: datetime | None = None

    # --- lifecycle ------------------------------------------------------------------------

    async def run(self) -> None:
        """Run sessions forever, reconnecting with backoff. Cancel the task to stop."""
        backoff = Backoff()
        while True:
            started = self.clock()
            try:
                await self.run_session()
                backoff.reset()
                if self.clock() - started >= QUIET_RECONNECT_AFTER:
                    log.info("salt-api event stream closed; reconnecting")
                    continue
                reason = "event stream closed"
            except asyncio.CancelledError:
                raise
            except SaltApiAuthError as exc:
                reason = str(exc)
                log.error("salt-api login failed: %s", exc)
            except SaltApiError as exc:
                reason = str(exc)
                log.warning("lost salt-api: %s", exc)
            except Exception as exc:
                reason = f"internal error: {exc}"
                log.exception("collector session crashed")
            self._set_connected(False, error=reason)
            delay = backoff.next()
            log.info("reconnecting to salt-api in %.1fs", delay)
            await self.backoff_sleep(delay)

    async def run_session(self) -> None:
        queue: asyncio.Queue[SaltEvent | BaseException | None] = asyncio.Queue()
        pump = asyncio.create_task(self._pump(queue), name="salt-events")
        helpers: list[asyncio.Task[None]] = []
        try:
            await self.sync()
            self._set_connected(True)
            helpers = [
                asyncio.create_task(self._presence_loop(), name="presence-poll"),
                asyncio.create_task(self._grains_loop(), name="grains-refresh"),
            ]
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                await self.handle(item)
        finally:
            for task in [pump, *helpers]:
                task.cancel()
            await asyncio.gather(pump, *helpers, return_exceptions=True)

    async def _pump(self, queue: asyncio.Queue[SaltEvent | BaseException | None]) -> None:
        try:
            async for event in self.client.events():
                await queue.put(event)
            await queue.put(None)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            await queue.put(exc)

    def _set_connected(self, connected: bool, *, error: str | None = None) -> None:
        if connected != self.status.connected or error != self.status.error:
            self.status.connected = connected
            self.status.since = self.clock()
            self.status.error = error
            if not connected:
                self.status.presence_method = None
            self.bus.publish({"type": "status"})

    def _publish(self, changes: Changes) -> None:
        if changes:
            self.bus.publish_changes(changes)

    # --- snapshot sync --------------------------------------------------------------------

    async def sync(self) -> None:
        """Catch up on everything that may have happened while brine wasn't listening."""
        keys = await self.client.wheel("key.list_all")
        self._publish(await self.ingest.keys(keys or {}))
        await self._sync_fingerprints("*")
        await self._observe_presence(initial=True)
        await self._sync_grains()
        await self._backfill_jobs()

    async def _sync_fingerprints(self, match: str) -> None:
        finger = await self.client.wheel("key.finger", match=match)
        if isinstance(finger, dict):
            self._publish(await self.ingest.fingerprints(finger))

    def _grains_due(self) -> timedelta:
        """How long until the fleet's grains are due a refresh (zero or less: now)."""
        if self._grains_asked_at is None:
            return timedelta(0)
        every = timedelta(minutes=self.settings.fleet.grains_refresh_minutes)
        return self._grains_asked_at + every - self.clock()

    async def _ask_for_grains(self) -> None:
        # Fresh grains from connected minions arrive as job returns on the event stream.
        await self.client.local_async("*", "grains.items")
        self._grains_asked_at = self.clock()

    async def _sync_grains(self) -> None:
        # Asking every minion on every reconnect would hammer the fleet when a proxy closes
        # the event stream often; the schedule carries over instead.
        if self._grains_due() <= timedelta(0):
            await self._ask_for_grains()
        # Minions brine has never seen get the master's cached grains (age unknown) for now.
        cached = await self.client.runner("cache.grains", tgt="*")
        changes = Changes()
        for mid, grains in (cached or {}).items():
            if isinstance(grains, dict) and grains:
                changes.merge(await self.ingest.grains(mid, grains, at=None, source="master_cache"))
        changes.merge(await self.ingest.presence_blind(cached if isinstance(cached, dict) else {}))
        self._publish(changes)

    async def _backfill_jobs(self) -> None:
        limit = self.settings.jobs.backfill_limit
        if limit == 0:
            return
        listed = await self.client.runner("jobs.list_jobs")
        if not isinstance(listed, dict):
            return
        candidates = [
            (jid, info)
            for jid, info in listed.items()
            if isinstance(info, dict)
            and _is_minion_job(str(info.get("Function", "")))
            and not self.ingest.is_housekeeping(_job_user(info), str(info.get("Function", "")))
        ]
        newest = sorted(candidates, key=lambda c: c[0], reverse=True)[:limit]
        known = await self.ingest.known_jids(jid for jid, _ in newest)
        missing = [(jid, info) for jid, info in newest if jid not in known]
        for jid, info in missing:
            await self._backfill_job(jid, info)
        if missing:
            log.info("backfilled %d job(s) from the master's job cache", len(missing))

    async def _backfill_job(self, jid: str, info: dict[str, Any]) -> None:
        await self.import_job(jid, user=_job_user(info))

    async def import_job(self, jid: str, *, user: str | None = None) -> None:
        self._publish(await import_job(self.client, self.ingest, jid, user=user, now=self.clock()))

    # --- presence -------------------------------------------------------------------------

    def _events_active(self) -> bool:
        """Has the master been sending presence events recently?"""
        if self._presence_event_at is None:
            return False
        window = timedelta(seconds=2 * self.settings.presence.poll_seconds)
        return self.clock() - self._presence_event_at <= window

    async def _observe_presence(self, *, initial: bool = False) -> None:
        method = self.settings.presence.method
        if method == "events" or (method == "auto" and self._events_active()):
            return
        now = self.clock()
        if method == "ping":
            result = await self.client.runner("manage.status")
            present = (result or {}).get("up", []) if isinstance(result, dict) else []
            used = "ping"
        else:  # auto without events, or "connected"
            present = await self.client.wheel("minions.connected") or []
            used = "connected"
        self.status.presence_method = used
        self._publish(await self.ingest.presence(present, at=now, method=used))

    async def _presence_loop(self) -> None:
        if self.settings.presence.method == "events":
            return
        while True:
            await asyncio.sleep(self.settings.presence.poll_seconds)
            try:
                await self._observe_presence()
            except SaltApiError as exc:
                log.warning("presence poll failed: %s", exc)

    async def _grains_loop(self) -> None:
        while True:
            await asyncio.sleep(max(self._grains_due().total_seconds(), 1.0))
            try:
                await self._ask_for_grains()
                cached = await self.client.runner("cache.grains", tgt="*")
                if isinstance(cached, dict):
                    self._publish(await self.ingest.presence_blind(cached))
            except SaltApiError as exc:
                log.warning("grains refresh failed: %s", exc)

    # --- events ---------------------------------------------------------------------------

    async def handle(self, event: SaltEvent) -> None:
        now = self.clock()
        self.status.last_event_at = now
        self.event_log.append(event)
        at = event.stamp or now
        tag, d = event.tag, event.data
        changes = Changes()

        if tag == "salt/presence/present":
            # Presence uses brine's own clock: "fresh" must mean fresh to brine, even if the
            # master's clock is off.
            self._presence_event_at = now
            self.status.presence_method = "events"
            changes = await self.ingest.presence(d.get("present") or [], at=now, method="events")
        elif tag == "salt/presence/change":
            changes = await self.ingest.presence_change(
                new=d.get("new") or [], lost=d.get("lost") or [], at=now
            )
        elif (m := _JOB_RET.match(tag) or _JOB_NEW.match(tag)) and not _is_minion_job(
            str(d.get("fun", ""))
        ):
            pass  # wheel/runner calls echoed as salt/job events: master-side, not minion jobs
        elif m := _JOB_RET.match(tag):
            mid, fun = str(d.get("id") or m["mid"]), str(d.get("fun", ""))
            # Someone's command run through brine: theirs, not brine's housekeeping.
            user = actor_of(d.get("metadata")) or d.get("user")
            changes = await self.ingest.job_return(
                jid=m["jid"],
                kind="local",
                minion_id=mid,
                fun=fun,
                at=at,
                data=d.get("return"),
                success=d.get("success"),
                retcode=d.get("retcode"),
                user=user,
            )
            changes.merge(await self._inventory_return(mid, m["jid"], fun, user, d, at))
        elif m := _JOB_NEW.match(tag):
            changes = await self.ingest.job_new(
                jid=m["jid"],
                kind="local",
                fun=str(d.get("fun", "")),
                at=at,
                args=d.get("arg") or [],
                target=_as_text(d.get("tgt")),
                target_type=d.get("tgt_type"),
                user=d.get("user"),
                minions=d.get("minions") or [],
            )
        elif m := _RUN_NEW.match(tag):
            changes = await self.ingest.job_new(
                jid=m["jid"],
                kind="runner",
                fun=str(d.get("fun", "")).removeprefix("runner."),
                at=at,
                args=d.get("fun_args") or [],
                user=d.get("user"),
            )
        elif m := _RUN_RET.match(tag):
            changes = await self.ingest.job_return(
                jid=m["jid"],
                kind="runner",
                minion_id="master",
                fun=str(d.get("fun", "")).removeprefix("runner."),
                at=at,
                data=d.get("return"),
                success=d.get("success"),
                retcode=None,
                user=d.get("user"),
            )
        elif tag in ("salt/auth", "salt/key"):
            mid = str(d.get("id", ""))
            changes = await self.ingest.key_event(mid, str(d.get("act", "")))
            if changes and d.get("act") != "delete":
                # A new or re-keyed minion: fetch its fingerprint too.
                await self._sync_fingerprints(mid)
        elif m := _MINION_START.match(tag):
            changes = await self.ingest.minion_seen(m["mid"], at=now)
            changes.merge(await self.ingest.presence_visible(m["mid"]))
            # A (re)started minion may have new grains, packages and checks. The want is timed
            # by the master, like the answers it's compared with, and recorded first, so a
            # salt-api error asking for grains doesn't lose it.
            try:
                await self.ingest.inventory_wanted(m["mid"], at=at)
            except Exception:  # derived data, read again anyway: not worth ending the session
                log.exception("couldn't record that %s wants a read", m["mid"])
            await self.client.local_async(m["mid"], "grains.items", tgt_type="list")

        self._publish(changes)

    async def _inventory_return(
        self, mid: str, jid: str, fun: str, user: str | None, d: dict[str, Any], at: datetime
    ) -> Changes:
        """Packages and checks from a job's return: an answer, or a job to read again after."""
        try:
            # An answer is a read-only call: it never wants a re-read or a credit.
            args = d.get("fun_args")
            if source := self._inventory_source(fun, args):
                return await self._inventory_answer(mid, jid, source, d, at)
            if not self.ingest.is_housekeeping(user, fun) and inventory.may_change_software(
                fun, args
            ):
                await self.ingest.inventory_job_done(mid, jid=jid, user=user, at=at)
        except Exception:  # derived data, read again anyway: not worth ending the session
            log.exception("couldn't record packages or checks from job %s on %s", jid, mid)
        return Changes()

    def _inventory_source(self, fun: str, args: object) -> str | None:
        """What a return answers, if anything: the packages, for ``pkg.list_pkgs`` with no
        arguments (``versions_as_list`` or ``attr`` change its shape), or a check, for
        ``cmd.run_all`` with exactly its command (``runas``, ``env`` or ``cwd`` can change the
        output: such a run is a job like any other)."""
        if fun == inventory.PACKAGES_FUN:
            return None if args else inventory.PACKAGES
        if fun == inventory.CHECK_FUN and isinstance(args, list) and len(args) == 1:
            return inventory.check_named(self.settings, args)
        return None

    async def _inventory_answer(
        self, mid: str, jid: str, source: str, d: dict[str, Any], at: datetime
    ) -> Changes:
        """A package list or a configured check's output, from brine or anyone else."""
        parse = inventory.parse_packages if source == inventory.PACKAGES else inventory.parse_check
        entries, error, truncated = parse(d.get("return"))
        # A call Salt says failed is a failed read. Its answer is usually Salt's error text (an
        # "unexpected answer"), but one that reads well may still be partial: a command inside
        # it failed, say.
        if d.get("success") is False and not error:
            retcode = d.get("retcode")
            error = "Salt said the call failed"
            if retcode is not None:
                error += f" (retcode {retcode})"
        if error:
            return await self.ingest.inventory_failed(mid, source, error, at=at, jid=jid)
        return await self.ingest.inventory_read(
            mid, source, entries, at=at, truncated=truncated, jid=jid
        )


async def import_job(
    client: SaltApi | Any, ingest: Ingest, jid: str, *, user: str | None, now: datetime
) -> Changes:
    """Record a minion job from the master's job cache (`jobs.list_job`), under `user` if given
    (an orchestration step someone ran through brine) or Salt's own user otherwise."""
    detail = await client.runner("jobs.list_job", jid=jid)
    info = detail if isinstance(detail, dict) else {}
    started = parse_job_start_time(info.get("StartTime")) or now
    fun = str(info.get("Function", ""))
    user = user or _job_user(info)
    changes = await ingest.job_new(
        jid=jid,
        kind="local",
        fun=fun,
        at=started,
        args=info.get("Arguments") or [],
        target=_as_text(info.get("Target")),
        target_type=info.get("Target-type"),
        user=user,
        minions=info.get("Minions") or [],
        from_job_cache=True,
    )
    for mid, result in (info.get("Result") or {}).items():
        result = result if isinstance(result, dict) else {"return": result}
        changes.merge(
            await ingest.job_return(
                jid=jid,
                kind="local",
                minion_id=mid,
                fun=fun,
                # The job cache doesn't keep per-minion return times; use the start time.
                at=started,
                data=result.get("return"),
                success=result.get("success"),
                retcode=result.get("retcode"),
                user=user,
            )
        )
    return changes


def _job_user(info: dict[str, Any]) -> Any:
    """A job-cache entry's user: the person, for commands brine ran on their behalf."""
    return actor_of(info.get("Metadata")) or info.get("User")


def _is_minion_job(fun: str) -> bool:
    """The job cache and salt/job/* also carry master-side wheel/runner calls."""
    return not fun.startswith(("wheel.", "runner."))


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return ",".join(map(str, value)) if isinstance(value, list) else str(value)
