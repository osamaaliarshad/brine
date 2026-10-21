"""Packages and checks: parsing, due rules, the sweep, ingest and the API."""

import re
from datetime import timedelta
from typing import Any

import pytest
import yaml

from app import inventory as inv
from app.config import Settings, parse_config
from tests.conftest import T0

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
    longest = "b" * inv.MAX_NAME
    data = {"a" * (inv.MAX_NAME + 1): "1", longest: "2", "big": "v" * (inv.MAX_VALUE + 1)}
    assert inv.parse_packages(data) == ({longest: "2", "big": "v" * inv.MAX_VALUE}, None, True)


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
    stdout = "a" * (inv.MAX_NAME + 1) + "=1\nweb=x\n"
    assert inv.parse_check(ok(stdout)) == ({"web": "x"}, None, True)
    stdout = "web=" + "v" * (inv.MAX_VALUE + 1)
    assert inv.parse_check(ok(stdout)) == ({"web": "v" * inv.MAX_VALUE}, None, True)
    stdout = "y" * (inv.MAX_VALUE + 1)
    assert inv.parse_check(ok(stdout)) == ({"": "y" * inv.MAX_VALUE}, None, True)


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


def test_due_rules() -> None:
    every = timedelta(hours=6)
    read = inv.ReadState(asked_at=None, answered_at=T0, wanted_at=None)
    assert inv.is_due(None, now=T0, every=every, back_at=None)
    assert not inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=None)
    assert inv.is_due(read, now=T0 + every, every=every, back_at=None)
    # Back online since the last answer.
    back = T0 + timedelta(minutes=5)
    assert inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=back)
    assert not inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=T0)
    # Wanted again (Ask now, or after a job), once that time comes.
    wanted = inv.ReadState(asked_at=None, answered_at=T0, wanted_at=T0 + timedelta(minutes=2))
    assert not inv.is_due(wanted, now=T0 + timedelta(minutes=1), every=every, back_at=None)
    assert inv.is_due(wanted, now=T0 + timedelta(minutes=2), every=every, back_at=None)
    # Asked and waiting for the answer: not asked again until ANSWER_WAIT has passed.
    waiting = inv.ReadState(asked_at=T0 + timedelta(hours=7), answered_at=T0, wanted_at=None)
    assert not inv.is_due(
        waiting, now=T0 + timedelta(hours=7, minutes=1), every=every, back_at=None
    )
    assert inv.is_due(
        waiting, now=T0 + timedelta(hours=7) + inv.ANSWER_WAIT, every=every, back_at=None
    )
    never_answered = inv.ReadState(asked_at=T0, answered_at=None, wanted_at=None)
    assert not inv.is_due(never_answered, now=T0 + timedelta(minutes=1), every=every, back_at=None)
    assert inv.is_due(never_answered, now=T0 + inv.ANSWER_WAIT, every=every, back_at=None)
    # Asked, then answered: not waiting any more.
    answered = inv.ReadState(asked_at=T0, answered_at=T0 + timedelta(seconds=5), wanted_at=None)
    assert not inv.is_due(answered, now=T0 + timedelta(minutes=1), every=every, back_at=None)
    wanted_since = inv.ReadState(asked_at=T0, answered_at=T0, wanted_at=T0 + timedelta(minutes=1))
    assert inv.is_due(wanted_since, now=T0 + timedelta(minutes=1), every=every, back_at=None)


def test_a_want_is_met_only_by_an_ask_made_after_it() -> None:
    every = timedelta(hours=6)
    t1, t2, t3, t4 = (T0 + timedelta(minutes=m) for m in (1, 2, 3, 4))
    # Asked at T0, wanted at T1, then the answer to the older ask arrives at T2: still due.
    old_answer = inv.ReadState(asked_at=T0, answered_at=t2, wanted_at=t1)
    assert inv.is_due(old_answer, now=t2, every=every, back_at=None)
    # Asked again at T3: the want is met, so not due again because of it.
    asked_again = inv.ReadState(asked_at=t3, answered_at=t4, wanted_at=t1)
    assert not inv.is_due(asked_again, now=t4, every=every, back_at=None)
    asked_at_want = inv.ReadState(asked_at=t1, answered_at=t2, wanted_at=t1)
    assert not inv.is_due(asked_at_want, now=t2, every=every, back_at=None)
    # Waiting for an answer comes first, even when wanted.
    waiting = inv.ReadState(asked_at=T0, answered_at=None, wanted_at=t1)
    assert not inv.is_due(waiting, now=t2, every=every, back_at=None)


def test_a_want_is_asked_again_when_its_answer_is_lost() -> None:
    every = timedelta(hours=6)
    t1, t3 = T0 + timedelta(minutes=1), T0 + timedelta(minutes=3)
    # Wanted at T1 and asked at T3, but no answer came (a dropped return, a reconnect).
    lost = inv.ReadState(asked_at=t3, answered_at=T0, wanted_at=t1)
    assert not inv.is_due(lost, now=t3 + timedelta(minutes=1), every=every, back_at=None)
    assert inv.is_due(lost, now=t3 + inv.ANSWER_WAIT, every=every, back_at=None)
