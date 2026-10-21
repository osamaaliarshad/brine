from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ingest import PRESENCE_STATE, Changes, Ingest
from app.inventory import AFTER_JOB, ANSWER_WAIT, CREDIT_WINDOW, NO_JOB, ReadState, is_due
from app.models import (
    GrainsSnapshot,
    InventoryChange,
    InventoryItem,
    InventoryRead,
    Job,
    JobReturn,
    Minion,
    PresenceChange,
)
from tests.conftest import T0

Sessions = async_sessionmaker[AsyncSession]


async def minion(sessions: Sessions, mid: str) -> Minion:
    async with sessions() as s:
        m = await s.get(Minion, mid)
        assert m is not None
        return m


async def count(sessions: Sessions, model: type, **where: object) -> int:
    async with sessions() as s:
        q = select(func.count()).select_from(model).filter_by(**where)
        return int(await s.scalar(q) or 0)


# --- keys -----------------------------------------------------------------------------------


async def test_keys_sync_sets_states_and_marks_missing_deleted(
    ingest: Ingest, sessions: Sessions
) -> None:
    changes = await ingest.keys({"minions": ["a", "b"], "minions_pre": ["c"]})
    assert changes.minions == {"a", "b", "c"} and changes.fleet
    assert (await minion(sessions, "c")).key_state == "pending"

    changes = await ingest.keys({"minions": ["a", "c"]})
    assert changes.minions == {"b", "c"}
    assert (await minion(sessions, "b")).key_state == "deleted"
    assert (await minion(sessions, "c")).key_state == "accepted"

    assert not await ingest.keys({"minions": ["a", "c"]})  # nothing changed


async def test_key_events(ingest: Ingest, sessions: Sessions) -> None:
    assert await ingest.key_event("new", "pend")
    assert (await minion(sessions, "new")).key_state == "pending"
    assert not await ingest.key_event("new", "pend")  # a pending minion retrying
    await ingest.key_event("new", "accept")
    assert (await minion(sessions, "new")).key_state == "accepted"
    assert not await ingest.key_event("new", "something-else")


# --- presence -------------------------------------------------------------------------------


