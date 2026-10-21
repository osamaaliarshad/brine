"""Packages and checks: what each minion has installed, read from the minion, kept over time.

brine asks connected minions for ``pkg.list_pkgs`` (their package manager's own list) and for
each check in ``inventory.checks`` (a read-only command, run with ``cmd.run_all``). It asks every
``inventory.refresh_hours``, again after a person's job that could change software, when a minion
starts or comes back, and when someone clicks Ask now. The answers arrive on the event bus like
any job return; ``Ingest`` keeps the current entries and every change.

Nothing is installed on the master or the minions, and the minion stays the source of truth:
brine shows what each one said, and when.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import Settings

PACKAGES = "packages"
PACKAGES_FUN = "pkg.list_pkgs"
CHECK_FUN = "cmd.run_all"

# A minion asked and not answered after this long is asked again when it's due.
ANSWER_WAIT = timedelta(minutes=10)
# Read again this long after a person's job that could change software finishes.
AFTER_JOB = timedelta(seconds=60)
# brine assumes its clock and the master's (asks are timed by brine's, jobs by the master's)
# agree to within this, as NTP keeps them. An ask timed less than this after a job may have
# been sent before it, so its answer gets no credit. Less than AFTER_JOB, so the ask made for
# a job is never one of them.
CLOCK_MARGIN = timedelta(seconds=30)
# What brine's read finds is credited to the job before it only if brine asked CLOCK_MARGIN or
# more after the job, and within this long of it: the wait after it, one lost answer asked
# again, and slack for the sweep and the clocks. Later, too much else may have changed.
CREDIT_WINDOW = AFTER_JOB + ANSWER_WAIT + timedelta(minutes=2)
# Kept as an ask's job when no minion matched (salt-api started none), so brine waits
# ANSWER_WAIT as for any ask rather than asking again on every sweep. Salt's jids are digits,
# so no answer can match it.
NO_JOB = "none"
# System state: {source: why salt-api refused to ask for it}, for Settings and Issues.
REFUSED_STATE = "inventory_refused"

# Caps on how much of a check's answer is read. Past them the answer is kept but marked
# truncated: cut short, so some entries may be missing (and none are taken as gone).
MAX_ENTRIES = 500  # entries from one check
MAX_TEXT = 64 * 1024  # characters of a check's output that are read
# Longer names are ignored: one wouldn't fit the database column, and would fail the whole
# write. As such a name can never be stored, leaving it out doesn't make an answer truncated.
MAX_NAME = 255
# Longer values are cut, so history rows stay small. The entry is still there: not truncated.
MAX_VALUE = 4096

# Jobs in these modules can install, remove or change software.
_SOFTWARE_PREFIXES = (
    *("state.", "pkg.", "cmd.", "docker.", "file.", "archive.", "cp.", "service."),
    *("pip.", "snap.", "flatpak.", "npm."),
)
# C0 control characters but tab and newline. PostgreSQL text can't hold NUL (and
# /proc/device-tree/model ends in one); the rest only garble what's shown. Newlines stay: a
# check's single value is its lines joined by them.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f]")

# For version_key.
_EPOCH = re.compile(r"([0-9]+):(.*)", re.DOTALL)
_PACKAGE_PARTS = re.compile(r"[0-9]+|~|[^0-9~]+")
_PARTS = re.compile(r"[0-9]+|[^0-9]+")
# How each part ranks against another kind of part at the same place.
_TILDE, _END, _NUMBER, _TEXT = -2, -1, 0, 1


def sources(settings: Settings) -> list[str]:
    """Everything brine reads from each minion: the packages, then each check."""
    return [PACKAGES, *settings.inventory.checks]


def key_of(source: str, name: str) -> str:
    """The key for one entry, such as ``@packages:bash``, or ``@rover-cli`` for a single value."""
    return f"@{source}:{name}" if name else f"@{source}"


def is_key(key: str) -> bool:
    """Whether a column (or anything that may be a grain path) is a package's or check's key.
    Grain paths never start with ``@``. The key may still name nothing, such as ``@``."""
    return key.startswith("@")


def parse_key(key: str) -> tuple[str, str] | None:
    """``(source, name)`` from a key; None for anything else, such as a grain path."""
    if not is_key(key):
        return None
    # Source names have no colon, so the first one ends it (package names may have more).
    source, _, name = key[1:].partition(":")
    return (source, name) if source else None


def version_key(text: str, *, package: bool) -> tuple[int, list[tuple[int, int | str]]]:
    """Newer versions sort later: runs of digits as numbers (2.10 after 2.9), other text as it
    is. A package's version is compared close to how dpkg and rpm do, but not a full copy: an
    epoch (``1:``) first, and ``~`` before anything, even the end (1.0~rc1 before 1.0). A
    check's value is free text (``8080:80``, a time), so it gets neither rule."""
    epoch = 0
    if package and (match := _EPOCH.fullmatch(text)):
        epoch, text = int(match[1]), match[2]
    parts: list[tuple[int, int | str]] = []
    for part in (_PACKAGE_PARTS if package else _PARTS).findall(text):
        if package and part == "~":
            parts.append((_TILDE, ""))
        elif part.isascii() and part.isdigit():
            parts.append((_NUMBER, int(part)))
        else:
            parts.append((_TEXT, part))
    return epoch, [*parts, (_END, "")]


