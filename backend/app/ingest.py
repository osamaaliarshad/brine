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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import GrainsSnapshot, Job, JobReturn, Minion, PresenceChange, SystemState

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
    ) -> Changes:
        if self.is_housekeeping(user, fun):
            return Changes()
        async with self._lock, self._sessions() as s, s.begin():
            job = await s.get(Job, jid)
            if job is None:
                job = Job(jid=jid, kind=kind, fun=fun, started_at=at)
                s.add(job)
            job.fun = fun
            job.started_at = min(job.started_at, at)
            job.args = args or []
            job.target, job.target_type, job.user = target, target_type, user
            job.minions = minions or []
        return Changes(jobs={jid})

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

    async def get_state(self, key: str) -> Any:
        async with self._sessions() as s:
            row = await s.get(SystemState, key)
            return None if row is None else row.value