async def test_presence_records_transitions_once(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.keys({"minions": ["a", "b"]})

    await ingest.presence(["a", "b"], at=T0, method="events")
    await ingest.presence(["a", "b"], at=T0 + timedelta(seconds=15), method="events")
    changes = await ingest.presence(["a"], at=T0 + timedelta(seconds=30), method="events")

    assert changes.minions == {"b"}
    a, b = await minion(sessions, "a"), await minion(sessions, "b")
    assert a.connected and a.last_seen_at == T0 + timedelta(seconds=30)
    assert not b.connected and b.last_seen_at == T0 + timedelta(seconds=15)
    assert await count(sessions, PresenceChange, minion_id="a") == 1
    assert await count(sessions, PresenceChange, minion_id="b") == 2
    state = await ingest.get_state(PRESENCE_STATE)
    assert state == {"at": (T0 + timedelta(seconds=30)).isoformat(), "method": "events"}


async def test_presence_creates_unknown_minions(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.presence(["surprise"], at=T0, method="connected")
    m = await minion(sessions, "surprise")
    assert m.connected and m.key_state == "accepted"


async def test_presence_ignores_absent_non_accepted_keys(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.keys({"minions_pre": ["pending-one"]})
    changes = await ingest.presence([], at=T0, method="events")
    assert "pending-one" not in changes.minions
    assert await count(sessions, PresenceChange) == 0


async def test_presence_change_event(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.presence(["a", "b"], at=T0, method="events")
    changes = await ingest.presence_change(new=[], lost=["b"], at=T0 + timedelta(seconds=5))
    assert changes.minions == {"b"}
    assert not (await minion(sessions, "b")).connected
    # The same news again is a no-op.
    assert not (await ingest.presence_change(new=[], lost=["b"], at=T0)).minions


# --- grains ---------------------------------------------------------------------------------


async def test_grains_history_only_grows_on_change(ingest: Ingest, sessions: Sessions) -> None:
    v1 = {"os": "Debian", "app_version": "1.0"}
    await ingest.grains("a", v1, at=T0, source="minion")
    await ingest.grains("a", dict(v1), at=T0 + timedelta(minutes=30), source="minion")
    assert await count(sessions, GrainsSnapshot, minion_id="a") == 1
    # "as of" moves forward even when nothing changed.
    assert (await minion(sessions, "a")).grains_at == T0 + timedelta(minutes=30)

    await ingest.grains(
        "a", {**v1, "app_version": "1.1"}, at=T0 + timedelta(hours=1), source="minion"
    )
    assert await count(sessions, GrainsSnapshot, minion_id="a") == 2
    assert (await minion(sessions, "a")).grains == {**v1, "app_version": "1.1"}


async def test_late_older_grains_are_ignored(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.grains("a", {"v": 2}, at=T0 + timedelta(minutes=5), source="minion")
    assert not await ingest.grains("a", {"v": 1}, at=T0, source="minion")
    assert (await minion(sessions, "a")).grains == {"v": 2}


async def test_master_cache_grains_only_fill_gaps(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.grains("cached", {"v": "cache"}, at=None, source="master_cache")
    m = await minion(sessions, "cached")
    assert m.grains == {"v": "cache"} and m.grains_at is None and m.grains_source == "master_cache"
    assert m.last_seen_at is None  # the cache proves nothing about being alive

    await ingest.grains("live", {"v": "live"}, at=T0, source="minion")
    assert not await ingest.grains("live", {"v": "cache"}, at=None, source="master_cache")
    assert (await minion(sessions, "live")).grains == {"v": "live"}
    assert await count(sessions, GrainsSnapshot, minion_id="cached") == 0


# --- jobs -----------------------------------------------------------------------------------


async def test_job_lifecycle(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.job_new(
        jid="j1",
        kind="local",
        fun="test.ping",
        at=T0,
        target="*",
        target_type="glob",
        user="alice",
        minions=["a", "b"],
    )
    for _ in range(2):  # duplicate delivery is harmless
        await ingest.job_return(
            jid="j1",
            kind="local",
            minion_id="a",
            fun="test.ping",
            at=T0 + timedelta(seconds=1),
            data=True,
            success=True,
            retcode=0,
        )
    async with sessions() as s:
        job = await s.get(Job, "j1")
        assert job is not None and job.minions == ["a", "b"]
    assert await count(sessions, JobReturn, jid="j1") == 1
    assert (await minion(sessions, "a")).last_seen_at == T0 + timedelta(seconds=1)


async def test_return_before_new_still_records_job(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.job_return(
        jid="j2",
        kind="local",
        minion_id="a",
        fun="cmd.run",
        at=T0 + timedelta(seconds=2),
        data="ok",
        success=True,
        retcode=0,
    )
    await ingest.job_new(jid="j2", kind="local", fun="cmd.run", at=T0, user="alice")
    async with sessions() as s:
        job = await s.get(Job, "j2")
        assert job is not None and job.started_at == T0


async def test_housekeeping_jobs_are_not_recorded(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.job_new(jid="mine", kind="local", fun="grains.items", at=T0, user="brine")
    await ingest.job_new(jid="poll", kind="local", fun="test.ping", at=T0, user="salt")
    await ingest.job_new(jid="real", kind="local", fun="state.apply", at=T0, user="salt")
    async with sessions() as s:
        assert set((await s.scalars(select(Job.jid))).all()) == {"real"}


async def test_grains_items_returns_update_grains(ingest: Ingest, sessions: Sessions) -> None:
    changes = await ingest.job_return(
        jid="g1",
        kind="local",
        minion_id="a",
        fun="grains.items",
        at=T0,
        data={"os": "Debian"},
        success=True,
        retcode=0,
        user="brine",
    )
    assert "a" in changes.minions and not changes.jobs
    m = await minion(sessions, "a")
    assert m.grains == {"os": "Debian"} and m.grains_at == T0 and m.grains_source == "minion"
    assert m.last_seen_at == T0
    # brine's own refresh updates grains but isn't kept as a job.
    assert await count(sessions, Job) == 0 and await count(sessions, JobReturn) == 0


async def test_runner_returns_do_not_touch_minions(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.job_return(
        jid="r1",
        kind="runner",
        minion_id="master",
        fun="manage.status",
        at=T0,
        data={"up": []},
        success=True,
        retcode=None,
    )
    assert await count(sessions, Minion) == 0
    assert await count(sessions, JobReturn, minion_id="master") == 1


async def test_fingerprints(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.keys({"minions": ["a"], "minions_pre": ["b"]})
    finger = {
        "minions": {"a": "aa:aa"},
        "minions_pre": {"b": "bb:bb"},
        "local": {"master.pem": "x"},
    }
    assert (await ingest.fingerprints(finger)).minions == {"a", "b"}
    assert (await minion(sessions, "b")).key_fingerprint == "bb:bb"
    assert not await ingest.fingerprints(finger)  # unchanged
    assert not await ingest.fingerprints({})


def test_has_routable_ip() -> None:
    from app.ingest import has_routable_ip

    assert has_routable_ip({"ipv4": ["127.0.0.1", "172.18.0.5"]})
    assert has_routable_ip({"ipv6": ["::1", "fd00::5"]})
    assert not has_routable_ip({"ipv4": ["127.0.0.1"], "ipv6": ["::1"]})
    assert not has_routable_ip({"ipv4": []})
    assert not has_routable_ip(None)


async def test_presence_blind_tracks_minions_without_cached_ips(ingest: Ingest) -> None:
    from app.ingest import PRESENCE_BLIND_STATE

    await ingest.keys({"minions": ["seen", "blind", "missing"], "minions_pre": ["pending"]})
    cached = {"seen": {"ipv4": ["10.0.0.1"]}, "blind": {"ipv4": ["127.0.0.1"]}}
    assert await ingest.presence_blind(cached)
    assert await ingest.get_state(PRESENCE_BLIND_STATE) == ["blind", "missing"]
    assert not await ingest.presence_blind(cached)  # unchanged

    assert await ingest.presence_visible("blind")
    assert await ingest.get_state(PRESENCE_BLIND_STATE) == ["missing"]
    assert not await ingest.presence_visible("seen")


async def test_job_cache_times_never_move_a_recorded_job(
    ingest: Ingest, sessions: Sessions
) -> None:
    # The job cache's StartTime comes from the jid, in the master's local time: on a master
    # five hours behind UTC it reads five hours early. A job seen live keeps its own time.
    await ingest.job_new(jid="j3", kind="local", fun="cmd.run", at=T0, user="alice")
    await ingest.job_new(
        jid="j3", kind="local", fun="cmd.run", at=T0 - timedelta(hours=5), from_job_cache=True
    )
    async with sessions() as s:
        job = await s.get(Job, "j3")
        assert job is not None and job.started_at == T0


# --- packages and checks --------------------------------------------------------------------

SECOND = timedelta(seconds=1)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
EVERY = timedelta(hours=6)


async def items(sessions: Sessions, mid: str, source: str = "packages") -> dict[str, str]:
    async with sessions() as s:
        rows = await s.scalars(select(InventoryItem).filter_by(minion_id=mid, source=source))
        return {r.name: r.value for r in rows}


async def changes_of(sessions: Sessions, mid: str) -> list[InventoryChange]:
    async with sessions() as s:
        q = select(InventoryChange).filter_by(minion_id=mid).order_by(InventoryChange.id)
        return list((await s.scalars(q)).all())


async def last_change(sessions: Sessions, mid: str = "a") -> InventoryChange:
    return (await changes_of(sessions, mid))[-1]


async def read_row(sessions: Sessions, mid: str, source: str = "packages") -> InventoryRead:
    async with sessions() as s:
        read = await s.get(InventoryRead, (mid, source))
        assert read is not None
        return read


async def due(sessions: Sessions, *, now: datetime, mid: str = "a") -> bool:
    """Whether the sweep would ask `mid` for its packages at `now`."""
    read = await read_row(sessions, mid)
    state = ReadState(
        asked_jid=read.asked_jid,
        asked_at=read.asked_at,
        answered_at=read.answered_at,
        wanted_at=read.wanted_at,
    )
    return is_due(state, now=now, every=EVERY, back_at=None)


async def brine_reads(
    ingest: Ingest,
    entries: dict[str, str],
    *,
    at: datetime,
    jid: str,
    mid: str = "a",
    source: str = "packages",
) -> Changes:
    """brine asks `mid` at `at`, in job `jid`; the good answer comes ten seconds later."""
    await ingest.inventory_asked([mid], source, at=at, jid=jid)
    return await ingest.inventory_read(mid, source, entries, at=at + 10 * SECOND, jid=jid)


# Reads and changes.


async def test_first_read_records_without_changes(ingest: Ingest, sessions: Sessions) -> None:
    changes = await ingest.inventory_read(
        "a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0, jid=None
    )
    assert changes.minions == {"a"} and changes.fleet
    assert await items(sessions, "a") == {"bash": "5.2", "agent": "2.3.0"}
    assert await changes_of(sessions, "a") == []  # "already there when brine first looked"
    read = await read_row(sessions, "a")
    assert read.read_at == read.answered_at == read.first_read_at == T0
    assert (await minion(sessions, "a")).key_state == "accepted"


async def test_later_reads_record_each_change(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0, jid=None)
    later = T0 + 6 * HOUR
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1", "curl": "8"}, at=later, jid=None
    )
    got = {(c.name, c.old, c.new) for c in await changes_of(sessions, "a")}
    assert got == {("agent", "2.3.0", "2.4.1"), ("curl", None, "8"), ("bash", "5.2", None)}
    assert all(c.since == T0 and c.at == later for c in await changes_of(sessions, "a"))
    assert all(c.jid is None and c.user is None for c in await changes_of(sessions, "a"))
    async with sessions() as s:
        agent = await s.get(InventoryItem, ("a", "packages", "agent"))
        assert agent is not None and agent.since == later
    read = await read_row(sessions, "a")
    assert read.read_at == later and read.first_read_at == T0


async def test_the_return_says_what_moved(ingest: Ingest) -> None:
    # A source's first read moves the fleet view even with nothing in it: no more "?".
    first = await ingest.inventory_read("a", "rover", {}, at=T0, jid=None)
    assert first.minions == {"a"} and first.fleet
    again = await ingest.inventory_read("a", "rover", {}, at=T0 + HOUR, jid=None)
    assert again.minions == {"a"} and not again.fleet  # the page refreshes ("as of" moved)
    moved = await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0 + 2 * HOUR, jid=None)
    assert moved.minions == {"a"} and moved.fleet
    failed = await ingest.inventory_failed("a", "rover", "exit 1", at=T0 + 3 * HOUR, jid=None)
    assert failed.minions == {"a"} and not failed.fleet


async def test_a_truncated_answer_removes_nothing(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0, jid=None)
    # Cut short: what's missing may only have been cut off, so it isn't gone.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=T0 + HOUR, jid=None, truncated=True
    )
    assert await items(sessions, "a") == {"bash": "5.2", "agent": "2.4.1"}
    assert [(c.name, c.new) for c in await changes_of(sessions, "a")] == [("agent", "2.4.1")]
    assert (await read_row(sessions, "a")).truncated
    # A whole answer without it: gone.
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + 2 * HOUR, jid=None)
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    last = await last_change(sessions)
    assert (last.name, last.old, last.new) == ("bash", "5.2", None)
    assert not (await read_row(sessions, "a")).truncated


async def test_a_single_value_check(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "rover", {"": "rover 1.0"}, at=T0, jid=None)
    assert await items(sessions, "a", "rover") == {"": "rover 1.0"}
    await ingest.inventory_read("a", "rover", {"": "rover 1.1"}, at=T0 + HOUR, jid=None)
    (change,) = await changes_of(sessions, "a")
    assert (change.source, change.name, change.old, change.new) == (
        "rover",
        "",
        "rover 1.0",
        "rover 1.1",
    )
    # No output: the thing isn't there any more.
    await ingest.inventory_read("a", "rover", {}, at=T0 + 2 * HOUR, jid=None)
    assert await items(sessions, "a", "rover") == {}
    assert (await last_change(sessions)).new is None


async def test_sources_are_independent(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_read("a", "services", {"agent": "running"}, at=T0, jid=None)
    await ingest.inventory_read("a", "packages", {"curl": "8"}, at=T0 + HOUR, jid=None)
    assert await items(sessions, "a", "services") == {"agent": "running"}
    assert await items(sessions, "a") == {"curl": "8"}
    assert {c.source for c in await changes_of(sessions, "a")} == {"packages"}
    await ingest.inventory_failed("a", "services", "exit 1", at=T0 + 2 * HOUR, jid=None)
    assert (await read_row(sessions, "a")).error is None
    assert (await read_row(sessions, "a", "services")).error == "exit 1"


async def test_late_answers_are_ignored(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + HOUR, jid=None)
    assert not await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    # The same answer delivered twice changes nothing either.
    assert not await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=T0 + HOUR, jid=None
    )
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    assert await changes_of(sessions, "a") == []

    assert not await ingest.inventory_failed("a", "packages", "locked", at=T0, jid=None)
    read = await read_row(sessions, "a")
    assert read.error is None and read.answered_at == T0 + HOUR


async def test_a_failed_read_keeps_the_last_good_one(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    failed_at = T0 + 6 * HOUR
    await ingest.inventory_failed("a", "packages", "dpkg database locked", at=failed_at, jid=None)
    assert await items(sessions, "a") == {"agent": "2.3.0"}
    read = await read_row(sessions, "a")
    assert read.error == "dpkg database locked" and read.read_at == T0
    assert read.answered_at == failed_at

    later = T0 + 12 * HOUR
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=later, jid=None)
    read = await read_row(sessions, "a")
    assert read.error is None and read.read_at == read.answered_at == later
    (change,) = await changes_of(sessions, "a")
    assert change.since == T0  # between the last two good reads


async def test_a_late_good_answer_after_a_failure(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_failed("a", "packages", "locked", at=T0 + 2 * HOUR, jid=None)
    # Newer than the last good read, so its entries are kept; the failure is still the latest.
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + HOUR, jid=None)
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    read = await read_row(sessions, "a")
    assert read.read_at == T0 + HOUR
    assert read.answered_at == T0 + 2 * HOUR and read.error == "locked"


async def test_failing_before_any_good_read(ingest: Ingest, sessions: Sessions) -> None:
    changes = await ingest.inventory_failed("a", "packages", "locked", at=T0, jid=None)
    assert changes.minions == {"a"}
    read = await read_row(sessions, "a")
    assert read.error == "locked" and read.read_at is None and read.first_read_at is None
    # The first good read after it is still the first: no changes.
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 + HOUR, jid=None)
    assert await changes_of(sessions, "a") == []


async def test_asks_are_recorded_for_each_minion(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    # "a" has been read before; "b" and "c" are new to brine.
    await ingest.inventory_asked(["a", "b", "c"], "packages", at=T0 + HOUR, jid="A1")
    for mid in ("a", "b", "c"):
        read = await read_row(sessions, mid)
        assert (read.asked_at, read.asked_jid) == (T0 + HOUR, "A1")
        assert (await minion(sessions, mid)).key_state == "accepted"
    assert (await read_row(sessions, "a")).read_at == T0
    assert (await read_row(sessions, "b")).read_at is None
    await ingest.inventory_asked([], "packages", at=T0 + 3 * HOUR, jid="A2")
    assert await count(sessions, InventoryRead) == 3


async def test_an_ask_that_matched_no_minion(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 - EVERY, jid=None)
    # salt-api started no job: kept as NO_JOB, so brine waits as for any ask instead of asking
    # again on every sweep.
    await ingest.inventory_asked(["a"], "packages", at=T0, jid=None)
    read = await read_row(sessions, "a")
    assert read.asked_at == T0 and read.asked_jid == NO_JOB
    assert not await due(sessions, now=T0 + 15 * SECOND)
    assert await due(sessions, now=T0 + ANSWER_WAIT)
    # No answer is brine's answer to it.
    await ingest.inventory_wanted("a", at=T0 + MINUTE)
    await ingest.inventory_asked(["a"], "packages", at=T0 + 2 * MINUTE, jid=None)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 + 3 * MINUTE, jid=None)
    assert (await read_row(sessions, "a")).wanted_at == T0 + MINUTE


# Credit: brine's answer after a person's job.


async def test_changes_after_a_job_are_credited_to_it(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice@example.com", at=job_at)
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + MINUTE, jid="A1")
    (change,) = await changes_of(sessions, "a")
    assert (change.jid, change.user) == ("J1", "alice@example.com")
    read = await read_row(sessions, "a")
    assert read.after_jid is None and read.after_user is None and read.after_at is None
    assert read.wanted_at is None and read.asked_jid is None
    # The credit is used up: the next change isn't the job's.
    await brine_reads(ingest, {"agent": "2.5.0"}, at=job_at + 2 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_a_credited_read_with_no_change_uses_the_credit_up(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await brine_reads(ingest, {"agent": "2.3.0"}, at=job_at + MINUTE, jid="A1")
    assert await changes_of(sessions, "a") == []
    assert (await read_row(sessions, "a")).after_at is None
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_the_credit_window(ingest: Ingest, sessions: Sessions) -> None:
    job_at = T0 + HOUR
    for mid in ("a", "b"):
        await ingest.inventory_read(mid, "packages", {"agent": "2.3.0"}, at=T0, jid=None)
        await ingest.inventory_job_done(mid, jid="J1", user="alice", at=job_at)
    # Asked within the window (a slow sweep, or one lost answer): credited.
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + CREDIT_WINDOW, jid="A1", mid="a")
    assert (await last_change(sessions, "a")).jid == "J1"
    # Asked later (the minion was away): too much else may have changed. No credit, and it's
    # used up all the same.
    late = job_at + CREDIT_WINDOW + MINUTE
    await brine_reads(ingest, {"agent": "2.4.1"}, at=late, jid="A2", mid="b")
    assert (await last_change(sessions, "b")).jid is None
    read = await read_row(sessions, "b")
    assert read.after_at is None and read.wanted_at is None


async def test_an_ask_sent_just_before_the_job_isnt_credited(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0", "curl": "7"}, at=T0, jid=None)
    # The sweep sends A1, then the job's return is processed, then A1 is recorded: it looks
    # like an ask after the job, but it was timed (before sending) ahead of it.
    sent = T0 + 6 * HOUR
    job_at = sent + SECOND
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=sent, jid="A1")
    # A1 ran before the job's change; curl was changed by hand hours ago.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0", "curl": "8"}, at=sent + 2 * SECOND, jid="A1"
    )
    last = await last_change(sessions)
    assert (last.name, last.jid, last.user) == ("curl", None, None)
    # A1's answer settles only A1: the job still wants a read, and its credit waits for it.
    read = await read_row(sessions, "a")
    assert (read.asked_jid, read.after_jid, read.wanted_at) == (None, "J1", job_at + AFTER_JOB)
    assert await due(sessions, now=job_at + AFTER_JOB)
    await brine_reads(ingest, {"agent": "2.4.1", "curl": "8"}, at=job_at + AFTER_JOB, jid="A2")
    last = await last_change(sessions)
    assert (last.name, last.jid, last.user) == ("agent", "J1", "alice")
    read = await read_row(sessions, "a")
    assert read.after_at is None and read.wanted_at is None


async def test_a_failed_or_late_answer_to_an_ask_sent_before_the_job(
    ingest: Ingest, sessions: Sessions
) -> None:
    sent = T0 + 6 * HOUR
    job_at = sent + SECOND
    for mid in ("a", "b"):
        await ingest.inventory_read(mid, "packages", {"agent": "2.3.0"}, at=T0, jid=None)
        await ingest.inventory_job_done(mid, jid="J1", user="alice", at=job_at)
        await ingest.inventory_asked([mid], "packages", at=sent, jid="A1")
    # "a": A1 fails. "b": someone else's read gets in first, so A1's answer is late.
    await ingest.inventory_failed("a", "packages", "locked", at=sent + 2 * SECOND, jid="A1")
    await ingest.inventory_read("b", "packages", {"agent": "2.3.0"}, at=sent + 3 * SECOND, jid=None)
    await ingest.inventory_read("b", "packages", {"agent": "2.3.0"}, at=sent + 2 * SECOND, jid="A1")
    # Either way it settles only A1; the next ask gets the want and the credit.
    for mid in ("a", "b"):
        read = await read_row(sessions, mid)
        assert (read.asked_jid, read.after_jid, read.wanted_at) == (
            None,
            "J1",
            job_at + AFTER_JOB,
        )
        await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + AFTER_JOB, jid="A2", mid=mid)
        last = await last_change(sessions, mid)
        assert (last.jid, last.user) == ("J1", "alice")


async def test_a_failed_answer_uses_the_credit_up(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + MINUTE, jid="A1")
    await ingest.inventory_failed("a", "packages", "locked", at=job_at + 2 * MINUTE, jid="A1")
    read = await read_row(sessions, "a")
    assert read.after_at is None and read.wanted_at is None and read.asked_jid is None
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 3 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_an_ask_out_before_the_job_isnt_its_answer(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_asked(["a"], "packages", at=T0 + HOUR, jid="A1")
    job_at = T0 + HOUR + MINUTE
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    # The job forgets A1, whose answer may predate it.
    assert (await read_row(sessions, "a")).asked_jid is None
    await ingest.inventory_asked(["a"], "packages", at=job_at + MINUTE, jid="A2")
    # A1's answer arrives after A2 went out: its entries count, uncredited.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.0"}, at=job_at + 2 * MINUTE, jid="A1"
    )
    assert await items(sessions, "a") == {"agent": "2.4.0"}
    assert (await last_change(sessions)).jid is None
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.wanted_at, read.asked_jid) == ("J1", job_at + AFTER_JOB, "A2")
    # A2's answer takes the credit and meets the want.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 3 * MINUTE, jid="A2"
    )
    last = await last_change(sessions)
    assert (last.old, last.new, last.jid, last.user) == ("2.4.0", "2.4.1", "J1", "alice")
    read = await read_row(sessions, "a")
    assert read.after_at is None and read.wanted_at is None


async def test_someone_elses_answer_settles_nothing(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + MINUTE, jid="A1")
    # A person's own pkg.list_pkgs, and a job brine never asked with: their entries count, but
    # neither is brine's answer.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid=None
    )
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.2"}, at=job_at + 3 * MINUTE, jid="OTHER"
    )
    await ingest.inventory_failed("a", "packages", "locked", at=job_at + 4 * MINUTE, jid=None)
    assert await items(sessions, "a") == {"agent": "2.4.2"}
    assert {c.jid for c in await changes_of(sessions, "a")} == {None}
    read = await read_row(sessions, "a")
    assert read.read_at == job_at + 3 * MINUTE and read.answered_at == job_at + 4 * MINUTE
    assert (read.after_jid, read.wanted_at, read.asked_jid) == ("J1", job_at + AFTER_JOB, "A1")


async def test_someone_elses_read_then_a_lost_answer(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    asked = job_at + MINUTE
    await ingest.inventory_asked(["a"], "packages", at=asked, jid="A1")
    # A person reads first and finds the job's change (uncredited); then A1's answer is lost.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid=None
    )
    assert not await due(sessions, now=asked + 5 * MINUTE)  # waiting for A1's answer
    assert await due(sessions, now=asked + ANSWER_WAIT)  # then asked again for the want
    # The re-ask is within the window but finds nothing new, so nothing goes to the job.
    await brine_reads(ingest, {"agent": "2.4.1"}, at=asked + ANSWER_WAIT, jid="A2")
    assert {c.jid for c in await changes_of(sessions, "a")} == {None}
    read = await read_row(sessions, "a")
    assert read.after_at is None and read.wanted_at is None
    assert not await due(sessions, now=asked + ANSWER_WAIT + MINUTE)
    await brine_reads(ingest, {"agent": "2.5.0"}, at=asked + ANSWER_WAIT + MINUTE, jid="A3")
    assert (await last_change(sessions)).jid is None


async def test_an_answer_before_its_ask_is_recorded(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    asked = job_at + MINUTE
    # The sweep's ask A1 is answered before the sweep records it: someone else's answer, so
    # it takes no credit and meets no want.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid="A1"
    )
    await ingest.inventory_asked(["a"], "packages", at=asked, jid="A1")
    assert (await last_change(sessions)).jid is None
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.wanted_at) == ("J1", job_at + AFTER_JOB)
    # A1 looks unanswered, so the want is asked again after ANSWER_WAIT, and that answer
    # settles it.
    assert not await due(sessions, now=asked + MINUTE)
    assert await due(sessions, now=asked + ANSWER_WAIT)
    await brine_reads(ingest, {"agent": "2.4.1"}, at=asked + ANSWER_WAIT, jid="A2")
    assert {c.jid for c in await changes_of(sessions, "a")} == {None}
    read = await read_row(sessions, "a")
    assert read.after_at is None and read.wanted_at is None and read.asked_jid is None


