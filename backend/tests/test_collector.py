import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import EventBus
from app.config import Settings
from app.ingest import PRESENCE_STATE, Ingest
from app.inventory import AFTER_JOB, MAX_ENTRIES
from app.models import InventoryChange, InventoryItem, InventoryRead, Job, JobReturn, Minion
from app.salt.client import SaltApiUnavailable
from app.salt.collector import Collector
from app.salt.events import SaltEvent
from tests.conftest import T0, FakeClock

Sessions = async_sessionmaker[AsyncSession]

ROVER_CLI = "rover-cli --version"


def settings(**presence: Any) -> Settings:
    return Settings.model_validate(
        {
            "salt_api": {"url": "https://salt.test", "username": "brine", "password": "x"},
            "auth": {"provider": "none"},
            "presence": presence,
            "inventory": {"checks": {"rover-cli": ROVER_CLI}},
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


SECOND = timedelta(seconds=1)
STAMP = T0 + 5 * SECOND  # ev()'s master stamp; brine's clock says T0


def job_ret(
    jid: str, fun: str, answer: Any, *, args: list[Any] | None = None, **data: Any
) -> SaltEvent:
    """rover-01's return for job `jid`: brine's own call unless `data` says otherwise."""
    fields = {"id": "rover-01", "jid": jid, "fun": fun, "fun_args": args or [], "success": True}
    fields |= {"retcode": 0, "user": "brine", "return": answer, **data}
    return ev(f"salt/job/{jid}/ret/rover-01", **fields)


def ok(stdout: str) -> dict[str, Any]:
    return {"retcode": 0, "stdout": stdout, "stderr": ""}


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


async def test_commands_run_through_brine_are_recorded_under_the_person(
    make_collector: Any, sessions: Sessions
) -> None:
    api = FakeSaltApi([])
    alice = {"brine": {"actor": "alice@example.com"}}
    api.responses["jobs.list_jobs"] = {
        "20261020110000000000": {  # run while brine was away: from the job cache
            "Function": "test.version",
            "Arguments": [],
            "Target": "*",
            "Target-type": "glob",
            "User": "brine",
            "Metadata": alice,
            "StartTime": "2026, Oct 20 11:00:00.000000",
        }
    }
    collector = make_collector(api)
    await collector.sync()
    ret = {"id": "rover-01", "fun": "test.ping", "success": True, "retcode": 0, "user": "brine"}
    # A return can beat brine writing the job down; it's still alice's.
    await collector.handle(ev("salt/job/c1/ret/rover-01", jid="c1", metadata=alice, **ret))
    # brine's own calls (same account, no metadata) stay housekeeping.
    await collector.handle(ev("salt/job/h1/ret/rover-01", jid="h1", **ret))

    async with sessions() as s:
        jobs = {j.jid: j for j in (await s.scalars(select(Job))).all()}
    assert set(jobs) == {"20261020110000000000", "c1"}
    assert {j.user for j in jobs.values()} == {"alice@example.com"}


async def test_reconnects_dont_ask_the_whole_fleet_for_grains_again(make_collector: Any) -> None:
    # A proxy closing the event stream every minute must not mean grains.items every minute.
    api = FakeSaltApi([])
    collector = make_collector(api)
    await collector.sync()
    await collector.sync()
    assert api.count("grains.items") == 1


async def test_a_stream_closing_after_a_while_reconnects_quietly(
    make_collector: Any, clock: Any
) -> None:
    api = FakeSaltApi([[], []])
    collector = make_collector(api)
    sessions = 0
    real_session = collector.run_session

    async def long_session() -> None:
        nonlocal sessions
        sessions += 1
        await real_session()
        clock.advance(minutes=5)  # the stream was up a while, then closed cleanly
        if sessions == 2:
            raise asyncio.CancelledError

    collector.run_session = long_session

    async def no_backoff(delay: float) -> None:
        raise AssertionError("a quiet reconnect doesn't back off")

    collector.backoff_sleep = no_backoff
    with pytest.raises(asyncio.CancelledError):
        await collector.run()
    assert sessions == 2
    assert collector.status.connected and collector.status.error is None


# --- packages and checks -----------------------------------------------------------------


async def inventory_of(sessions: Sessions) -> set[tuple[str, str, str]]:
    async with sessions() as s:
        return {(i.source, i.name, i.value) for i in await s.scalars(select(InventoryItem))}


async def read_of(sessions: Sessions, source: str = "packages") -> InventoryRead:
    async with sessions() as s:
        read = await s.get(InventoryRead, ("rover-01", source))
    assert read is not None
    return read


async def test_package_and_check_answers_are_stored(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_asked(["rover-01"], "packages", at=T0, jid="101")
    await ingest.inventory_asked(["rover-01"], "rover-cli", at=T0, jid="102")
    await collector.handle(job_ret("101", "pkg.list_pkgs", {"rover-agent": "2.4.1"}))
    await collector.handle(job_ret("102", "cmd.run_all", ok("rover-cli 1.2.0\n"), args=[ROVER_CLI]))

    assert await inventory_of(sessions) == {
        ("packages", "rover-agent", "2.4.1"),
        ("rover-cli", "", "rover-cli 1.2.0"),
    }
    for source in ("packages", "rover-cli"):
        read = await read_of(sessions, source)
        # Read as of the master's stamp, and the return's jid settled brine's ask.
        assert (read.read_at, read.error, read.asked_jid) == (STAMP, None, None)


async def test_a_failing_check_is_a_failed_read_and_keeps_its_entries(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "rover-cli", {"": "rover-cli 1.2.0"}, at=T0, jid=None)
    # cmd.run_all marks the call failed when the command fails.
    answer = {"retcode": 127, "stdout": "", "stderr": "sh: rover-cli: not found"}
    await collector.handle(
        job_ret("103", "cmd.run_all", answer, args=[ROVER_CLI], success=False, retcode=127)
    )
    read = await read_of(sessions, "rover-cli")
    assert (read.error, read.answered_at, read.read_at) == (
        "exit 127: sh: rover-cli: not found",
        STAMP,
        T0,
    )
    assert await inventory_of(sessions) == {("rover-cli", "", "rover-cli 1.2.0")}


async def test_a_package_list_salt_says_failed_is_a_failed_read(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    # The function failed on the minion: Salt answers with its error text.
    error = "ERROR: Problem encountered getting the package list"
    await collector.handle(job_ret("104", "pkg.list_pkgs", error, success=False, retcode=1))
    assert (await read_of(sessions)).error == f"unexpected answer: {error}"
    # Nor is a list trusted when Salt says the call failed: it may be partial.
    later = "2026-10-20T12:00:10.000000"
    await collector.handle(
        job_ret("105", "pkg.list_pkgs", {"bash": "5.3"}, success=False, retcode=1, _stamp=later)
    )
    read = await read_of(sessions)
    assert (read.error, read.answered_at) == (
        "Salt said the call failed (retcode 1)",
        T0 + 10 * SECOND,
    )
    assert await inventory_of(sessions) == {("packages", "bash", "5.2")}
    # Without a retcode, the message doesn't make one up.
    latest = "2026-10-20T12:00:15.000000"
    event = job_ret("106", "pkg.list_pkgs", {"bash": "5.4"}, success=False, _stamp=latest)
    del event.data["retcode"]
    await collector.handle(event)
    assert (await read_of(sessions)).error == "Salt said the call failed"


async def test_a_package_list_without_fun_args_is_still_an_answer(
    make_collector: Any, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    event = job_ret("109", "pkg.list_pkgs", {"bash": "5.2"})
    del event.data["fun_args"]
    await collector.handle(event)
    assert await inventory_of(sessions) == {("packages", "bash", "5.2")}


async def test_other_calls_are_not_answers(make_collector: Any, sessions: Sessions) -> None:
    collector = make_collector(FakeSaltApi([]))
    await collector.handle(job_ret("106", "cmd.run_all", ok("hi"), args=["echo hi"]))
    # With arguments, a package list isn't the plain one brine reads. Keyword arguments come
    # as a dict (the salt CLI sends them so) or as a name=value string (a salt-api client can).
    listed = {"rover-agent": ["2.4.1"]}
    await collector.handle(
        job_ret("107", "pkg.list_pkgs", listed, args=[{"versions_as_list": True}])
    )
    await collector.handle(job_ret("108", "pkg.list_pkgs", listed, args=["versions_as_list=True"]))
    assert await inventory_of(sessions) == set()
    async with sessions() as s:
        assert (await s.scalars(select(InventoryRead))).all() == []


@pytest.mark.parametrize(
    ("data", "person"),
    [
        ({"user": "alice"}, "alice"),  # from the salt CLI or salt-api
        ({"metadata": {"brine": {"actor": "bob@example.com"}}}, "bob@example.com"),  # brine
    ],
)
async def test_a_persons_job_that_may_change_software_wants_a_reread(
    make_collector: Any, ingest: Ingest, sessions: Sessions, data: dict[str, Any], person: str
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    await collector.handle(job_ret("201", "state.apply", {}, **data))
    read = await read_of(sessions)
    assert read.wanted_at == STAMP + AFTER_JOB
    assert (read.after_jid, read.after_user, read.after_at) == ("201", person, STAMP)


async def test_brines_own_calls_and_read_only_jobs_dont_want_a_reread(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    await collector.handle(job_ret("301", "state.apply", {}))  # brine's own, for no one
    await collector.handle(job_ret("302", "cmd.run_all", ok(""), args=["true"]))
    await collector.handle(job_ret("303", "test.ping", True, user="alice"))
    await collector.handle(job_ret("304", "pkg.list_pkgs", {"bash": "5.2"}, user="alice"))
    read = await read_of(sessions)
    assert read.wanted_at is None and read.after_at is None


async def test_a_person_running_a_checks_command_reads_it_and_changes_nothing(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    answer = ok("rover-cli 1.2.0")
    await collector.handle(job_ret("401", "cmd.run_all", answer, args=[ROVER_CLI], user="alice"))
    assert ("rover-cli", "", "rover-cli 1.2.0") in await inventory_of(sessions)
    # A check is read-only: nothing to read again, or to credit to the person's run.
    assert (await read_of(sessions)).wanted_at is None
    # Any other command could install something.
    install = ["apt-get install -y rover-cli"]
    await collector.handle(job_ret("402", "cmd.run_all", ok(""), args=install, user="alice"))
    assert (await read_of(sessions)).after_jid == "402"


async def test_a_minion_start_wants_a_reread(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    await collector.handle(ev("salt/minion/rover-01/start", id="rover-01"))
    # As of the master's stamp, like the answers it's compared with.
    assert (await read_of(sessions)).wanted_at == STAMP


async def test_a_minion_start_wants_a_reread_even_if_salt_api_then_fails(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    class SaltApiDown(FakeSaltApi):
        async def local_async(self, tgt: str, fun: str, **kwargs: Any) -> str | None:
            raise SaltApiUnavailable("down")

    collector = make_collector(SaltApiDown([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    with pytest.raises(SaltApiUnavailable):  # asking for its grains fails
        await collector.handle(ev("salt/minion/rover-01/start", id="rover-01"))
    assert (await read_of(sessions)).wanted_at == STAMP


@pytest.mark.parametrize("more", [{"runas": "bob"}, "runas=bob"])
async def test_a_checks_command_with_more_arguments_is_a_job_not_an_answer(
    make_collector: Any, ingest: Ingest, sessions: Sessions, more: Any
) -> None:
    # Keyword arguments come as a dict (the salt CLI sends them so) or as a name=value string
    # (a salt-api client can). They can change the output (runas, env, cwd), and the command
    # could do anything.
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "packages", {"bash": "5.2"}, at=T0, jid=None)
    answer, args = ok("rover-cli 1.2.0"), [ROVER_CLI, more]
    await collector.handle(job_ret("403", "cmd.run_all", answer, args=args, user="alice"))
    assert await inventory_of(sessions) == {("packages", "bash", "5.2")}
    assert (await read_of(sessions)).after_jid == "403"


async def test_a_truncated_answer_is_stored_as_truncated(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    await ingest.inventory_read("rover-01", "rover-cli", {"old": "1"}, at=T0, jid=None)
    stdout = "\n".join(f"c{i}=1" for i in range(MAX_ENTRIES + 1))
    await collector.handle(job_ret("501", "cmd.run_all", ok(stdout), args=[ROVER_CLI]))
    assert (await read_of(sessions, "rover-cli")).truncated
    # Some entries may be missing from it, so none are taken as gone.
    assert ("rover-cli", "old", "1") in await inventory_of(sessions)


@pytest.mark.parametrize(
    ("method", "event"),
    [
        ("inventory_read", job_ret("601", "pkg.list_pkgs", {"bash": "5.2"})),
        ("inventory_job_done", job_ret("602", "state.apply", {}, user="alice")),
        ("inventory_wanted", ev("salt/minion/rover-01/start", id="rover-01")),
    ],
)
async def test_a_failure_recording_packages_or_checks_doesnt_end_the_session(
    make_collector: Any,
    ingest: Ingest,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
    event: SaltEvent,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("broken")

    monkeypatch.setattr(ingest, method, broken)
    api = FakeSaltApi([])
    collector = make_collector(api)
    async with collector.bus.subscribe() as queue:
        await collector.handle(event)  # logged, not raised
        assert "broken" in caplog.text
        # The rest of the event still counts, and browsers hear of it.
        assert not queue.empty()
    assert api.count("grains.items") == (1 if method == "inventory_wanted" else 0)


async def test_browsers_hear_when_a_minions_packages_or_checks_move(make_collector: Any) -> None:
    """An "inventory" hint redoes the fleet compared with that minion: only when a read
    records something (a first read, or anything moved), never for other returns."""
    collector = make_collector(FakeSaltApi([]))

    async def hints(event: SaltEvent) -> list[dict[str, Any]]:
        async with collector.bus.subscribe() as queue:
            await collector.handle(event)
            found = []
            while not queue.empty():
                found.append(queue.get_nowait())
        return found

    stamp = "2026-10-20T12:00:{:02d}.000000"
    inventory = {"type": "inventory", "id": "rover-01"}
    first = await hints(job_ret("1", "pkg.list_pkgs", {"bash": "5.2"}, _stamp=stamp.format(1)))
    assert inventory in first
    same = await hints(job_ret("2", "pkg.list_pkgs", {"bash": "5.2"}, _stamp=stamp.format(2)))
    assert {"type": "minion", "id": "rover-01"} in same and inventory not in same
    moved = await hints(job_ret("3", "pkg.list_pkgs", {"bash": "5.3"}, _stamp=stamp.format(3)))
    assert moved.count(inventory) == 1
    ping = await hints(job_ret("4", "test.ping", True, user="alice", _stamp=stamp.format(4)))
    assert ping and inventory not in ping


async def test_a_persons_job_is_credited_with_brines_read_after_it(
    make_collector: Any, ingest: Ingest, sessions: Sessions
) -> None:
    collector = make_collector(FakeSaltApi([]))
    before = "2026-10-20T11:00:00.000000"
    await collector.handle(job_ret("700", "pkg.list_pkgs", {"bash": "5.2"}, _stamp=before))
    await collector.handle(job_ret("701", "state.apply", {}, user="alice"))
    # The sweep asks for the want, AFTER_JOB after the job; its answer finds the change.
    await ingest.inventory_asked(["rover-01"], "packages", at=STAMP + AFTER_JOB, jid="702")
    after = "2026-10-20T12:01:10.000000"
    await collector.handle(job_ret("702", "pkg.list_pkgs", {"bash": "5.3"}, _stamp=after))
    async with sessions() as s:
        (change,) = await s.scalars(select(InventoryChange))
    assert (change.name, change.old, change.new) == ("bash", "5.2", "5.3")
    assert (change.jid, change.user) == ("701", "alice")
    read = await read_of(sessions)
    assert read.wanted_at is None and read.after_at is None
