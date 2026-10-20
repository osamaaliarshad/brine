from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ingest import PRESENCE_STATE, Ingest
from app.models import GrainsSnapshot, Job, JobReturn, Minion, PresenceChange
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
