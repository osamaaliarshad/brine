from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ingest import PRESENCE_STATE, Ingest
from app.inventory import AFTER_JOB
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


async def items(sessions: Sessions, mid: str, source: str = "packages") -> dict[str, str]:
    async with sessions() as s:
        rows = await s.scalars(select(InventoryItem).filter_by(minion_id=mid, source=source))
        return {r.name: r.value for r in rows}


async def changes_of(sessions: Sessions, mid: str) -> list[InventoryChange]:
    async with sessions() as s:
        q = select(InventoryChange).filter_by(minion_id=mid).order_by(InventoryChange.id)
        return list((await s.scalars(q)).all())


async def read_row(sessions: Sessions, mid: str, source: str = "packages") -> InventoryRead:
    async with sessions() as s:
        read = await s.get(InventoryRead, (mid, source))
        assert read is not None
        return read


async def test_first_read_records_without_changes(ingest: Ingest, sessions: Sessions) -> None:
    changes = await ingest.inventory_read("a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0)
    assert changes.minions == {"a"} and changes.fleet
    assert await items(sessions, "a") == {"bash": "5.2", "agent": "2.3.0"}
    assert await changes_of(sessions, "a") == []  # "already there when brine first looked"
    read = await read_row(sessions, "a")
    assert read.read_at == read.answered_at == read.first_read_at == T0
    assert (await minion(sessions, "a")).key_state == "accepted"


async def test_later_reads_record_each_change(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0)
    later = T0 + timedelta(hours=6)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1", "curl": "8"}, at=later)
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
    hour = timedelta(hours=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    same = await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 + hour)
    assert same.minions == {"a"} and not same.fleet  # the page refreshes ("as of" moved)
    moved = await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + 2 * hour)
    assert moved.minions == {"a"} and moved.fleet
    failed = await ingest.inventory_failed("a", "packages", "locked", at=T0 + 3 * hour)
    assert failed.minions == {"a"} and not failed.fleet


async def test_changes_after_a_job_are_credited_to_it(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice@example.com", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + timedelta(seconds=61), jid="A1")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + timedelta(minutes=2), jid="A1"
    )
    (change,) = await changes_of(sessions, "a")
    assert (change.jid, change.user) == ("J1", "alice@example.com")
    read = await read_row(sessions, "a")
    assert read.after_jid is None and read.after_user is None and read.after_at is None
    # The credit is used up: the next change isn't the job's.
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=7), jid="A2")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.5.0"}, at=T0 + timedelta(hours=8), jid="A2"
    )
    assert (await changes_of(sessions, "a"))[-1].jid is None


async def test_an_answer_to_an_ask_before_the_job_is_not_credited(
    ingest: Ingest, sessions: Sessions
) -> None:
    minute = timedelta(minutes=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=1), jid="A1")
    job_at = T0 + timedelta(hours=1) + minute
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    # The answer to brine's latest ask, but that ask came before the job: what changed may
    # predate it.
    await ingest.inventory_read("a", "packages", {"agent": "2.4.0"}, at=job_at + minute, jid="A1")
    assert (await changes_of(sessions, "a"))[-1].jid is None
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.after_user, read.after_at) == ("J1", "alice", job_at)
    # The credit waits for the answer to an ask made after the job.
    await ingest.inventory_asked(["a"], "packages", at=job_at + 5 * minute, jid="A2")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 6 * minute, jid="A2"
    )
    last = (await changes_of(sessions, "a"))[-1]
    assert (last.old, last.new, last.jid, last.user) == ("2.4.0", "2.4.1", "J1", "alice")