async def test_two_jobs_before_the_read_credit_neither(ingest: Ingest, sessions: Sessions) -> None:
    job_at = T0 + HOUR
    for mid, second_user in (("a", "alice"), ("b", "bob")):
        await ingest.inventory_read(mid, "packages", {"agent": "2.3.0"}, at=T0, jid=None)
        # Say a pkg.install, then a cmd.run: either may have made the change.
        await ingest.inventory_job_done(mid, jid="J1", user="alice", at=job_at)
        await ingest.inventory_job_done(mid, jid="J2", user=second_user, at=job_at + MINUTE)
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.after_user, read.after_at) == (None, "alice", job_at + MINUTE)
    for mid in ("a", "b"):
        await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid="A1", mid=mid)
    a, b = await last_change(sessions, "a"), await last_change(sessions, "b")
    assert (a.jid, a.user) == (None, "alice")  # "after jobs by alice"
    assert (b.jid, b.user) == (None, None)


async def test_more_jobs_stay_several(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    # J0 is reported late, after J1 and J2: all three came before brine's read.
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=T0 + 2 * HOUR)
    await ingest.inventory_job_done("a", jid="J2", user="alice", at=T0 + 3 * HOUR)
    await ingest.inventory_job_done("a", jid="J0", user="alice", at=T0 + HOUR)
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.after_user, read.after_at) == (None, "alice", T0 + 3 * HOUR)
    assert read.wanted_at == T0 + 3 * HOUR + AFTER_JOB
    await ingest.inventory_job_done("a", jid="J3", user="bob", at=T0 + 4 * HOUR)
    await ingest.inventory_job_done("a", jid="J4", user="alice", at=T0 + 5 * HOUR)
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.after_user, read.after_at) == (None, None, T0 + 5 * HOUR)
    await brine_reads(ingest, {"agent": "2.4.1"}, at=T0 + 5 * HOUR + 2 * MINUTE, jid="A1")
    last = await last_change(sessions)
    assert (last.jid, last.user) == (None, None)


