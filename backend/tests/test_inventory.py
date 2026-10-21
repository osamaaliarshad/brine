"""Packages and checks: parsing, due rules, the sweep, ingest and the API."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from app import inventory as inv
from app import inventory_sweep as sweeper
from app.api.inventory import version_key
from app.config import Settings, parse_config
from app.models import InventoryRead
from app.salt.client import SaltApiUnavailable
from tests.conftest import T0
from tests.test_api import Api
from tests.test_commands import CSRF, JID, FakeSalt, make_api

ROVER_CLI = "/opt/rover/bin/rover-cli --version || true"
CONTAINERS = "podman ps --format '{{.Names}}={{.Image}}'"


def settings_with(checks: dict[str, str]) -> Settings:
    text = (
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "auth: {provider: none}\n"
    )
    inventory = yaml.safe_dump({"inventory": {"checks": checks}}, sort_keys=False)
    return parse_config(text + inventory, {})


def ok(stdout: str) -> dict[str, Any]:
    return {"retcode": 0, "stdout": stdout, "stderr": ""}


def test_sources_are_packages_then_the_checks() -> None:
    assert inv.sources(settings_with({})) == ["packages"]
    settings = settings_with({"rover-cli": ROVER_CLI, "containers": CONTAINERS})
    assert inv.sources(settings) == ["packages", "rover-cli", "containers"]


def test_packages_are_name_to_version() -> None:
    # Several versions are joined the way Salt writes them (pkg_resource.stringify).
    assert inv.parse_packages({"bash": "5.2", "kernel": ["6.1", "6.2"]}) == (
        {"bash": "5.2", "kernel": "6.1,6.2"},
        None,
        False,
    )


def test_package_versions_that_arent_strings_are_written_out() -> None:
    data = {"odd": None, "num": 7, "mixed": ["1.0", 2]}
    assert inv.parse_packages(data) == ({"odd": "None", "num": "7", "mixed": "1.0,2"}, None, False)


def test_a_package_answer_that_isnt_a_dict_is_an_error() -> None:
    assert inv.parse_packages("'pkg.list_pkgs' is not available.") == (
        {},
        "unexpected answer: 'pkg.list_pkgs' is not available.",
        False,
    )
    _, error, _ = inv.parse_packages("x" * 500)
    assert error == "unexpected answer: " + "x" * 200


def test_an_empty_package_list_is_an_error() -> None:
    # A locked or broken dpkg/rpm database gives {}; a real system always has packages.
    assert inv.parse_packages({}) == ({}, "the package list was empty", False)


def test_packages_skip_long_names_and_cut_long_values() -> None:
    # Neither makes the answer truncated: a name too long to store can never be stored, so
    # nothing stored goes missing, and a cut value is still there.
    longest = "b" * inv.MAX_NAME
    data = {"a" * (inv.MAX_NAME + 1): "1", longest: "2", "big": "v" * (inv.MAX_VALUE + 1)}
    assert inv.parse_packages(data) == ({longest: "2", "big": "v" * inv.MAX_VALUE}, None, False)


def test_control_characters_are_dropped() -> None:
    # PostgreSQL text can't hold NUL, and /proc/device-tree/model ends in one.
    assert inv.parse_packages({"pkg\x00": "1.0\x1b\t2"}) == ({"pkg": "1.0\t2"}, None, False)
    model = ok("NVIDIA Jetson Xavier NX\x00")
    assert inv.parse_check(model) == ({"": "NVIDIA Jetson Xavier NX"}, None, False)
    # A name of only control characters is an empty name, so the line is skipped.
    assert inv.parse_check(ok("\x00=x\nweb=y\x07\n")) == ({"web": "y"}, None, False)
    assert inv.parse_check(ok("\x00\n\x1b\n")) == ({}, None, False)
    assert inv.parse_packages({"\x00": "1", "bash": "5.2"}) == ({"bash": "5.2"}, None, False)
    _, error, _ = inv.parse_check({"retcode": 1, "stdout": "", "stderr": "bad\x00 thing"})
    assert error == "exit 1: bad thing"
    _, error, _ = inv.parse_check({"retcode": "2\x00", "stdout": "", "stderr": ""})
    assert error == "exit 2"
    _, error, _ = inv.parse_packages("nul\x00")
    assert error == "unexpected answer: nul"


@pytest.mark.parametrize(
    ("stdout", "items"),
    [
        (
            "web=ghcr.io/acme/web:1.4\ndb=postgres:16\n",
            {"web": "ghcr.io/acme/web:1.4", "db": "postgres:16"},
        ),
        ("rover-cli 1.2.0\n", {"": "rover-cli 1.2.0"}),
        ("", {}),
        ("  \n", {}),
        ("a=1\nplain line\n", {"": "a=1\nplain line"}),
        (" web = x=y \n\n", {"web": "x=y"}),
        ("=orphan\nweb=x\n", {"web": "x"}),
    ],
)
def test_check_output(stdout: str, items: dict[str, str]) -> None:
    assert inv.parse_check(ok(stdout)) == (items, None, False)


def test_a_check_without_a_retcode_is_read_as_a_success() -> None:
    assert inv.parse_check({"stdout": "1.2.0"}) == ({"": "1.2.0"}, None, False)


def test_a_failing_check_is_an_error_not_an_empty_answer() -> None:
    items, error, _ = inv.parse_check(
        {"retcode": 127, "stdout": "", "stderr": "sh: podman: not found\nmore"}
    )
    assert items == {} and error == "exit 127: sh: podman: not found"
    # No stderr: the first line of stdout; no output at all: just the code.
    answer = {"retcode": 2, "stdout": "\nusage: rover-cli\n", "stderr": ""}
    assert inv.parse_check(answer) == ({}, "exit 2: usage: rover-cli", False)
    assert inv.parse_check({"retcode": 1, "stdout": "", "stderr": ""}) == ({}, "exit 1", False)
    _, error, _ = inv.parse_check({"retcode": 1, "stdout": "", "stderr": "e" * 500})
    assert error == "exit 1: " + "e" * 200


def test_an_answer_that_isnt_a_dict_is_an_error() -> None:
    assert inv.parse_check("'cmd.run_all' is not available.") == (
        {},
        "unexpected answer: 'cmd.run_all' is not available.",
        False,
    )
    _, error, _ = inv.parse_check("x" * 500)
    assert error == "unexpected answer: " + "x" * 200


def test_check_entries_stop_at_max_entries() -> None:
    exactly = "".join(f"k{i}=v\n" for i in range(inv.MAX_ENTRIES))
    items, error, truncated = inv.parse_check(ok(exactly))
    assert len(items) == inv.MAX_ENTRIES and error is None and not truncated
    more = "".join(f"k{i}=v\n" for i in range(inv.MAX_ENTRIES + 10))
    items, error, truncated = inv.parse_check(ok(more))
    assert list(items) == [f"k{i}" for i in range(inv.MAX_ENTRIES)]
    assert error is None and truncated


def test_check_output_past_max_text_is_cut_at_a_whole_line() -> None:
    value = "v" * 1000
    line = f"k000={value}\n"
    stdout = "".join(f"k{i:03}={value}\n" for i in range(100))
    assert len(stdout) > inv.MAX_TEXT
    items, error, truncated = inv.parse_check(ok(stdout))
    # The line the cut went through is left out, not kept as half an entry.
    whole = inv.MAX_TEXT // len(line)
    assert list(items) == [f"k{i:03}" for i in range(whole)]
    assert set(items.values()) == {value}
    assert error is None and truncated


def test_lines_that_end_at_max_text_are_all_kept() -> None:
    # 64 lines of exactly 1024 characters fill MAX_TEXT; the cut falls between lines.
    value = "v" * (1024 - len("k00=\n"))
    stdout = "".join(f"k{i:02}={value}\n" for i in range(70))
    assert stdout[: inv.MAX_TEXT].count("\n") == 64 and stdout[inv.MAX_TEXT - 1] == "\n"
    items, error, truncated = inv.parse_check(ok(stdout))
    assert list(items) == [f"k{i:02}" for i in range(64)]
    assert error is None and truncated


@pytest.mark.parametrize("before", ["", "\n", "\n \n\x00\n"])
def test_one_long_line_past_max_text_is_one_cut_value(before: str) -> None:
    # No whole line with anything in it fits: the long line is kept (and cut), not lost.
    items, error, truncated = inv.parse_check(ok(before + "x" * 70_000))
    assert items == {"": "x" * inv.MAX_VALUE}
    assert error is None and truncated


def test_lines_are_split_on_newlines_only() -> None:
    # Unicode line breaks inside a line don't start a new one; a CRLF ends a line.
    stdout = "x=1\u2028y=2\x85z\nw=3\r\n"
    assert inv.parse_check(ok(stdout)) == ({"x": "1\u2028y=2\x85z", "w": "3"}, None, False)


def test_check_entries_skip_long_names_and_cut_long_values() -> None:
    # Not truncated: only MAX_ENTRIES and MAX_TEXT cut an answer short.
    stdout = "a" * (inv.MAX_NAME + 1) + "=1\nweb=x\n"
    assert inv.parse_check(ok(stdout)) == ({"web": "x"}, None, False)
    stdout = "web=" + "v" * (inv.MAX_VALUE + 1)
    assert inv.parse_check(ok(stdout)) == ({"web": "v" * inv.MAX_VALUE}, None, False)
    stdout = "y" * (inv.MAX_VALUE + 1)
    assert inv.parse_check(ok(stdout)) == ({"": "y" * inv.MAX_VALUE}, None, False)


def test_check_named_matches_the_configured_command() -> None:
    settings = settings_with({"rover-cli": ROVER_CLI, "containers": CONTAINERS})
    assert inv.check_named(settings, [CONTAINERS]) == "containers"
    assert inv.check_named(settings, [ROVER_CLI, {"python_shell": True}]) == "rover-cli"
    assert inv.check_named(settings, ["podman ps"]) is None
    assert inv.check_named(settings, []) is None
    assert inv.check_named(settings, [42]) is None
    assert inv.check_named(settings, CONTAINERS) is None
    assert inv.check_named(settings, None) is None


@pytest.mark.parametrize(
    ("source", "name", "key"),
    [
        ("packages", "rover-agent", "@packages:rover-agent"),
        ("packages", "libc6:i386", "@packages:libc6:i386"),
        ("containers", "web", "@containers:web"),
        ("rover-cli", "", "@rover-cli"),
    ],
)
def test_keys_round_trip(source: str, name: str, key: str) -> None:
    assert inv.key_of(source, name) == key
    assert inv.parse_key(key) == (source, name)


@pytest.mark.parametrize("key", ["app_version", "os:family", "@", ""])
def test_grain_paths_are_not_inventory_keys(key: str) -> None:
    assert inv.parse_key(key) is None


@pytest.mark.parametrize(
    ("fun", "changes"),
    [
        ("state.apply", True),
        ("state.highstate", True),
        ("pkg.install", True),
        ("cmd.run", True),
        ("docker.pull", True),
        ("file.managed", True),
        ("archive.extracted", True),
        ("cp.get_file", True),
        ("service.restart", True),
        ("pip.install", True),
        ("snap.install", True),
        ("flatpak.install", True),
        ("npm.install", True),
        # A person's cmd.run_all can install things; brine's own checks are told apart by user.
        ("cmd.run_all", True),
        ("test.ping", False),
        ("grains.items", False),
        ("pkg.list_pkgs", False),
    ],
)
def test_jobs_that_may_change_software(fun: str, changes: bool) -> None:
    assert inv.may_change_software(fun) is changes


def test_acl_without_checks_is_just_the_package_list() -> None:
    assert inv.acl_lines(settings_with({})) == "- '*':\n  - pkg.list_pkgs\n"


def test_acl_allows_exactly_each_check_command() -> None:
    settings = settings_with({"rover-cli": ROVER_CLI, "containers": CONTAINERS})
    text = inv.acl_lines(settings)
    assert text == (
        "- '*':\n"
        "  - pkg.list_pkgs\n"
        "  - cmd.run_all:\n"
        "      args:\n"
        "        - '^/opt/rover/bin/rover\\-cli\\ \\-\\-version\\ \\|\\|\\ true$'\n"
        "  - cmd.run_all:\n"
        "      args:\n"
        "        - '^podman\\ ps\\ \\-\\-format\\ ''\\{\\{\\.Names\\}\\}=\\{\\{\\.Image\\}\\}''$'\n"
    )
    # It's YAML Salt reads as one rule per check, each matching only its own command, the way
    # Salt matches eauth arguments (re.match on each positional argument, in order). Only the
    # command is pinned: Salt doesn't constrain other arguments or kwargs (shell, env, runas).
    [rules] = yaml.safe_load(text)
    funs = rules["*"]
    assert funs[0] == "pkg.list_pkgs"
    patterns = [fun["cmd.run_all"]["args"] for fun in funs[1:]]
    assert len(patterns) == 2
    for [pattern], command in zip(patterns, [ROVER_CLI, CONTAINERS], strict=True):
        assert re.match(pattern, command)
        assert not re.match(pattern, command + "; reboot")
        assert not re.match(pattern, "x" + command)


def _state(
    asked_jid: str | None = None,
    asked_at: datetime | None = None,
    answered_at: datetime | None = None,
    wanted_at: datetime | None = None,
) -> inv.ReadState:
    return inv.ReadState(
        asked_jid=asked_jid, asked_at=asked_at, answered_at=answered_at, wanted_at=wanted_at
    )


def test_due_rules() -> None:
    every, minute = timedelta(hours=6), timedelta(minutes=1)
    read = _state(answered_at=T0)
    assert inv.is_due(None, now=T0, every=every, back_at=None)
    assert not inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=None)
    assert inv.is_due(read, now=T0 + every, every=every, back_at=None)
    # Back online since the last answer.
    back = T0 + 5 * minute
    assert inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=back)
    assert not inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=T0)
    # Wanted again (a start, a job), once that time comes.
    wanted = _state(answered_at=T0, wanted_at=T0 + 2 * minute)
    assert not inv.is_due(wanted, now=T0 + minute, every=every, back_at=None)
    assert inv.is_due(wanted, now=T0 + 2 * minute, every=every, back_at=None)
    # brine's ask is out: not asked again until ANSWER_WAIT has passed, even when due.
    asked = T0 + timedelta(hours=7)
    waiting = _state(asked_jid="A1", asked_at=asked, answered_at=T0)
    assert not inv.is_due(waiting, now=asked + minute, every=every, back_at=None)
    assert inv.is_due(waiting, now=asked + inv.ANSWER_WAIT, every=every, back_at=None)
    never_answered = _state(asked_jid="A1", asked_at=T0)
    assert not inv.is_due(never_answered, now=T0 + minute, every=every, back_at=None)
    assert inv.is_due(never_answered, now=T0 + inv.ANSWER_WAIT, every=every, back_at=None)
    # Answered: nothing is out any more.
    answered = _state(asked_at=T0, answered_at=T0 + timedelta(seconds=5))
    assert not inv.is_due(answered, now=T0 + minute, every=every, back_at=None)


def test_a_want_stays_until_brines_answer_clears_it() -> None:
    every = timedelta(hours=6)
    t1, t2, t3, t4 = (T0 + timedelta(minutes=m) for m in (1, 2, 3, 4))
    # Asked at T0, then a job at T1 wants a read (and forgets that ask). The old ask's answer
    # arrives at T2: it isn't brine's answer, so the want stays.
    old_answer = _state(asked_at=T0, answered_at=t2, wanted_at=t1)
    assert inv.is_due(old_answer, now=t2, every=every, back_at=None)
    # Asked again at T3: waiting for that answer, not asked again.
    asked_again = _state(asked_jid="A2", asked_at=t3, answered_at=t2, wanted_at=t1)
    assert not inv.is_due(asked_again, now=t4, every=every, back_at=None)
    # Its answer clears the want.
    met = _state(asked_at=t3, answered_at=t4)
    assert not inv.is_due(met, now=t4, every=every, back_at=None)
    # The clocks aren't compared: brine's ask is out whatever the master stamped the last
    # answer with (here, a master clock ahead of brine's).
    skewed = _state(asked_jid="A1", asked_at=T0, answered_at=t4, wanted_at=t1)
    assert not inv.is_due(skewed, now=t2, every=every, back_at=None)


def test_a_want_is_asked_again_when_its_answer_is_lost() -> None:
    every = timedelta(hours=6)
    t1, t3 = T0 + timedelta(minutes=1), T0 + timedelta(minutes=3)
    # Wanted at T1 and asked at T3, but no answer came (a dropped return, a reconnect).
    lost = _state(asked_jid="A1", asked_at=t3, answered_at=T0, wanted_at=t1)
    assert not inv.is_due(lost, now=t3 + timedelta(minutes=1), every=every, back_at=None)
    assert inv.is_due(lost, now=t3 + inv.ANSWER_WAIT, every=every, back_at=None)


def test_an_ask_that_matched_no_minion_is_waited_for_too() -> None:
    every = timedelta(hours=6)
    # No minion matched, so salt-api started no job: brine still waits before asking again,
    # rather than asking on every sweep.
    nothing = _state(asked_jid=inv.NO_JOB, asked_at=T0, answered_at=T0 - every)
    assert not inv.is_due(nothing, now=T0 + timedelta(seconds=15), every=every, back_at=None)
    assert inv.is_due(nothing, now=T0 + inv.ANSWER_WAIT, every=every, back_at=None)
    # Salt's jids are digits, so no answer can be taken for it.
    assert not inv.NO_JOB.isdigit()


def test_the_credit_window_covers_the_wait_and_one_lost_answer() -> None:
    assert inv.CREDIT_WINDOW > inv.AFTER_JOB + inv.ANSWER_WAIT


def test_the_ask_made_for_a_job_is_past_the_clock_margin() -> None:
    # It comes AFTER_JOB after the job, so it's never taken as sent before it.
    assert inv.CLOCK_MARGIN < inv.AFTER_JOB


# --- the sweep and Ask now ------------------------------------------------------------------

SECOND, MINUTE = timedelta(seconds=1), timedelta(minutes=1)
ONLINE = ["dock-01", "rover-01", "rover-02"]  # make_api: rover-03 offline, rover-04 pending
CHECKS = yaml.safe_dump(
    {"inventory": {"checks": {"rover-cli": ROVER_CLI, "containers": CONTAINERS}}}, sort_keys=False
)


@pytest.fixture
def admin(tmp_path: Path) -> Iterator[tuple[Api, FakeSalt]]:
    yield from make_api(tmp_path, "admin")


@pytest.fixture
def with_checks(tmp_path: Path) -> Iterator[tuple[Api, FakeSalt]]:
    yield from make_api(tmp_path, "admin", CHECKS)


def runtime(api: Api) -> Any:
    return api.client.app.state.runtime  # type: ignore[attr-defined]


def sweep(api: Api, now: datetime) -> None:
    api.seed(sweeper.sweep, runtime(api), now)


def read_of(api: Api, mid: str, source: str = "packages") -> InventoryRead | None:
    async def get() -> InventoryRead | None:
        async with runtime(api).sessions() as s:
            return await s.get(InventoryRead, (mid, source))  # type: ignore[no-any-return]

    return api.seed(get)  # type: ignore[no-any-return]


def answer(
    api: Api, mid: str, entries: dict[str, str], *, at: datetime, source: str = "packages"
) -> None:
    """The minion answers brine's ask still out."""
    read = read_of(api, mid, source)
    assert read is not None and read.asked_jid is not None
    api.seed(api.ingest.inventory_read, mid, source, entries, at=at, jid=read.asked_jid)