async def test_a_late_answer_to_an_older_ask_is_not_credited(
    ingest: Ingest, sessions: Sessions
) -> None:
    minute = timedelta(minutes=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=1), jid="A1")
    job_at = T0 + timedelta(hours=1) + minute
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + AFTER_JOB, jid="A2")
    # A1's answer arrives after A2 went out. brine's latest ask came after the job, but this
    # isn't its answer: what it shows may predate the job.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.0"}, at=job_at + 2 * minute, jid="A1"
    )
    assert (await changes_of(sessions, "a"))[-1].jid is None
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.wanted_at) == ("J1", job_at + AFTER_JOB)
    # A2's own answer takes the credit and meets the want.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + 3 * minute, jid="A2"
    )
    last = (await changes_of(sessions, "a"))[-1]
    assert (last.old, last.new, last.jid, last.user) == ("2.4.0", "2.4.1", "J1", "alice")
    read = await read_row(sessions, "a")
    assert read.after_jid is None and read.wanted_at is None


async def test_an_answer_to_someone_elses_call_is_not_credited(
    ingest: Ingest, sessions: Sessions
) -> None:
    minute = timedelta(minutes=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + AFTER_JOB, jid="A1")
    # A person's own pkg.list_pkgs (no jid of brine's): its entries count, but not for credit.
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=job_at + 2 * minute)
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    assert (await changes_of(sessions, "a"))[-1].jid is None
    read = await read_row(sessions, "a")
    assert read.read_at == read.answered_at == job_at + 2 * minute
    assert (read.after_jid, read.wanted_at) == ("J1", job_at + AFTER_JOB)
    # The same for a jid brine never asked with.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.2"}, at=job_at + 3 * minute, jid="OTHER"
    )
    assert (await changes_of(sessions, "a"))[-1].jid is None
    assert (await read_row(sessions, "a")).after_jid == "J1"


async def test_a_late_answer_to_brines_ask_still_settles_it(
    ingest: Ingest, sessions: Sessions
) -> None:
    second = timedelta(seconds=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + AFTER_JOB, jid="A1")
    # A person's own read gets in first and finds what the job changed (uncredited).
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=job_at + 120 * second)
    # Late answers from anyone else settle nothing ...
    for jid in (None, "OLD"):
        assert not await ingest.inventory_read(
            "a", "packages", {"agent": "2.4.1"}, at=job_at + 90 * second, jid=jid
        )
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.wanted_at) == ("J1", job_at + AFTER_JOB)
    # ... but A1's own late answer does: the want is met and the credit used up. Items and
    # times stay as the newer read left them.
    assert not await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.0"}, at=job_at + 100 * second, jid="A1"
    )
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    read = await read_row(sessions, "a")
    assert read.read_at == read.answered_at == job_at + 120 * second
    assert read.after_jid is None and read.after_user is None and read.after_at is None
    assert read.wanted_at is None
    # A later change isn't the job's.
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=7), jid="A2")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.5.0"}, at=T0 + timedelta(hours=8), jid="A2"
    )
    assert (await changes_of(sessions, "a"))[-1].jid is None


async def test_a_repeated_answer_leaves_a_newer_jobs_credit(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=1), jid="A1")
    answered = T0 + timedelta(hours=1, seconds=5)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=answered, jid="A1")
    job_at = T0 + timedelta(hours=2)
    await ingest.inventory_job_done("a", jid="J2", user="bob", at=job_at)
    # A1 delivered again: its ask came before J2, so J2's credit and want stay.
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=answered, jid="A1")
    await ingest.inventory_failed("a", "packages", "locked", at=answered, jid="A1")
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.wanted_at) == ("J2", job_at + AFTER_JOB)


async def test_a_late_failure_to_brines_ask(ingest: Ingest, sessions: Sessions) -> None:
    second = timedelta(seconds=1)
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + AFTER_JOB, jid="A1")
    # Only a newer failure got in first: nothing has found what the job changed, so the late
    # failure meets the want but leaves the credit for the next good read.
    await ingest.inventory_failed("a", "packages", "locked", at=job_at + 120 * second)
    await ingest.inventory_failed("a", "packages", "busy", at=job_at + 90 * second, jid="A1")
    read = await read_row(sessions, "a")
    assert read.error == "locked" and read.answered_at == job_at + 120 * second
    assert read.wanted_at is None and read.after_jid == "J1"

    # Once a newer good read has found the changes, a late failure to brine's ask uses up the
    # credit too.
    await ingest.inventory_job_done("a", jid="J2", user="bob", at=job_at + 180 * second)
    await ingest.inventory_asked(["a"], "packages", at=job_at + 240 * second, jid="A2")
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=job_at + 300 * second)
    await ingest.inventory_failed("a", "packages", "busy", at=job_at + 270 * second, jid="A2")
    read = await read_row(sessions, "a")
    assert read.error is None and read.read_at == read.answered_at == job_at + 300 * second
    assert read.after_jid is None and read.wanted_at is None