async def test_a_repeated_job_report_cant_credit_it_twice(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + MINUTE, jid="A1")
    # Reported again while it waits: still the one job, and brine's ask since still counts.
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.asked_jid) == ("J1", "A1")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid="A1"
    )
    assert (await last_change(sessions)).jid == "J1"
    # Reported again after its read: its changes are in.
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    read = await read_row(sessions, "a")
    assert read.after_at is None and read.wanted_at is None
    # So a later change, even within the window, isn't credited to it.
    await brine_reads(ingest, {"agent": "2.5.0"}, at=job_at + 3 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_a_repeat_after_brines_failed_answer_brings_nothing_back(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_wanted("a", at=job_at)  # say the job restarted the minion
    for source, jid in (("packages", "A1"), ("rover", "R1")):
        await ingest.inventory_asked(["a"], source, at=job_at + MINUTE, jid=jid)
        await ingest.inventory_failed("a", source, "locked", at=job_at + 2 * MINUTE, jid=jid)
    # Both reported again: an answer newer than them is in (failed, so no read since), so
    # they're skipped. The credit stays used up, and no read is wanted.
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_wanted("a", at=job_at)
    for source in ("packages", "rover"):
        read = await read_row(sessions, "a", source)
        assert read.after_at is None and read.wanted_at is None
    # So a later change, even within the window, isn't credited to the job.
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 3 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_a_job_counts_only_for_sources_read_before_it(
    ingest: Ingest, sessions: Sessions
) -> None:
    job_at = T0 + HOUR
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0, jid=None)
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 30 * SECOND, jid=None
    )
    # Reported after a newer packages read, which already shows what it changed. The rover
    # check, last read before it, still wants a read and gives the credit.
    await ingest.inventory_job_done("a", jid="J0", user="carol", at=job_at)
    packages, rover = await read_row(sessions, "a"), await read_row(sessions, "a", "rover")
    assert packages.after_at is None and packages.wanted_at is None
    assert (rover.after_jid, rover.wanted_at) == ("J0", job_at + AFTER_JOB)
    await brine_reads(ingest, {"": "1.1"}, at=job_at + 2 * MINUTE, jid="R1", source="rover")
    last = await last_change(sessions)
    assert (last.source, last.jid, last.user) == ("rover", "J0", "carol")
    # A job after the last packages read: wanted and credited as usual.
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at + 3 * MINUTE)
    await brine_reads(ingest, {"agent": "2.5.0"}, at=job_at + 5 * MINUTE, jid="A1")
    last = await last_change(sessions)
    assert (last.source, last.jid, last.user) == ("packages", "J1", "alice")