def configured_key(settings: Settings, key: str) -> tuple[str, str] | None:
    """``(source, name)`` of a package's or a configured check's key; None for anything else:
    a grain path, a check no longer configured, or ``@packages`` with no package named."""
    parsed = parse_key(key)
    if parsed is None or parsed[0] not in sources(settings) or parsed == (PACKAGES, ""):
        return None
    return parsed


def may_change_software(fun: str) -> bool:
    """Whether a job running ``fun`` could change what's installed, so worth reading again."""
    # pkg.list_pkgs is brine's own read. cmd.run_all counts: a person can install things with it,
    # and brine's own check jobs are told apart elsewhere, as its service user's housekeeping.
    return fun.startswith(_SOFTWARE_PREFIXES) and fun != PACKAGES_FUN


def _clean(text: str) -> str:
    return _CONTROL.sub("", text)


def _lines(text: str) -> Iterator[str]:
    """The lines of some output that have something in them, stripped and cleaned."""
    # Only "\n" ends a line; the cleaning removes the "\r" of a "\r\n". str.splitlines() would also
    # split on characters such as \x0b, \x1c and \u2028 inside a line.
    for raw in text.split("\n"):
        if line := _clean(raw).strip():
            yield line


def _unexpected(data: object) -> str:
    return f"unexpected answer: {_clean(str(data))[:200]}"


def _put(entries: dict[str, str], name: str, value: str) -> None:
    """Add one entry without control characters: ignored if its name is longer than MAX_NAME,
    its value cut to MAX_VALUE."""
    name, value = _clean(name), _clean(value)
    if len(name) <= MAX_NAME:
        entries[name] = value[:MAX_VALUE]


def parse_packages(data: object) -> tuple[dict[str, str], str | None, bool]:
    """``(entries, error, truncated)`` from a ``pkg.list_pkgs`` answer.

    The answer maps each package to its version, or to a list when several are installed. An
    empty list is an error, not "nothing installed": a locked or broken package database gives
    one, and a real system always has packages. The list is read whole, so it's never
    truncated.
    """
    if not isinstance(data, dict):
        return {}, _unexpected(data), False
    if not data:
        return {}, "the package list was empty", False
    entries: dict[str, str] = {}
    for name, version in data.items():
        # As in checks, a name with nothing in it is skipped.
        if not _clean(str(name)).strip():
            continue
        # Several versions are joined the way Salt writes them (pkg_resource.stringify).
        value = ",".join(map(str, version)) if isinstance(version, list) else str(version)
        _put(entries, str(name), value)
    return entries, None, False