async def test_the_latest_job_wins_the_credit(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=T0 + timedelta(hours=1))
    await ingest.inventory_job_done("a", jid="J2", user="bob", at=T0 + timedelta(hours=2))
    # A late report of an earlier job doesn't take the credit back.
    await ingest.inventory_job_done("a", jid="J0", user="carol", at=T0 + timedelta(minutes=30))
    read = await read_row(sessions, "a")
    assert (read.after_jid, read.after_user) == ("J2", "bob")
    assert read.wanted_at == T0 + timedelta(hours=2) + AFTER_JOB


async def test_a_repeated_job_report_cant_credit_it_twice(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    await ingest.inventory_asked(["a"], "packages", at=job_at + AFTER_JOB, jid="A1")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + timedelta(minutes=2), jid="A1"
    )
    assert (await changes_of(sessions, "a"))[-1].jid == "J1"
    # The same job reported again (a duplicate event, or a late one): its changes are in.
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    read = await read_row(sessions, "a")
    assert read.after_jid is None and read.after_user is None and read.after_at is None
    assert read.wanted_at is None
    # So a later change isn't credited to it.
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=7), jid="A2")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.5.0"}, at=T0 + timedelta(hours=8), jid="A2"
    )
    assert (await changes_of(sessions, "a"))[-1].jid is None


async def test_a_job_counts_only_for_sources_read_before_it(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 + timedelta(hours=2))
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0)
    # Reported after a newer packages read, which already shows what it changed. The rover
    # check was last read before it, so that still wants a read and gives the credit.
    await ingest.inventory_job_done("a", jid="J0", user="carol", at=T0 + timedelta(hours=1))
    packages, rover = await read_row(sessions, "a"), await read_row(sessions, "a", "rover")
    assert packages.after_jid is None and packages.wanted_at is None
    assert (rover.after_jid, rover.wanted_at) == ("J0", T0 + timedelta(hours=1) + AFTER_JOB)
    # A job after the last read: the next read is wanted, and credited to it.
    job_at = T0 + timedelta(hours=3)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    packages = await read_row(sessions, "a")
    assert (packages.after_jid, packages.after_user, packages.after_at) == ("J1", "alice", job_at)
    assert packages.wanted_at == job_at + AFTER_JOB


async def test_a_start_reported_late_keeps_the_later_want(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_wanted("a", at=T0 + timedelta(hours=2))
    await ingest.inventory_wanted("a", at=T0 + timedelta(hours=1))  # an earlier start, second
    assert (await read_row(sessions, "a")).wanted_at == T0 + timedelta(hours=2)


async def test_a_repeated_start_doesnt_want_another_read(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0)
    started = T0 + timedelta(hours=1)
    await ingest.inventory_wanted("a", at=started)
    await ingest.inventory_asked(["a"], "packages", at=started + timedelta(seconds=5), jid="A1")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=started + timedelta(seconds=10), jid="A1"
    )
    assert (await read_row(sessions, "a")).wanted_at is None
    # The same start reported again: the packages read after it stands. The rover check, not
    # read since, still wants one.
    await ingest.inventory_wanted("a", at=started)
    assert (await read_row(sessions, "a")).wanted_at is None
    assert (await read_row(sessions, "a", "rover")).wanted_at == started