async def test_a_job_on_a_minion_never_read_does_nothing(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=T0)
    await ingest.inventory_wanted("a", at=T0)
    assert await count(sessions, InventoryRead) == 0  # never read: it's due anyway


# Wants: a start or a job wants a read, until brine's answer.


async def test_a_job_wants_a_read_shortly_after_it(ingest: Ingest, sessions: Sessions) -> None:
    await brine_reads(ingest, {"agent": "2.3.0"}, at=T0, jid="A0")
    await ingest.inventory_asked(["a"], "packages", at=T0 + 30 * MINUTE, jid="A1")
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    read = await read_row(sessions, "a")
    assert read.wanted_at == job_at + AFTER_JOB and read.asked_jid is None  # A1 forgotten
    # Answers that aren't brine's don't meet it: A1's, a person's own, someone else's failure.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=job_at + 2 * MINUTE, jid="A1"
    )
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=job_at + 3 * MINUTE, jid=None
    )
    await ingest.inventory_failed("a", "packages", "locked", at=job_at + 4 * MINUTE, jid=None)
    assert (await read_row(sessions, "a")).wanted_at == job_at + AFTER_JOB
    # brine's answer does.
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 5 * MINUTE, jid="A2")
    assert (await read_row(sessions, "a")).wanted_at is None
    last = await last_change(sessions)
    assert (last.jid, last.user) == ("J1", "alice")


