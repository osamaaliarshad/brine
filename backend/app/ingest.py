"""Record what Salt tells us in the database.

Every method is idempotent: the same event delivered twice (or a backfilled job that was also
seen live) leaves the database unchanged. Each returns a `Changes` describing what moved, so
the caller can notify browsers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.inventory import AFTER_JOB
from app.models import (
    AuditEntry,
    GrainsSnapshot,
    InventoryChange,
    InventoryItem,
    InventoryRead,
    Job,
    JobReturn,
    Minion,
    PendingRun,
    PresenceChange,
    SystemState,
)

# `wheel key.list_all` field -> brine key state
KEY_LIST_FIELDS = {
    "minions": "accepted",
    "minions_pre": "pending",
    "minions_rejected": "rejected",
    "minions_denied": "denied",
}
# `act` in salt/auth and salt/key events -> key state
KEY_ACTS = {"pend": "pending", "accept": "accepted", "reject": "rejected", "delete": "deleted"}

PRESENCE_STATE = "presence"
# Accepted minions the master's presence detection can't see (no cached IP addresses).
PRESENCE_BLIND_STATE = "presence_blind"


def has_routable_ip(grains: Any) -> bool:
    """Presence matches TCP peers against cached ipv4/ipv6 grains; loopback never matches."""
    if not isinstance(grains, dict):
        return False
    addresses = [*(grains.get("ipv4") or []), *(grains.get("ipv6") or [])]
    return any(isinstance(a, str) and not a.startswith("127.") and a != "::1" for a in addresses)


@dataclass
class Changes:
    fleet: bool = False
    minions: set[str] = field(default_factory=set)
    jobs: set[str] = field(default_factory=set)
    status: bool = False

    def __bool__(self) -> bool:
        return self.fleet or self.status or bool(self.minions) or bool(self.jobs)

    def merge(self, other: Changes) -> Changes:
        self.fleet |= other.fleet
        self.status |= other.status
        self.minions |= other.minions
        self.jobs |= other.jobs
        return self


def grains_hash(grains: dict[str, Any]) -> str:
    canonical = json.dumps(grains, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _later(current: datetime | None, candidate: datetime) -> datetime:
    return candidate if current is None or candidate > current else current


def _meet_want(read: InventoryRead) -> None:
    """An answer meets a want (a start, a job) only if brine asked at or after it."""
    if read.wanted_at is not None and read.asked_at is not None and read.asked_at >= read.wanted_at:
        read.wanted_at = None


class Ingest:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        service_user: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._service_user = service_user
        self._clock = clock
        # One writer at a time keeps SQLite happy and makes read-modify-write safe.
        self._lock = asyncio.Lock()

    def is_housekeeping(self, user: str | None, fun: str) -> bool:
        """Jobs brine doesn't record: its own calls (grains refreshes, polls, backfill lookups)
        and the pings the master runs for `manage.status`. Their effects (fresh grains, proof a
        minion is alive) are still applied."""
        return user == self._service_user or (user == "salt" and fun == "test.ping")

    async def _get_or_create(self, s: AsyncSession, mid: str, key_state: str) -> Minion:
        minion = await s.get(Minion, mid)
        if minion is None:
            minion = Minion(id=mid, key_state=key_state, first_seen_at=self._clock())
            s.add(minion)
        return minion

    # --- keys -----------------------------------------------------------------------------

    async def keys(self, key_lists: dict[str, list[str]]) -> Changes:
        """Apply a full `key.list_all` result; keys that disappeared become "deleted"."""
        wanted = {
            mid: state for name, state in KEY_LIST_FIELDS.items() for mid in key_lists.get(name, [])
        }
        changes = Changes()
        async with self._lock, self._sessions() as s, s.begin():
            existing = {m.id: m for m in (await s.scalars(select(Minion))).all()}
            for mid, state in wanted.items():
                minion = existing.get(mid)
                if minion is None:
                    await self._get_or_create(s, mid, state)
                    changes.minions.add(mid)
                elif minion.key_state != state:
                    minion.key_state = state
                    changes.minions.add(mid)
            for mid, minion in existing.items():
                if mid not in wanted and minion.key_state != "deleted":
                    minion.key_state = "deleted"
                    minion.connected = False
                    changes.minions.add(mid)
        changes.fleet = bool(changes.minions)
        return changes

    async def key_event(self, mid: str, act: str) -> Changes:
        state = KEY_ACTS.get(act)
        if state is None or not mid:
            return Changes()
        async with self._lock, self._sessions() as s, s.begin():
            existing = await s.get(Minion, mid)
            if existing is not None and existing.key_state == state:
                # Pending minions re-send their key every few seconds; nothing to do.
                return Changes()
            minion = existing or await self._get_or_create(s, mid, state)
            minion.key_state = state
            if state != "accepted":
                minion.connected = False
        return Changes(fleet=True, minions={mid})

    async def fingerprints(self, finger: dict[str, Any]) -> Changes:
        """Apply `wheel key.finger` output: {"minions": {id: fp}, "minions_pre": {...}, ...}."""
        flat = {
            mid: str(fp)
            for name in KEY_LIST_FIELDS
            for mid, fp in (finger.get(name) or {}).items()
            if fp
        }
        changes = Changes()
        if not flat:
            return changes
        async with self._lock, self._sessions() as s, s.begin():
            for minion in (await s.scalars(select(Minion).where(Minion.id.in_(flat)))).all():
                if minion.key_fingerprint != flat[minion.id]:
                    minion.key_fingerprint = flat[minion.id]
                    changes.minions.add(minion.id)
        return changes

    # --- presence -------------------------------------------------------------------------

    async def presence(self, present: Iterable[str], *, at: datetime, method: str) -> Changes:
        """A full observation: exactly these accepted minions are connected right now."""
        present_ids = set(present)
        changes = Changes(status=True)
        async with self._lock, self._sessions() as s, s.begin():
            minions = {m.id: m for m in (await s.scalars(select(Minion))).all()}
            for mid in present_ids - minions.keys():
                minions[mid] = await self._get_or_create(s, mid, "accepted")
            for mid, minion in minions.items():
                connected = mid in present_ids
                if connected:
                    minion.last_seen_at = _later(minion.last_seen_at, at)
                elif minion.key_state != "accepted":
                    continue
                if minion.connected != connected:
                    minion.connected = connected
                    s.add(PresenceChange(minion_id=mid, at=at, connected=connected))
                    changes.minions.add(mid)
            await self._set_state(s, PRESENCE_STATE, {"at": at.isoformat(), "method": method})
        # Presence refreshes "last seen" for everyone online, so the fleet view always changes.
        changes.fleet = True
        return changes

    async def presence_change(
        self, *, new: Iterable[str], lost: Iterable[str], at: datetime
    ) -> Changes:
        """A `salt/presence/change` event: only the minions that came or went."""
        changes = Changes()
        async with self._lock, self._sessions() as s, s.begin():
            for mid, connected in [(m, True) for m in new] + [(m, False) for m in lost]:
                minion = await self._get_or_create(s, mid, "accepted")
                if connected:
                    minion.last_seen_at = _later(minion.last_seen_at, at)
                if minion.connected != connected:
                    minion.connected = connected
                    s.add(PresenceChange(minion_id=mid, at=at, connected=connected))
                    changes.minions.add(mid)
        changes.fleet = bool(changes.minions)
        return changes

    async def minion_seen(self, mid: str, *, at: datetime) -> Changes:
        async with self._lock, self._sessions() as s, s.begin():
            minion = await self._get_or_create(s, mid, "accepted")
            minion.last_seen_at = _later(minion.last_seen_at, at)
        return Changes(fleet=True, minions={mid})

    # --- grains ---------------------------------------------------------------------------

    async def grains(
        self, mid: str, grains: dict[str, Any], *, at: datetime | None, source: str
    ) -> Changes:
        """Store grains. `source="minion"` means collected live at `at`; `"master_cache"` means
        the master's cached copy, used only when brine has nothing better (age unknown)."""
        async with self._lock, self._sessions() as s, s.begin():
            minion = await self._get_or_create(s, mid, "accepted")
            if source == "master_cache":
                if minion.grains is not None:
                    return Changes()
                minion.grains, minion.grains_at, minion.grains_source = grains, None, source
                return Changes(fleet=True, minions={mid})

            assert at is not None, "live grains need a collection time"
            if minion.grains_at is not None and at < minion.grains_at:
                return Changes()  # an older collection arriving late
            digest = grains_hash(grains)
            latest = await s.scalar(
                select(GrainsSnapshot.sha256)
                .where(GrainsSnapshot.minion_id == mid)
                .order_by(GrainsSnapshot.collected_at.desc())
                .limit(1)
            )
            if latest != digest:
                s.add(GrainsSnapshot(minion_id=mid, collected_at=at, sha256=digest, grains=grains))
            minion.grains, minion.grains_at, minion.grains_source = grains, at, source
            minion.last_seen_at = _later(minion.last_seen_at, at)
        return Changes(fleet=True, minions={mid})

    # --- packages and checks (app/inventory.py) -------------------------------------------

    async def _read_row(self, s: AsyncSession, mid: str, source: str) -> InventoryRead:
        await self._get_or_create(s, mid, "accepted")
        read = await s.get(InventoryRead, (mid, source))
        if read is None:
            read = InventoryRead(minion_id=mid, source=source)
            s.add(read)
        return read

    async def inventory_asked(self, mids: Iterable[str], source: str, *, at: datetime) -> None:
        async with self._lock, self._sessions() as s, s.begin():
            for mid in mids:
                (await self._read_row(s, mid, source)).asked_at = at

    async def inventory_wanted(self, mid: str, *, at: datetime) -> None:
        """The minion started: read each source again from `at` on. A minion never read has no
        rows, and is due anyway."""
        async with self._lock, self._sessions() as s, s.begin():
            for read in await s.scalars(select(InventoryRead).filter_by(minion_id=mid)):
                read.wanted_at = _later(read.wanted_at, at)

    async def inventory_job_done(
        self, mid: str, *, jid: str, user: str | None, at: datetime
    ) -> None:
        """A person's job that may change software finished on `mid` at `at`: read it again
        shortly, and credit what that read finds to the job. The latest job wins."""
        async with self._lock, self._sessions() as s, s.begin():
            for read in await s.scalars(select(InventoryRead).filter_by(minion_id=mid)):
                read.wanted_at = _later(read.wanted_at, at + AFTER_JOB)
                if read.after_at is None or at >= read.after_at:
                    read.after_jid, read.after_user, read.after_at = jid, user, at

    async def inventory_read(
        self,
        mid: str,
        source: str,
        entries: dict[str, str],
        *,
        at: datetime,
        truncated: bool = False,
    ) -> Changes:
        """A good answer: these are all the entries `mid` has for `source`, as of `at`. Each
        difference from the last read is a change; the first read records what's there without
        any ("already there when brine first looked")."""
        async with self._lock, self._sessions() as s, s.begin():
            read = await self._read_row(s, mid, source)
            if read.read_at is not None and at <= read.read_at:
                return Changes()  # an older answer arriving late, or a duplicate
            first, since = read.first_read_at is None, read.read_at
            # Changes go to the job only if brine asked after it: an answer to an older ask may
            # show a change made before the job. Otherwise the credit waits for the next answer.
            credited = (
                read.after_at is not None
                and read.asked_at is not None
                and read.asked_at >= read.after_at
                and at >= read.after_at
            )
            jid, user = (read.after_jid, read.after_user) if credited else (None, None)
            current = {
                item.name: item
                for item in await s.scalars(
                    select(InventoryItem).filter_by(minion_id=mid, source=source)
                )
            }
            moved: list[tuple[str, str | None, str | None]] = []
            for name, value in entries.items():
                item = current.pop(name, None)
                if item is None:
                    s.add(
                        InventoryItem(
                            minion_id=mid, source=source, name=name, value=value, since=at
                        )
                    )
                    moved.append((name, None, value))
                elif item.value != value:
                    moved.append((name, item.value, value))
                    item.value, item.since = value, at
            for name, item in current.items():
                moved.append((name, item.value, None))
                await s.delete(item)
            if not first:
                s.add_all(
                    InventoryChange(
                        minion_id=mid,
                        source=source,
                        name=name,
                        old=old,
                        new=new,
                        at=at,
                        since=since,
                        jid=jid,
                        user=user,
                    )
                    for name, old, new in moved
                )
            if credited:
                read.after_jid = read.after_user = read.after_at = None
            read.read_at, read.truncated = at, truncated
            read.first_read_at = read.first_read_at or at
            # A failed answer from after this one (it arrived first) stays the latest answer.
            if read.answered_at is None or at >= read.answered_at:
                read.answered_at, read.error = at, None
            _meet_want(read)
        return Changes(fleet=bool(moved), minions={mid})

    async def inventory_failed(self, mid: str, source: str, error: str, *, at: datetime) -> Changes:
        """The minion answered but couldn't say (a locked package database, a failing check).
        The last good entries stay, as of when they were read."""
        async with self._lock, self._sessions() as s, s.begin():
            read = await self._read_row(s, mid, source)
            if read.answered_at is not None and at <= read.answered_at:
                return Changes()  # an older answer arriving late, or a duplicate
            read.answered_at, read.error = at, error
            _meet_want(read)
        return Changes(minions={mid})

    # --- jobs -----------------------------------------------------------------------------

    async def job_new(
        self,
        *,
        jid: str,
        kind: str,
        fun: str,
        at: datetime,
        args: list[Any] | None = None,
        target: str | None = None,
        target_type: str | None = None,
        user: str | None = None,
        minions: list[str] | None = None,
        from_job_cache: bool = False,
    ) -> Changes:
        """`from_job_cache`: `at` comes from the master's job cache (worked out from the jid,
        in the master's local time), so it never moves a job brine has already recorded."""
        if self.is_housekeeping(user, fun):
            return Changes()
        async with self._lock, self._sessions() as s, s.begin():
            job = await s.get(Job, jid)
            job_is_new = job is None
            if job is None:
                job = Job(jid=jid, kind=kind, fun=fun, started_at=at)
                s.add(job)
            job.fun = fun
            # A live `new` event can come after a return that already created the job: its
            # (earlier, real) start time wins. A job-cache time never moves a recorded job.
            if job_is_new or not from_job_cache:
                job.started_at = min(job.started_at, at)
            job.args = args or []
            job.target, job.target_type = target, target_type
            # Who a job belongs to, once known, sticks: an orchestration step's events say
            # "salt", but brine has already recorded the person who ran the orchestration.
            job.user = job.user or user
            job.minions = minions or []
        return Changes(jobs={jid})

    async def command_started(
        self,
        *,
        jid: str,
        fun: str,
        args: list[Any],
        target: str,
        target_type: str,
        actor: str,
        minions: list[str],
        at: datetime,
    ) -> Changes:
        """A job brine started for someone. Salt reports brine's service account as its user,
        so this records the person instead; returns find them through the job's metadata."""
        async with self._lock, self._sessions() as s, s.begin():
            job = await s.get(Job, jid)
            if job is None:
                job = Job(jid=jid, kind="local", fun=fun, started_at=at)
                s.add(job)
            job.fun, job.started_at = fun, min(job.started_at, at)
            job.args, job.target, job.target_type = args, target, target_type
            job.user, job.minions = actor, minions
        return Changes(jobs={jid})

    async def master_command(
        self,
        *,
        jid: str,
        fun: str,
        args: list[Any],
        actor: str,
        at: datetime,
        data: Any,
        success: bool | None,
    ) -> Changes:
        """A runner someone ran through brine, with its answer: recorded as a runner job under
        them (Salt's own events name brine's service account, so they're skipped)."""
        async with self._lock, self._sessions() as s, s.begin():
            job = await s.get(Job, jid)
            if job is None:
                job = Job(jid=jid, kind="runner", fun=fun, started_at=at)
                s.add(job)
            job.args, job.user = args, actor
            ret = await s.get(JobReturn, (jid, "master"))
            if ret is None:
                ret = JobReturn(jid=jid, minion_id="master", returned_at=at, data=data)
                s.add(ret)
            ret.returned_at, ret.data, ret.success, ret.retcode = at, data, success, None
        return Changes(jobs={jid})

    # --- catch-up runs (app/catchup.py) ------------------------------------------------------

    async def catch_up_queue(
        self,
        *,
        source_jid: str,
        fun: str,
        args: list[Any],
        actor: str,
        minions: Iterable[str],
        at: datetime,
        expires_at: datetime,
    ) -> Changes:
        """Keep a command for minions that missed it. A minion already waiting on the same
        command gets only this one: the older is marked replaced."""
        changes = Changes(jobs={source_jid})
        async with self._lock, self._sessions() as s, s.begin():
            for mid in minions:
                older = await s.scalars(
                    select(PendingRun).where(
                        PendingRun.state == "waiting",
                        PendingRun.minion_id == mid,
                        PendingRun.fun == fun,
                    )
                )
                for run in older:
                    if run.args == args:
                        run.state, run.reason = "replaced", f"replaced by job {source_jid}"
                        changes.jobs.add(run.source_jid)
                s.add(
                    PendingRun(
                        minion_id=mid,
                        source_jid=source_jid,
                        fun=fun,
                        args=args,
                        actor=actor,
                        created_at=at,
                        expires_at=expires_at,
                        state="waiting",
                    )
                )
                changes.minions.add(mid)
        return changes

    async def catch_up_claim(self, run_id: int) -> bool:
        """Take a waiting run for sending (waiting -> sending). False if it isn't waiting any
        more (cancelled or replaced meanwhile), so it's never sent."""
        async with self._lock, self._sessions() as s, s.begin():
            run = await s.get(PendingRun, run_id)
            if run is None or run.state != "waiting":
                return False
            run.state = "sending"
            return True

    async def catch_up_sent(self, run_id: int, *, jid: str, at: datetime) -> Changes:
        async with self._lock, self._sessions() as s, s.begin():
            run = await s.get(PendingRun, run_id)
            if run is None or run.state != "sending":
                return Changes()
            run.state, run.sent_jid, run.sent_at = "sent", jid, at
            return Changes(jobs={run.source_jid, jid}, minions={run.minion_id})

    async def catch_up_unsent(self, run_id: int, *, state: str, reason: str | None) -> Changes:
        """Sending didn't work out: back to waiting (it certainly didn't go out), failed (it
        may have), or refused (Salt doesn't know the minion any more)."""
        async with self._lock, self._sessions() as s, s.begin():
            run = await s.get(PendingRun, run_id)
            if run is None or run.state != "sending":
                return Changes()
            run.state, run.reason = state, reason
            return Changes(jobs={run.source_jid}, minions={run.minion_id})

    async def catch_up_close(self, run_id: int, *, state: str, reason: str) -> Changes:
        """End a waiting run without sending it: cancelled or refused."""
        async with self._lock, self._sessions() as s, s.begin():
            run = await s.get(PendingRun, run_id)
            if run is None or run.state != "waiting":
                return Changes()
            run.state, run.reason = state, reason
            return Changes(jobs={run.source_jid}, minions={run.minion_id})

    async def catch_up_expire(self, now: datetime) -> Changes:
        changes = Changes()
        async with self._lock, self._sessions() as s, s.begin():
            stale = await s.scalars(
                select(PendingRun).where(
                    PendingRun.state == "waiting", PendingRun.expires_at <= now
                )
            )
            for run in stale:
                run.state, run.reason = "expired", "the minion didn't come back in time"
                changes.jobs.add(run.source_jid)
                changes.minions.add(run.minion_id)
        return changes

    async def prune(
        self,
        *,
        jobs_before: datetime | None,
        history_before: datetime | None,
        audit_before: datetime | None,
    ) -> dict[str, int]:
        """Delete history older than each cutoff (None keeps it). Returns rows deleted per kind.
        A job's returns go with it; catch-up runs still waiting are never deleted."""
        deleted: dict[str, int] = {}

        async def drop(s: AsyncSession, name: str, statement: Any) -> None:
            result = await s.execute(statement)
            deleted[name] = int(getattr(result, "rowcount", 0) or 0)

        async with self._lock, self._sessions() as s, s.begin():
            if jobs_before is not None:
                await drop(s, "jobs", delete(Job).where(Job.started_at < jobs_before))
                await drop(
                    s,
                    "catch_up_runs",
                    delete(PendingRun).where(
                        PendingRun.state != "waiting", PendingRun.created_at < jobs_before
                    ),
                )
            if history_before is not None:
                await drop(
                    s,
                    "presence_changes",
                    delete(PresenceChange).where(PresenceChange.at < history_before),
                )
                await drop(
                    s,
                    "grains_snapshots",
                    delete(GrainsSnapshot).where(GrainsSnapshot.collected_at < history_before),
                )
                # Only the history: current packages and check entries are never pruned.
                await drop(
                    s,
                    "inventory_changes",
                    delete(InventoryChange).where(InventoryChange.at < history_before),
                )
            if audit_before is not None:
                await drop(s, "audit", delete(AuditEntry).where(AuditEntry.at < audit_before))
        return deleted

    async def job_owner(self, jids: Iterable[str], actor: str) -> Changes:
        """These jobs belong to `actor` (an orchestration's steps, started as "salt")."""
        wanted = set(jids)
        async with self._lock, self._sessions() as s, s.begin():
            for job in (await s.scalars(select(Job).where(Job.jid.in_(wanted)))).all():
                job.user = actor
        return Changes(jobs=wanted)

    async def job_return(
        self,
        *,
        jid: str,
        kind: str,
        minion_id: str,
        fun: str,
        at: datetime,
        data: Any,
        success: bool | None,
        retcode: int | None,
        user: str | None = None,
    ) -> Changes:
        record = not self.is_housekeeping(user, fun)
        changes = Changes(jobs={jid} if record else set())
        async with self._lock, self._sessions() as s, s.begin():
            if record:
                job = await s.get(Job, jid)
                if job is None:
                    # The return beat (or replaced) the job's `new` event.
                    s.add(Job(jid=jid, kind=kind, fun=fun, started_at=at, user=user))
                ret = await s.get(JobReturn, (jid, minion_id))
                if ret is None:
                    ret = JobReturn(jid=jid, minion_id=minion_id, returned_at=at, data=data)
                    s.add(ret)
                ret.returned_at, ret.data, ret.success, ret.retcode = at, data, success, retcode
            if kind == "local":
                minion = await self._get_or_create(s, minion_id, "accepted")
                minion.last_seen_at = _later(minion.last_seen_at, at)
                changes.minions.add(minion_id)
                changes.fleet = True
        if (
            kind == "local"
            and fun == "grains.items"
            and success is not False
            and isinstance(data, dict)
        ):
            changes.merge(await self.grains(minion_id, data, at=at, source="minion"))
        return changes

    async def known_jids(self, jids: Iterable[str]) -> set[str]:
        wanted = list(jids)
        async with self._sessions() as s:
            rows = await s.scalars(select(Job.jid).where(Job.jid.in_(wanted)))
            return set(rows.all())

    # --- system state ---------------------------------------------------------------------

    async def _set_state(self, s: AsyncSession, key: str, value: Any) -> None:
        row = await s.get(SystemState, key)
        if row is None:
            s.add(SystemState(key=key, value=value, updated_at=self._clock()))
        else:
            row.value, row.updated_at = value, self._clock()

    async def presence_blind(self, cached_grains: dict[str, Any]) -> Changes:
        """From `runner cache.grains`: remember accepted minions presence can't see."""
        async with self._lock, self._sessions() as s, s.begin():
            accepted = (
                await s.scalars(select(Minion.id).where(Minion.key_state == "accepted"))
            ).all()
            blind = sorted(m for m in accepted if not has_routable_ip(cached_grains.get(m)))
            row = await s.get(SystemState, PRESENCE_BLIND_STATE)
            if row is not None and row.value == blind:
                return Changes()
            await self._set_state(s, PRESENCE_BLIND_STATE, blind)
        return Changes(fleet=True, status=True)

    async def presence_visible(self, mid: str) -> Changes:
        """A (re)started minion refreshes the master's cache, so presence can see it again."""
        async with self._lock, self._sessions() as s, s.begin():
            row = await s.get(SystemState, PRESENCE_BLIND_STATE)
            if row is None or mid not in (row.value or []):
                return Changes()
            await self._set_state(s, PRESENCE_BLIND_STATE, [m for m in row.value if m != mid])
        return Changes(fleet=True, status=True)

    async def get_state(self, key: str) -> Any:
        async with self._sessions() as s:
            row = await s.get(SystemState, key)
            return None if row is None else row.value