async def test_a_job_wants_a_read_shortly_after_it(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_asked(["a"], "packages", at=T0, jid="A0")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=T0 + timedelta(seconds=5), jid="A0"
    )
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=job_at)
    assert (await read_row(sessions, "a")).wanted_at == job_at + AFTER_JOB

    # The answer to an ask made before the want doesn't meet it ...
    await ingest.inventory_asked(["a"], "packages", at=job_at, jid="A1")
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=job_at + AFTER_JOB * 2, jid="A1"
    )
    assert (await read_row(sessions, "a")).wanted_at == job_at + AFTER_JOB
    # ... nor does an answer to anything but brine's latest ask ...
    await ingest.inventory_asked(["a"], "packages", at=job_at + AFTER_JOB * 3, jid="A2")
    for at, jid in [(AFTER_JOB * 4, None), (AFTER_JOB * 5, "A1"), (AFTER_JOB * 6, "OTHER")]:
        await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=job_at + at, jid=jid)
        assert (await read_row(sessions, "a")).wanted_at == job_at + AFTER_JOB
    # ... its answer, to an ask made at or after the want, does.
    await ingest.inventory_read(
        "a", "packages", {"agent": "2.4.1"}, at=job_at + AFTER_JOB * 7, jid="A2"
    )
    assert (await read_row(sessions, "a")).wanted_at is None


async def test_a_job_on_a_minion_never_read_does_nothing(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_job_done("a", jid="J1", user="alice", at=T0)
    await ingest.inventory_wanted("a", at=T0)
    assert await count(sessions, InventoryRead) == 0  # never read: it's due anyway


async def test_a_start_wants_every_source_read_again(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_read("a", "rover", {"": "1.0"}, at=T0)
    await ingest.inventory_read("b", "packages", {"agent": "2.3.0"}, at=T0)
    started = T0 + timedelta(hours=1)
    await ingest.inventory_wanted("a", at=started)
    assert (await read_row(sessions, "a")).wanted_at == started
    assert (await read_row(sessions, "a", "rover")).wanted_at == started
    assert (await read_row(sessions, "b")).wanted_at is None
    assert await count(sessions, InventoryRead) == 3


async def test_asks_are_recorded_for_each_minion(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_asked(["a", "b"], "packages", at=T0, jid="A1")
    for mid in ("a", "b"):
        read = await read_row(sessions, mid)
        assert read.asked_at == T0 and read.asked_jid == "A1"
        assert read.answered_at is None and read.read_at is None
        assert (await minion(sessions, mid)).key_state == "accepted"
    # No minion matched: no job, so no answer can be the ask's.
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=6), jid=None)
    read = await read_row(sessions, "a")
    assert read.asked_at == T0 + timedelta(hours=6) and read.asked_jid is None


async def test_late_answers_are_ignored(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + timedelta(hours=1))
    assert not await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    # The same answer delivered twice changes nothing either.
    assert not await ingest.inventory_read(
        "a", "packages", {"agent": "2.3.0"}, at=T0 + timedelta(hours=1)
    )
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    assert await changes_of(sessions, "a") == []

    assert not await ingest.inventory_failed("a", "packages", "locked", at=T0)
    read = await read_row(sessions, "a")
    assert read.error is None and read.answered_at == T0 + timedelta(hours=1)


async def test_a_failed_read_keeps_the_last_good_one(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    failed_at = T0 + timedelta(hours=6)
    await ingest.inventory_failed("a", "packages", "dpkg database locked", at=failed_at)
    assert await items(sessions, "a") == {"agent": "2.3.0"}
    read = await read_row(sessions, "a")
    assert read.error == "dpkg database locked" and read.read_at == T0
    assert read.answered_at == failed_at

    later = T0 + timedelta(hours=12)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=later)
    read = await read_row(sessions, "a")
    assert read.error is None and read.read_at == read.answered_at == later
    (change,) = await changes_of(sessions, "a")
    assert change.since == T0  # between the last two good reads


async def test_a_late_good_answer_after_a_failure(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_failed("a", "packages", "locked", at=T0 + timedelta(hours=2))
    # Newer than the last good read, so its entries are kept; the failure is still the latest.
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + timedelta(hours=1))
    assert await items(sessions, "a") == {"agent": "2.4.1"}
    read = await read_row(sessions, "a")
    assert read.read_at == T0 + timedelta(hours=1)
    assert read.answered_at == T0 + timedelta(hours=2) and read.error == "locked"


async def test_a_failure_meets_a_want_like_a_good_answer(
    ingest: Ingest, sessions: Sessions
) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_wanted("a", at=T0 + timedelta(hours=1))
    await ingest.inventory_asked(["a"], "packages", at=T0 + timedelta(hours=1), jid="A1")
    # A failure from someone else's call doesn't meet it; one answering brine's ask does.
    await ingest.inventory_failed(
        "a", "packages", "locked", at=T0 + timedelta(hours=1, seconds=5), jid="OTHER"
    )
    assert (await read_row(sessions, "a")).wanted_at == T0 + timedelta(hours=1)
    await ingest.inventory_failed(
        "a", "packages", "locked", at=T0 + timedelta(hours=1, seconds=6), jid="A1"
    )
    assert (await read_row(sessions, "a")).wanted_at is None


async def test_failing_before_any_good_read(ingest: Ingest, sessions: Sessions) -> None:
    changes = await ingest.inventory_failed("a", "packages", "locked", at=T0)
    assert changes.minions == {"a"}
    read = await read_row(sessions, "a")
    assert read.error == "locked" and read.read_at is None and read.first_read_at is None
    # The first good read after it is still the first: no changes.
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 + timedelta(hours=1))
    assert await changes_of(sessions, "a") == []