async def test_brines_failed_answer_meets_a_want(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_wanted("a", at=T0 + HOUR)
    await ingest.inventory_asked(["a"], "packages", at=T0 + HOUR + MINUTE, jid="A1")
    await ingest.inventory_failed("a", "packages", "locked", at=T0 + HOUR + 2 * MINUTE, jid="OTHER")
    assert (await read_row(sessions, "a")).wanted_at == T0 + HOUR
    await ingest.inventory_failed("a", "packages", "locked", at=T0 + HOUR + 3 * MINUTE, jid="A1")
    assert (await read_row(sessions, "a")).wanted_at is None


async def test_a_start_wants_every_source_read_again(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0, jid=None)
    await ingest.inventory_read("b", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_asked(["a", "b"], "packages", at=T0 + 30 * MINUTE, jid="A1")
    started = T0 + HOUR
    await ingest.inventory_wanted("a", at=started)
    packages = await read_row(sessions, "a")
    assert (packages.wanted_at, packages.asked_jid) == (started, None)  # A1 forgotten
    assert (await read_row(sessions, "a", "rover")).wanted_at == started
    b = await read_row(sessions, "b")
    assert (b.wanted_at, b.asked_jid) == (None, "A1")
    assert await count(sessions, InventoryRead) == 3


async def test_a_start_reported_late_keeps_the_later_want(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_wanted("a", at=T0 + 2 * HOUR)
    await ingest.inventory_wanted("a", at=T0 + HOUR)  # an earlier start, second
    assert (await read_row(sessions, "a")).wanted_at == T0 + 2 * HOUR


async def test_a_repeated_start_doesnt_want_another_read(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0, jid=None)
    started = T0 + HOUR
    await ingest.inventory_wanted("a", at=started)
    await ingest.inventory_asked(["a"], "rover", at=started + MINUTE, jid="R1")
    # Reported again while wanted: brine's ask since still counts.
    await ingest.inventory_wanted("a", at=started)
    assert (await read_row(sessions, "a", "rover")).asked_jid == "R1"
    await brine_reads(ingest, {"agent": "2.3.0"}, at=started + MINUTE, jid="A1")
    assert (await read_row(sessions, "a")).wanted_at is None
    # Reported again after the packages read: that read stands. The rover check, not read
    # since, still wants one.
    await ingest.inventory_wanted("a", at=started)
    assert (await read_row(sessions, "a")).wanted_at is None
    assert (await read_row(sessions, "a", "rover")).wanted_at == started


# Late and repeated answers.


async def test_a_late_answer_to_brines_ask_still_settles_it(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + MINUTE, jid="A1")
    # A person's read gets in first and finds what the job changed (uncredited).
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 3 * MINUTE, jid=None
    )
    # A1's answer, older than that read, changes no entries but settles brine's ask.
    assert not await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.0"}, at=job_at + 2 * MINUTE, jid="A1"
    )
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    read = await read_row(sessions, "a")
    assert read.read_at == read.answered_at == job_at + 3 * MINUTE
    assert read.after_at is None and read.wanted_at is None and read.asked_jid is None
    # So a later change, even within the window, isn't the job's.
    await brine_reads(ingest, {"agent": "2.5.0"}, at=job_at + 4 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_a_late_failure_to_brines_ask_still_settles_it(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    job_at = T0 + HOUR
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + MINUTE, jid="A1")
    # Someone else's failure gets in first; then brine's, older.
    await ingest.inventory_failed("a", "packages", "locked", at=job_at + 3 * MINUTE, jid=None)
    await ingest.inventory_failed("a", "packages", "busy", at=job_at + 2 * MINUTE, jid="A1")
    read = await read_row(sessions, "a")
    assert read.error == "locked" and read.answered_at == job_at + 3 * MINUTE
    assert read.after_at is None and read.wanted_at is None and read.asked_jid is None
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 4 * MINUTE, jid="A2")
    assert (await last_change(sessions)).jid is None


async def test_a_repeated_answer_settles_nothing_more(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await brine_reads(ingest, {"agent": "2.3.0"}, at=T0 + HOUR, jid="A1")
    job_at = T0 + 2 * HOUR
    await ingest.inventory_job_done("a", jid="J2", user="bob", at=job_at)
    # A1's answer delivered again: A1 is no longer out, so J2's want and credit stay.
    answered = T0 + HOUR + 10 * SECOND
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=answered, jid="A1")
    await ingest.inventory_failed("a", "packages", "locked", at=answered, jid="A1")
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.wanted_at) == ("J2", job_at + AFTER_JOB)
    await brine_reads(ingest, {"agent": "2.4.1"}, at=job_at + 2 * MINUTE, jid="A2")
    last = await last_change(sessions)
    assert (last.jid, last.user) == ("J2", "bob")


# Retention.


async def test_old_changes_are_pruned(ingest: Ingest, sessions: Sessions) -> None:
    day = timedelta(days=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, jid=None)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + day, jid=None)
    await ingest.inventory_read("a", "packages", {"agent": "2.5.0"}, at=T0 + 3 * day, jid=None)
    deleted = await ingest.prune(jobs_before=None, history_before=T0 + 2 * day, audit_before=None)
    assert deleted["inventory_changes"] == 1
    assert [c.new for c in await changes_of(sessions, "a")] == ["2.5.0"]
    # Current entries are never pruned, however old.
    await ingest.prune(jobs_before=None, history_before=T0 + 30 * day, audit_before=None)
    assert await items(sessions, "a") == {"agent": "2.5.0"}
