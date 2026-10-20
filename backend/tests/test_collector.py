import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import EventBus
from app.config import Settings
from app.ingest import PRESENCE_STATE, Ingest
from app.models import Job, JobReturn, Minion
from app.salt.client import SaltApiUnavailable
from app.salt.collector import Collector
from app.salt.events import SaltEvent
from tests.conftest import FakeClock

Sessions = async_sessionmaker[AsyncSession]


def settings(**presence: Any) -> Settings:
    return Settings.model_validate(
        {
            "salt_api": {"url": "https://salt.test", "username": "brine", "password": "x"},
            "presence": presence,
        }
    )


class FakeSaltApi:
    """Scripted salt-api: each call to events() plays the next batch (or raises it)."""

    username = "brine"

    def __init__(self, batches: list[list[SaltEvent] | Exception]) -> None:
        self.batches = batches
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.responses: dict[str, Any] = {
            "key.list_all": {"minions": ["rover-01", "rover-02"], "minions_pre": ["rover-04"]},
            "minions.connected": ["rover-01"],
            "key.finger": {
                "minions": {"rover-01": "aa:01", "rover-02": "aa:02"},
                "minions_pre": {"rover-04": "aa:04"},
                "local": {"master.pem": "ff:ff"},
            },
            "manage.status": {"up": ["rover-01", "rover-02"], "down": []},
            "cache.grains": {"rover-02": {"os": "Debian", "cached": True}},
            "jobs.list_jobs": {
                "20261020100000000000": {
                    "Function": "state.apply",
                    "Arguments": [],
                    "Target": "*",
                    "Target-type": "glob",
                    "User": "alice",
                    "StartTime": "2026, Oct 20 10:00:00.000000",
                },
                "20261020100200000000": {  # master-side wheel call: not a minion job
                    "Function": "wheel.key.list_all",
                    "Arguments": [],
                    "Target": "",
                    "Target-type": "",
                    "User": "UNKNOWN",
                    "StartTime": "2026, Oct 20 10:02:00.000000",
                },
                "20261020100100000000": {  # brine's own: never backfilled
                    "Function": "grains.items",
                    "Arguments": [],
                    "Target": "*",
                    "Target-type": "glob",
                    "User": "brine",
                    "StartTime": "2026, Oct 20 10:01:00.000000",
                },
            },
            "jobs.list_job": {
                "Minions": ["rover-01"],
                "Result": {"rover-01": {"return": {"changes": 0}, "retcode": 0, "success": True}},
            },
        }

    async def events(self) -> AsyncIterator[SaltEvent]:
        batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        for event in batch:
            yield event

    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append(("wheel", fun, kwargs))
        return self.responses[fun]

    async def runner(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append(("runner", fun, kwargs))
        return self.responses[fun]

    async def local_async(self, tgt: str, fun: str, **kwargs: Any) -> str | None:
        self.calls.append(("local_async", fun, {"tgt": tgt, **kwargs}))
        return "jid"

    def count(self, fun: str) -> int:
        return sum(1 for _, f, _ in self.calls if f == fun)


def ev(tag: str, **data: Any) -> SaltEvent:
    return SaltEvent(tag, {"_stamp": "2026-10-20T12:00:05.000000", **data})


LIVE_EVENTS = [
    ev("salt/presence/present", present=["rover-01", "rover-02"]),
    ev(
        "salt/job/j1/new",
        jid="j1",
        fun="test.ping",
        tgt="rover-0*",
        tgt_type="glob",
        user="alice",
        arg=[],
        minions=["rover-01", "rover-02"],
    ),
    ev(
        "salt/job/j1/ret/rover-01",
        id="rover-01",
        fun="test.ping",
        jid="j1",
        success=True,
        retcode=0,
        **{"return": True},
    ),
    ev(
        "salt/job/g1/ret/rover-01",
        id="rover-01",
        fun="grains.items",
        jid="g1",
        success=True,
        retcode=0,
        user="brine",
        **{"return": {"os": "Debian", "site": "a"}},
    ),
    ev(
        "salt/job/w1/ret/salt-master_master",
        id="salt-master_master",
        fun="wheel.key.list_all",
        jid="w1",
        success=True,
        **{"return": {}},
    ),
    ev("salt/run/r1/new", fun="runner.jobs.active", user="alice", fun_args=[]),
    ev("salt/run/r1/ret", fun="runner.jobs.active", user="alice", success=True, **{"return": {}}),
    ev("salt/auth", act="pend", id="rover-05"),
    ev("salt/minion/rover-02/start", id="rover-02"),
    ev("salt/presence/change", new=[], lost=["rover-02"]),
    ev("something/we/ignore", x=1),
]


@pytest.fixture
def make_collector(ingest: Ingest, clock: FakeClock) -> Any:
    def make(api: FakeSaltApi, **presence: Any) -> Collector:
        return Collector(api, ingest, settings(**presence), EventBus(), clock=clock)

    return make


async def test_session_syncs_then_processes_events(make_collector: Any, sessions: Sessions) -> None:
    api = FakeSaltApi([LIVE_EVENTS])
    collector = make_collector(api)

    await collector.run_session()  # returns when the stream ends

    async with sessions() as s:
        minions = {m.id: m for m in (await s.scalars(select(Minion))).all()}
        jobs = {j.jid: j for j in (await s.scalars(select(Job))).all()}
        returns = {(r.jid, r.minion_id) for r in (await s.scalars(select(JobReturn))).all()}

    assert minions["rover-04"].key_state == "pending"
    assert minions["rover-04"].key_fingerprint == "aa:04"
    assert minions["rover-01"].key_fingerprint == "aa:01"
    assert minions["rover-05"].key_state == "pending"
    assert minions["rover-01"].connected
    assert not minions["rover-02"].connected  # lost at the end
    assert minions["rover-01"].grains == {"os": "Debian", "site": "a"}
    assert minions["rover-02"].grains_source == "master_cache"

    # Backfilled from the job cache (brine's own job skipped), plus live jobs.
    # brine's own grains refresh (g1) and the master-side wheel job aren't recorded.
    assert set(jobs) == {"20261020100000000000", "j1", "r1"}
    assert "salt-master_master" not in minions
    assert jobs["r1"].kind == "runner" and jobs["r1"].fun == "jobs.active"
    assert ("20261020100000000000", "rover-01") in returns
    assert ("r1", "master") in returns

    # Snapshot sync asked for fresh grains; the start event asked again for rover-02.
    grains_calls = [c for c in api.calls if c[1] == "grains.items"]
    assert [c[2]["tgt"] for c in grains_calls] == ["*", "rover-02"]
    assert collector.status.presence_method == "events"
    # Every event is also kept for the Events page.
    assert [e["tag"] for e in collector.event_log.recent()] == [e.tag for e in LIVE_EVENTS]


async def test_initial_presence_uses_minions_connected_in_auto_mode(
    make_collector: Any, ingest: Ingest
) -> None:
    api = FakeSaltApi([[]])
    collector = make_collector(api)
    await collector.run_session()
    assert api.count("minions.connected") == 1
    assert (await ingest.get_state(PRESENCE_STATE))["method"] == "connected"


async def test_ping_mode_uses_manage_status(make_collector: Any, ingest: Ingest) -> None:
    api = FakeSaltApi([[]])
    await make_collector(api, method="ping").run_session()
    assert api.count("manage.status") == 1 and api.count("minions.connected") == 0
    assert (await ingest.get_state(PRESENCE_STATE))["method"] == "ping"


async def test_events_mode_never_polls(make_collector: Any) -> None:
    api = FakeSaltApi([[]])
    await make_collector(api, method="events").run_session()
    assert api.count("minions.connected") == 0 and api.count("manage.status") == 0


async def test_auto_mode_stops_polling_while_presence_events_flow(
    make_collector: Any, clock: FakeClock
) -> None:
    api = FakeSaltApi([])
    collector = make_collector(api, poll_seconds=60)
    await collector.handle(ev("salt/presence/present", present=["rover-01"]))

    clock.advance(seconds=60)
    await collector._observe_presence()
    assert api.count("minions.connected") == 0  # events are recent: no poll

    clock.advance(seconds=121)
    await collector._observe_presence()
    assert api.count("minions.connected") == 1  # events stopped: fall back


async def test_reconnects_after_failures_and_resyncs(make_collector: Any) -> None:
    api = FakeSaltApi([SaltApiUnavailable("down"), [ev("salt/key", act="accept", id="x")]])
    collector = make_collector(api)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 2:
            raise asyncio.CancelledError

    collector.backoff_sleep = fake_sleep
    with pytest.raises(asyncio.CancelledError):
        await collector.run()

    # Session 1 failed on the stream; session 2 ran and its stream ended normally.
    assert api.count("key.list_all") == 2
    assert len(delays) == 2 and delays[0] < delays[1] * 3
    assert not collector.status.connected
    assert collector.status.error == "event stream closed"


async def test_status_tracks_connection(make_collector: Any) -> None:
    api = FakeSaltApi([[ev("salt/presence/present", present=[])]])
    collector = make_collector(api)
    bus_messages: list[dict[str, Any]] = []
    async with collector.bus.subscribe() as queue:
        await collector.run_session()
        while not queue.empty():
            bus_messages.append(queue.get_nowait())
    assert collector.status.connected  # run() flips it back on stream end
    assert {"type": "status"} in bus_messages
    assert {"type": "fleet"} in bus_messages


async def test_minion_start_clears_presence_blindness(make_collector: Any, ingest: Ingest) -> None:
    from app.ingest import PRESENCE_BLIND_STATE

    api = FakeSaltApi([])
    collector = make_collector(api)
    await ingest.keys({"minions": ["rover-01"]})
    await ingest.presence_blind({})
    assert await ingest.get_state(PRESENCE_BLIND_STATE) == ["rover-01"]
    await collector.handle(ev("salt/minion/rover-01/start", id="rover-01"))
    assert await ingest.get_state(PRESENCE_BLIND_STATE) == []