def calls(salt: FakeSalt) -> list[tuple[str, dict[str, Any]]]:
    return [(fun, kw) for kind, fun, kw in salt.calls if kind == "local_async"]


def test_connected_minions_are_asked_once_until_due(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    now = datetime.now(UTC)
    sweep(api, now)
    # One job for all of them; not rover-03 (offline) or rover-04 (pending).
    assert calls(salt) == [
        ("pkg.list_pkgs", {"tgt": "dock-01,rover-01,rover-02", "tgt_type": "list"})
    ]
    read = read_of(api, "rover-01")
    assert read is not None and (read.asked_at, read.asked_jid) == (now, JID)
    sweep(api, now + MINUTE)  # waiting for the answers
    assert len(salt.calls) == 1
    sweep(api, now + inv.ANSWER_WAIT)  # none came: asked again
    assert salt.asked("pkg.list_pkgs") == ONLINE * 2


def test_answered_minions_wait_for_the_refresh(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    now = datetime.now(UTC)
    sweep(api, now)
    for mid in ONLINE:
        answer(api, mid, {"bash": "5.2"}, at=now + 5 * SECOND)
    sweep(api, now + inv.ANSWER_WAIT)
    assert len(salt.calls) == 1
    # refresh_hours (6) after the answers, with a fresh presence check then.
    due = now + 5 * SECOND + timedelta(hours=6)
    api.seed(api.ingest.presence, ONLINE, at=due - SECOND, method="events")
    sweep(api, due - SECOND)
    assert len(salt.calls) == 1
    sweep(api, due)
    assert salt.asked("pkg.list_pkgs") == ONLINE * 2


def test_a_job_wants_a_read_shortly_after(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    now = datetime.now(UTC)
    sweep(api, now)
    for mid in ONLINE:
        answer(api, mid, {"bash": "5.2"}, at=now + 5 * SECOND)
    job_at = now + MINUTE
    api.seed(api.ingest.inventory_job_done, "rover-01", jid="J1", user="alice", at=job_at)
    sweep(api, job_at + inv.AFTER_JOB - SECOND)
    assert len(salt.calls) == 1
    sweep(api, job_at + inv.AFTER_JOB)
    assert salt.asked("pkg.list_pkgs") == [*ONLINE, "rover-01"]
    read = read_of(api, "rover-01")
    assert read is not None and read.asked_at == job_at + inv.AFTER_JOB


def test_a_minion_that_came_back_is_asked(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    now = datetime.now(UTC)
    sweep(api, now)
    for mid in ONLINE:
        answer(api, mid, {"bash": "5.2"}, at=now + 5 * SECOND)
    # rover-02 drops off and comes back after its answer; rover-03 comes back, never read.
    api.seed(api.ingest.presence_change, new=[], lost=["rover-02"], at=now + 10 * SECOND)
    back = ["rover-02", "rover-03"]
    api.seed(api.ingest.presence_change, new=back, lost=[], at=now + 20 * SECOND)
    sweep(api, now + MINUTE)
    assert salt.asked("pkg.list_pkgs") == [*ONLINE, *back]


def test_checks_are_asked_with_their_exact_command(with_checks: tuple[Api, FakeSalt]) -> None:
    api, salt = with_checks
    sweep(api, datetime.now(UTC))
    target = "dock-01,rover-01,rover-02"
    assert calls(salt) == [
        ("pkg.list_pkgs", {"tgt": target, "tgt_type": "list"}),
        ("cmd.run_all", {"tgt": target, "arg": [ROVER_CLI], "tgt_type": "list"}),
        ("cmd.run_all", {"tgt": target, "arg": [CONTAINERS], "tgt_type": "list"}),
    ]
    # Each source waits for its own job.
    reads = [read_of(api, "rover-01", source) for source in ("packages", "rover-cli", "containers")]
    assert [r.asked_jid for r in reads if r] == [JID, str(int(JID) + 1), str(int(JID) + 2)]


def test_each_sweep_asks_a_batch_per_source(
    with_checks: tuple[Api, FakeSalt], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, salt = with_checks
    monkeypatch.setattr(sweeper, "BATCH", 2)
    now = datetime.now(UTC)
    sweep(api, now)
    assert [kw["tgt"] for _, kw in calls(salt)] == ["dock-01,rover-01"] * 3
    sweep(api, now + 15 * SECOND)
    assert [kw["tgt"] for _, kw in calls(salt)][3:] == ["rover-02"] * 3


def test_nobody_is_asked_on_stale_presence(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    sweep(api, datetime.now(UTC) + timedelta(hours=1))  # no presence check for an hour
    assert salt.calls == []


def test_a_refused_source_is_remembered_until_asking_works(
    admin: tuple[Api, FakeSalt],
) -> None:
    api, salt = admin
    salt.forbidden.add("pkg.list_pkgs")
    now = datetime.now(UTC)
    sweep(api, now)
    refused = api.seed(api.ingest.get_state, inv.REFUSED_STATE)
    assert "isn't allowed to run pkg.list_pkgs" in refused["packages"]
    # Not asked again on every sweep: each refusal makes brine log in to salt-api again.
    sweep(api, now + MINUTE)
    assert len(salt.calls) == 1
    salt.forbidden.clear()
    sweep(api, now + inv.ANSWER_WAIT)
    assert salt.asked("pkg.list_pkgs") == ONLINE * 2
    assert api.seed(api.ingest.get_state, inv.REFUSED_STATE) == {}


def test_asking_again_when_salt_api_fails(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    salt.start_error = SaltApiUnavailable("can't reach salt-api")
    now = datetime.now(UTC)
    sweep(api, now)
    assert read_of(api, "rover-01") is None  # nothing was asked
    assert api.seed(api.ingest.get_state, inv.REFUSED_STATE) is None
    salt.start_error = None
    sweep(api, now + 15 * SECOND)
    assert salt.asked("pkg.list_pkgs") == ONLINE * 2


def test_an_ask_that_matched_no_minion_is_waited_for(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin

    async def matched_nothing(tgt: str, fun: str, **kwargs: Any) -> str | None:
        salt.calls.append(("local_async", fun, {"tgt": tgt, **kwargs}))
        return None

    salt.local_async = matched_nothing  # type: ignore[method-assign]
    now = datetime.now(UTC)
    sweep(api, now)
    read = read_of(api, "rover-01")
    assert read is not None and read.asked_jid == inv.NO_JOB
    sweep(api, now + 15 * SECOND)
    assert len(salt.calls) == 1


SOURCES = ("packages", "rover-cli", "containers")


def test_ask_now_for_the_fleet_is_asked_by_the_sweep(
    with_checks: tuple[Api, FakeSalt], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, salt = with_checks
    monkeypatch.setattr(sweeper, "BATCH", 2)
    rt, now = runtime(api), datetime.now(UTC)
    sweep(api, now)
    sweep(api, now + 15 * SECOND)
    for mid in ONLINE:  # everyone has answered everything: nothing is due
        for source in SOURCES:
            answer(api, mid, {}, at=now + 20 * SECOND, source=source)
    later = now + 30 * SECOND
    queued = api.seed(sweeper.ask_now, rt, None, later)
    assert (queued.asked, queued.queued, queued.failed, queued.reason) == (ONLINE, True, {}, None)
    assert len(salt.calls) == 6  # nothing sent: the sweep asks them, BATCH at a time
    sweep(api, later)
    assert [kw["tgt"] for _, kw in calls(salt)][6:] == ["dock-01,rover-01"] * 3
    sweep(api, later + 15 * SECOND)
    assert [kw["tgt"] for _, kw in calls(salt)][9:] == ["rover-02"] * 3
    with pytest.raises(sweeper.Throttled, match="in a minute") as caught:
        api.seed(sweeper.ask_now, rt, None, later)  # once a minute for everyone
    assert 0 < caught.value.retry_after <= 60


def test_ask_now_for_one_minion_asks_it_directly(with_checks: tuple[Api, FakeSalt]) -> None:
    api, salt = with_checks
    rt, now = runtime(api), datetime.now(UTC)
    one = api.seed(sweeper.ask_now, rt, "rover-01", now)
    assert (one.asked, one.queued, one.failed, one.reason) == (["rover-01"], False, {}, None)
    assert [(fun, kw["tgt"]) for fun, kw in calls(salt)] == [
        ("pkg.list_pkgs", "rover-01"),
        ("cmd.run_all", "rover-01"),
        ("cmd.run_all", "rover-01"),
    ]
    with pytest.raises(sweeper.Throttled, match="in a few seconds") as caught:
        api.seed(sweeper.ask_now, rt, "rover-01", now)
    assert 0 < caught.value.retry_after <= 10
    offline = api.seed(sweeper.ask_now, rt, "rover-03", now)
    assert (offline.asked, offline.reason) == ([], "rover-03 isn't online")
    # Nothing went out, so it may be asked again straight away.
    assert api.seed(sweeper.ask_now, rt, "rover-03", now).reason == "rover-03 isn't online"


def test_asking_minions_one_by_one_is_capped(
    admin: tuple[Api, FakeSalt], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, salt = admin
    monkeypatch.setattr(sweeper, "BATCH", 2)  # one by one: at most BATCH a minute
    rt, now = runtime(api), datetime.now(UTC)
    for mid in ("dock-01", "rover-01"):
        assert api.seed(sweeper.ask_now, rt, mid, now).asked == [mid]
    with pytest.raises(sweeper.Throttled, match="one by one") as caught:
        api.seed(sweeper.ask_now, rt, "rover-02", now)
    assert 0 < caught.value.retry_after <= 60
    assert salt.asked("pkg.list_pkgs") == ["dock-01", "rover-01"]
    # The whole fleet can still be asked.
    assert api.seed(sweeper.ask_now, rt, None, now).asked == ONLINE


# --- the API ---------------------------------------------------------------------------------

HOUR = timedelta(hours=1)


def read(
    api: Api, mid: str, entries: dict[str, str], at: datetime, source: str = "packages"
) -> None:
    api.seed(api.ingest.inventory_read, mid, source, entries, at=at, jid=None)


def seed_agent(api: Api, at: datetime) -> None:
    """rover-agent 2.10.0 on rover-01 (read an hour before `at`) and rover-03, 2.9.1 on
    rover-02, and not on dock-01."""
    read(api, "rover-01", {"rover-agent": "2.10.0", "bash": "5.2"}, at - HOUR)
    read(api, "rover-02", {"rover-agent": "2.9.1", "bash": "5.2"}, at)
    read(api, "rover-03", {"rover-agent": "2.10.0", "bash": "5.2"}, at)
    read(api, "dock-01", {"bash": "5.2"}, at)


def values(api: Api, key: str) -> Any:
    return api.get("/api/inventory/values", key=key)


def when(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def test_versions_sort_like_package_managers() -> None:
    versions = ["2.10.0", "2.9.1", "10.0", "2.9", "2.9.1-1ubuntu1", "1:1.0-1"]
    assert sorted(versions, key=version_key) == [
        "2.9",
        "2.9.1",
        "2.9.1-1ubuntu1",
        "2.10.0",
        "10.0",
        "1:1.0-1",
    ]
    assert version_key("1:1.0-1") > version_key("2.10-1")  # the epoch comes first
    assert version_key("1.0~rc1-1") < version_key("1.0-1")  # ~ comes before anything,
    assert version_key("1.0~rc1") < version_key("1.0")  # even the end
    assert version_key("1.0~rc1") < version_key("1.0~rc2")
    # A colon after something other than digits isn't an epoch.
    assert version_key("ghcr.io/acme/web:1.4") < version_key("ghcr.io/acme/web:1.10")
    # A digit to str.isdigit(), but not a number: text, and no crash.
    assert sorted(["²", "2"], key=version_key) == ["2", "²"]


def test_values_split_versions_missing_and_unknown(admin: tuple[Api, FakeSalt]) -> None:
    api, _ = admin
    now = datetime.now(UTC)
    seed_agent(api, now)
    d = values(api, "@packages:rover-agent")
    # Newest version first: 2.10 comes after 2.9.
    assert d["values"] == [
        {"value": "2.10.0", "text": "2.10.0", "minions": ["rover-01", "rover-03"]},
        {"value": "2.9.1", "text": "2.9.1", "minions": ["rover-02"]},
    ]
    assert (d["key"], d["source"], d["name"], d["kind"], d["total"]) == (
        "@packages:rover-agent",
        "packages",
        "rover-agent",
        "package",
        4,
    )
    assert (d["missing"], d["unknown"], d["refused"]) == (["dock-01"], [], None)
    assert (when(d["oldest_read_at"]), when(d["newest_read_at"])) == (now - HOUR, now)


def test_never_read_minions_are_unknown_not_missing(admin: tuple[Api, FakeSalt]) -> None:
    api, _ = admin
    now = datetime.now(UTC)
    read(api, "rover-01", {"rover-agent": "2.4.1"}, now)
    # Only a failed answer is still unknown. Pending and rejected keys aren't counted at all.
    api.seed(api.ingest.inventory_failed, "rover-02", "packages", "locked", at=now, jid=None)
    api.seed(api.ingest.key_event, "rover-05", "reject")
    for mid in ("rover-04", "rover-05"):
        read(api, mid, {"rover-agent": "2.3.0"}, now)
    d = values(api, "@packages:rover-agent")
    assert [(v["text"], v["minions"]) for v in d["values"]] == [("2.4.1", ["rover-01"])]
    assert (d["total"], d["missing"]) == (4, [])
    assert d["unknown"] == ["dock-01", "rover-02", "rover-03"]


def test_values_say_when_salt_api_refuses_the_source(admin: tuple[Api, FakeSalt]) -> None:
    api, _ = admin
    why = "brine's Salt account isn't allowed to run pkg.list_pkgs"
    api.seed(api.ingest.set_state_entry, inv.REFUSED_STATE, "packages", why)
    d = values(api, "@packages:rover-agent")
    assert (d["refused"], d["values"], d["oldest_read_at"], d["newest_read_at"]) == (
        why,
        [],
        None,
        None,
    )
    assert d["unknown"] == ["dock-01", "rover-01", "rover-02", "rover-03"]


def test_values_of_a_check(with_checks: tuple[Api, FakeSalt]) -> None:
    api, _ = with_checks
    now = datetime.now(UTC)
    read(api, "rover-01", {"": "rover-cli 1.2.0"}, now, source="rover-cli")
    read(api, "rover-02", {}, now, source="rover-cli")  # printed nothing: not there
    d = values(api, "@rover-cli")
    assert (d["source"], d["name"], d["kind"]) == ("rover-cli", "", "check")
    assert [(v["text"], v["minions"]) for v in d["values"]] == [("rover-cli 1.2.0", ["rover-01"])]
    assert (d["missing"], d["unknown"]) == (["rover-02"], ["dock-01", "rover-03"])
    assert values(api, "@rover-cli:")["key"] == "@rover-cli"  # the key as brine writes it


def test_a_read_cut_short_without_the_entry_is_unknown(with_checks: tuple[Api, FakeSalt]) -> None:
    api, _ = with_checks
    now = datetime.now(UTC)
    # Truncated: an entry the answer doesn't list may be past the cut.
    for mid, images in (("rover-01", {"db": "postgres:16"}), ("rover-02", {"web": "web:1.4"})):
        api.seed(
            api.ingest.inventory_read, mid, "containers", images, at=now, jid=None, truncated=True
        )
    read(api, "dock-01", {"db": "postgres:16"}, now, source="containers")
    d = values(api, "@containers:web")
    assert [(v["text"], v["minions"]) for v in d["values"]] == [("web:1.4", ["rover-02"])]
    assert (d["missing"], d["unknown"]) == (["dock-01"], ["rover-01", "rover-03"])


def test_keys_list_checks_and_find_packages(with_checks: tuple[Api, FakeSalt]) -> None:
    api, _ = with_checks
    now = datetime.now(UTC)
    seed_agent(api, now)
    read(api, "rover-04", {"rover-agent": "2.3.0"}, now)  # pending: not counted
    read(api, "rover-01", {"": "rover-cli 1.2.0"}, now, source="rover-cli")
    read(api, "rover-01", {"web": "ghcr.io/acme/web:1.4"}, now, source="containers")
    images = {"web": "ghcr.io/acme/web:1.5", "db": "postgres:16"}
    read(api, "rover-02", images, now, source="containers")
    read(api, "rover-01", {"x": "1"}, now, source="old-check")  # no longer configured
    # Without a search: every check's entries, and no packages.
    assert [(k["key"], k["kind"], k["minions"]) for k in api.get("/api/inventory/keys")] == [
        ("@containers:db", "check", 1),
        ("@containers:web", "check", 2),
        ("@rover-cli", "check", 1),
    ]
    # A search finds packages by part of their name, whatever the case.
    assert api.get("/api/inventory/keys", q="AGENT") == [
        {
            "key": "@packages:rover-agent",
            "source": "packages",
            "name": "rover-agent",
            "kind": "package",
            "minions": 3,
        }
    ]
    # Checks are searched too (entry or check name), so they can't crowd packages out.
    assert [k["key"] for k in api.get("/api/inventory/keys", q="web")] == ["@containers:web"]
    assert [k["key"] for k in api.get("/api/inventory/keys", q="cli")] == ["@rover-cli"]
    assert api.get("/api/inventory/keys", q="%") == []  # matched as typed, not as a pattern
    assert len(api.get("/api/inventory/keys", limit=1)) == 1
    assert api.client.get("/api/inventory/keys", params={"limit": 0}).status_code == 422


def test_keys_without_checks(admin: tuple[Api, FakeSalt]) -> None:
    api, _ = admin
    seed_agent(api, datetime.now(UTC))
    assert api.get("/api/inventory/keys") == []
    found = api.get("/api/inventory/keys", q="agent")
    assert [(k["key"], k["minions"]) for k in found] == [("@packages:rover-agent", 3)]


def test_changes_newest_first_by_key_and_by_minion(admin: tuple[Api, FakeSalt]) -> None:
    api, _ = admin
    now = datetime.now(UTC)
    seed_agent(api, now)
    read(api, "rover-02", {"rover-agent": "2.10.0", "bash": "5.2"}, now + MINUTE)
    read(api, "rover-02", {"rover-agent": "2.10.0", "bash": "5.3"}, now + 2 * MINUTE)
    # dock-01 gets it from alice's job, and brine's read after it finds it.
    job_at, asked = now + 3 * MINUTE, now + 3 * MINUTE + inv.AFTER_JOB
    api.seed(api.ingest.inventory_job_done, "dock-01", jid="J1", user="alice", at=job_at)
    api.seed(api.ingest.inventory_asked, ["dock-01"], "packages", at=asked, jid="A1")
    found = {"rover-agent": "2.10.0", "bash": "5.2"}
    api.seed(api.ingest.inventory_read, "dock-01", "packages", found, at=asked, jid="A1")

    by_key = api.get("/api/inventory/changes", key="@packages:rover-agent")
    assert [(c["minion_id"], c["old"], c["new"], c["jid"], c["user"]) for c in by_key] == [
        ("dock-01", None, "2.10.0", "J1", "alice"),
        ("rover-02", "2.9.1", "2.10.0", None, None),
    ]
    upgrade = by_key[1]
    assert (upgrade["source"], upgrade["name"]) == ("packages", "rover-agent")
    assert (when(upgrade["since"]), when(upgrade["at"])) == (now, now + MINUTE)
    by_minion = api.get("/api/inventory/changes", minion="rover-02")
    assert [(c["name"], c["new"]) for c in by_minion] == [
        ("bash", "5.3"),
        ("rover-agent", "2.10.0"),
    ]
    both = api.get("/api/inventory/changes", key="@packages:rover-agent", minion="rover-02")
    assert both == [upgrade]
    assert len(api.get("/api/inventory/changes")) == 3
    assert [c["minion_id"] for c in api.get("/api/inventory/changes", limit=1)] == ["dock-01"]


def test_minion_inventory_lists_every_source(with_checks: tuple[Api, FakeSalt]) -> None:
    api, _ = with_checks
    now = datetime.now(UTC)
    seed_agent(api, now)
    failed = "exit 127: not found"
    api.seed(api.ingest.inventory_failed, "rover-01", "rover-cli", failed, at=now, jid=None)
    packages, cli, containers = api.get("/api/minions/rover-01/inventory")["sources"]
    assert [(e["name"], e["value"]) for e in packages["entries"]] == [
        ("bash", "5.2"),
        ("rover-agent", "2.10.0"),
    ]
    assert (packages["source"], packages["kind"], packages["error"], packages["truncated"]) == (
        "packages",
        "package",
        None,
        False,
    )
    times = [when(packages[k]) for k in ("read_at", "first_read_at", "answered_at")]
    assert times == [now - HOUR] * 3
    assert when(packages["entries"][0]["since"]) == now - HOUR
    # A check that failed, and one never read: listed all the same.
    assert (cli["source"], cli["kind"], cli["error"], cli["read_at"], cli["entries"]) == (
        "rover-cli",
        "check",
        failed,
        None,
        [],
    )
    assert containers == {
        "source": "containers",
        "kind": "check",
        "read_at": None,
        "first_read_at": None,
        "answered_at": None,
        "error": None,
        "truncated": False,
        "entries": [],
    }
    assert api.client.get("/api/minions/ghost/inventory").status_code == 404


@pytest.mark.parametrize("key", ["app_version", "os:family", "@", "@packages", "@nope:x", "@nope"])
def test_keys_that_arent_a_package_or_a_check_are_422(
    admin: tuple[Api, FakeSalt], key: str
) -> None:
    api, _ = admin
    for path in ("/api/inventory/values", "/api/inventory/changes"):
        resp = api.client.get(path, params={"key": key})
        assert resp.status_code == 422, path
        assert "isn't a package or a configured check" in resp.json()["detail"]


def ask(api: Api, **body: Any) -> Any:
    return api.client.post("/api/inventory/ask", json=body, headers=CSRF)


def test_ask_now_for_everyone_signed_in(tmp_path: Path) -> None:
    for api, salt in make_api(tmp_path, "viewer"):  # it only reads
        fleet = ask(api)
        assert fleet.json() == {"asked": ONLINE, "queued": True, "failed": {}, "reason": None}
        assert salt.calls == []  # queued: the sweep asks them
        throttled = ask(api)
        assert throttled.status_code == 429
        assert throttled.json()["detail"] == "Asked a moment ago; try again in a minute."
        assert 0 < int(throttled.headers["Retry-After"]) <= 60
        one = ask(api, minion="rover-01")
        assert one.json() == {"asked": ["rover-01"], "queued": False, "failed": {}, "reason": None}
        throttled = ask(api, minion="rover-01")
        assert throttled.status_code == 429
        assert throttled.json()["detail"] == "Asked a moment ago; try again in a few seconds."
        assert 0 < int(throttled.headers["Retry-After"]) <= 10
        offline = ask(api, minion="rover-03").json()
        assert (offline["asked"], offline["reason"]) == ([], "rover-03 isn't online")
        assert ask(api, minion="ghost").status_code == 404
        no_csrf = api.client.post("/api/inventory/ask", json={"minion": "dock-01"})
        assert no_csrf.status_code == 403 and "X-Requested-With" in no_csrf.json()["detail"]
        assert salt.asked("pkg.list_pkgs") == ["rover-01"]


def test_ask_now_says_what_salt_api_did(with_checks: tuple[Api, FakeSalt]) -> None:
    api, salt = with_checks
    salt.start_error = SaltApiUnavailable("can't reach salt-api")
    down = ask(api, minion="rover-01")
    assert down.status_code == 502 and down.json()["detail"] == "salt-api: can't reach salt-api"
    # Nothing went out, so asking again isn't throttled.
    salt.start_error = None
    salt.forbidden |= {"pkg.list_pkgs", "cmd.run_all"}
    refused = ask(api, minion="rover-01")
    assert refused.status_code == 403
    assert "isn't allowed to run pkg.list_pkgs" in refused.json()["detail"]
    assert "external_auth" in refused.json()["detail"]
    # Some sources went out: the others are named.
    salt.forbidden = {"cmd.run_all"}
    partly = ask(api, minion="rover-01")
    assert partly.status_code == 200
    body = partly.json()
    assert (body["asked"], sorted(body["failed"])) == (["rover-01"], ["containers", "rover-cli"])
    assert "isn't allowed to run cmd.run_all" in body["failed"]["rover-cli"]


def test_ask_now_when_presence_is_stale_or_nobody_is_online(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    now = datetime.now(UTC)
    api.seed(api.ingest.presence, ONLINE, at=now - HOUR, method="events")
    stale = {"asked": [], "queued": True, "failed": {}, "reason": "presence is stale"}
    assert ask(api).json() == stale
    assert ask(api).json() == stale  # nothing was queued, so not throttled
    assert ask(api, minion="rover-01").json()["reason"] == "presence is stale"
    api.seed(api.ingest.presence, [], at=now, method="events")
    assert ask(api).json()["reason"] == "no minions are online"
    assert salt.calls == []