def parse_check(data: object) -> tuple[dict[str, str], str | None, bool]:
    """``(entries, error, truncated)`` from a check's ``cmd.run_all`` answer.

    Output where every line is ``name=value`` is one entry per line. Any other output is one
    entry named "". No output means the thing isn't there. A failing command is an error, so it
    isn't mistaken for an empty answer. ``truncated``: the output was cut short (past MAX_TEXT
    or MAX_ENTRIES), so some entries may be missing.
    """
    if not isinstance(data, dict):
        return {}, _unexpected(data), False
    retcode = data.get("retcode")
    stdout = str(data.get("stdout") or "")
    if retcode not in (0, None):
        code = _clean(str(retcode))
        message = next(_lines(str(data.get("stderr") or "")), "") or next(_lines(stdout), "")
        return {}, f"exit {code}: {message[:200]}" if message else f"exit {code}", False

    truncated = len(stdout) > MAX_TEXT
    text = stdout
    if truncated:
        # Cut after the last whole line that fits, so no line is kept half. If no line with
        # anything in it fits whole, keep what fits of the long one (it's cut to MAX_VALUE).
        end = stdout.rfind("\n", 0, MAX_TEXT + 1)
        text = stdout[:end] if end > 0 else ""
        if not any(_lines(text)):
            text = stdout[:MAX_TEXT]
    lines = list(_lines(text))
    entries: dict[str, str] = {}
    if not lines:
        return entries, None, truncated

    if all("=" in line for line in lines):
        for line in lines:
            if len(entries) == MAX_ENTRIES:
                truncated = True
                break
            name, _, value = line.partition("=")
            # An empty name would collide with the single value's name "".
            if name.strip():
                _put(entries, name.strip(), value.strip())
        return entries, None, truncated

    _put(entries, "", "\n".join(lines))
    return entries, None, truncated


def check_named(settings: Settings, args: object) -> str | None:
    """Which configured check a ``cmd.run_all`` job was, from its arguments (``fun_args``)."""
    if not isinstance(args, list) or not args or not isinstance(args[0], str):
        return None
    for name, command in settings.inventory.checks.items():
        if args[0] == command:
            return name
    return None


def acl_lines(settings: Settings) -> str:
    """The ``external_auth`` entries brine's Salt account needs, as YAML.

    Salt matches each listed argument with ``re.match``, in order, so ``^...$`` around the
    escaped command pins each check's command. Each check gets its own ``cmd.run_all`` rule:
    two patterns in one ``args`` list would be the first and second argument of one call.

    Salt can't forbid other arguments or keyword arguments, though (``shell``, ``env``,
    ``runas``, ``cwd``), so an account that's allowed checks can in practice run commands.
    """
    lines = ["- '*':", f"  - {PACKAGES_FUN}"]
    for command in settings.inventory.checks.values():
        pattern = f"^{re.escape(command)}$"
        # In single quotes YAML keeps backslashes as they are; a quote is written twice.
        quoted = "'" + pattern.replace("'", "''") + "'"
        lines += [f"  - {CHECK_FUN}:", "      args:", f"        - {quoted}"]
    return "\n".join(lines) + "\n"


@dataclass
class ReadState:
    """A minion's reads of one source, as ``InventoryRead`` keeps them."""

    asked_jid: str | None  # brine's ask still out, if any
    asked_at: datetime | None  # by brine's clock
    answered_at: datetime | None  # the last answer, by the master's clock
    wanted_at: datetime | None  # read again from then (a start, a job)


def is_due(
    read: ReadState | None, *, now: datetime, every: timedelta, back_at: datetime | None
) -> bool:
    """Whether to ask a minion now. ``back_at`` is when it last came online."""
    if read is None:
        return True
    # brine's ask is out: give the answer a while before asking again. Only brine's own clock is
    # compared here.
    if (
        read.asked_jid is not None
        and read.asked_at is not None
        and now - read.asked_at < ANSWER_WAIT
    ):
        return False
    answered = read.answered_at
    if answered is None or now - answered >= every:
        return True
    # A want stays until brine's answer clears it, so a lost answer is asked again.
    if read.wanted_at is not None and read.wanted_at <= now:
        return True
    return back_at is not None and answered < back_at