async def test_sources_are_independent(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_read("a", "services", {"agent": "running"}, at=T0)
    await ingest.inventory_read("a", "packages", {"curl": "8"}, at=T0 + timedelta(hours=1))
    assert await items(sessions, "a", "services") == {"agent": "running"}
    assert await items(sessions, "a") == {"curl": "8"}
    assert {c.source for c in await changes_of(sessions, "a")} == {"packages"}
    await ingest.inventory_failed("a", "services", "exit 1", at=T0 + timedelta(hours=2))
    assert (await read_row(sessions, "a")).error is None
    assert (await read_row(sessions, "a", "services")).error == "exit 1"


async def test_a_single_value_check(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "rover", {"": "rover 1.0"}, at=T0)
    assert await items(sessions, "a", "rover") == {"": "rover 1.0"}
    await ingest.inventory_read("a", "rover", {"": "rover 1.1"}, at=T0 + timedelta(hours=1))
    (change,) = await changes_of(sessions, "a")
    assert (change.source, change.name, change.old, change.new) == (
        "rover",
        "",
        "rover 1.0",
        "rover 1.1",
    )
    # No output: the thing isn't there any more.
    await ingest.inventory_read("a", "rover", {}, at=T0 + timedelta(hours=2))
    assert await items(sessions, "a", "rover") == {}
    assert (await changes_of(sessions, "a"))[-1].new is None


async def test_truncated_is_stored(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0, truncated=True)
    assert (await read_row(sessions, "a")).truncated
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0 + timedelta(hours=1))
    assert not (await read_row(sessions, "a")).truncated


async def test_old_changes_are_pruned(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + timedelta(days=1))
    await ingest.inventory_read("a", "packages", {"agent": "2.5.0"}, at=T0 + timedelta(days=3))
    deleted = await ingest.prune(
        jobs_before=None, history_before=T0 + timedelta(days=2), audit_before=None
    )
    assert deleted["inventory_changes"] == 1
    assert [c.new for c in await changes_of(sessions, "a")] == ["2.5.0"]
    # Current entries are never pruned, however old.
    await ingest.prune(jobs_before=None, history_before=T0 + timedelta(days=30), audit_before=None)
    assert await items(sessions, "a") == {"agent": "2.5.0"}
