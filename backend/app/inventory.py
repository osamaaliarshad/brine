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

# Caps on what one answer can add. Past them the answer is kept but marked truncated.
MAX_ENTRIES = 500  # entries from one check
MAX_TEXT = 64 * 1024  # characters of a check's output that are read
# Names longer than the database column are skipped: one would fail the whole write.
MAX_NAME = 255
# Longer values are cut, so history rows stay small.
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


def sources(settings: Settings) -> list[str]:
    """Everything brine reads from each minion: the packages, then each check."""
    return [PACKAGES, *settings.inventory.checks]


def key_of(source: str, name: str) -> str:
    """The key for one entry, such as ``@packages:bash``, or ``@rover-cli`` for a single value."""
    return f"@{source}:{name}" if name else f"@{source}"


def parse_key(key: str) -> tuple[str, str] | None:
    """``(source, name)`` from a key; None for anything else, such as a grain path."""
    if not key.startswith("@"):
        return None
    # Source names have no colon, so the first one ends it (package names may have more).
    source, _, name = key[1:].partition(":")
    return (source, name) if source else None


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


def _put(entries: dict[str, str], name: str, value: str) -> bool:
    """Add one entry within the caps, without control characters. True if skipped or cut."""
    name, value = _clean(name), _clean(value)
    if len(name) > MAX_NAME:
        return True
    entries[name] = value[:MAX_VALUE]
    return len(value) > MAX_VALUE


def parse_packages(data: object) -> tuple[dict[str, str], str | None, bool]:
    """``(entries, error, truncated)`` from a ``pkg.list_pkgs`` answer.

    The answer maps each package to its version, or to a list when several are installed. An
    empty list is an error, not "nothing installed": a locked or broken package database gives
    one, and a real system always has packages.
    """
    if not isinstance(data, dict):
        return {}, _unexpected(data), False
    if not data:
        return {}, "the package list was empty", False
    entries: dict[str, str] = {}
    truncated = False
    for name, version in data.items():
        # As in checks, a name with nothing in it is skipped.
        if not _clean(str(name)).strip():
            continue
        # Several versions are joined the way Salt writes them (pkg_resource.stringify).
        value = ",".join(map(str, version)) if isinstance(version, list) else str(version)
        truncated |= _put(entries, str(name), value)
    return entries, None, truncated


def parse_check(data: object) -> tuple[dict[str, str], str | None, bool]:
    """``(entries, error, truncated)`` from a check's ``cmd.run_all`` answer.

    Output where every line is ``name=value`` is one entry per line. Any other output is one
    entry named "". No output means the thing isn't there. A failing command is an error, so it
    isn't mistaken for an empty answer.
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
                truncated |= _put(entries, name.strip(), value.strip())
        return entries, None, truncated

    truncated |= _put(entries, "", "\n".join(lines))
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
    """A minion's reads: last asked, last answered, and when it's wanted again (Ask now, a job)."""

    asked_at: datetime | None
    answered_at: datetime | None
    wanted_at: datetime | None


def is_due(
    read: ReadState | None, *, now: datetime, every: timedelta, back_at: datetime | None
) -> bool:
    """Whether to ask a minion now. ``back_at`` is when it last came online."""
    if read is None:
        return True
    asked, answered = read.asked_at, read.answered_at
    # Asked and not answered since: wait a while for the answer before asking again.
    if asked is not None and (answered is None or asked > answered) and now - asked < ANSWER_WAIT:
        return False
    if answered is None or now - answered >= every:
        return True
    # A want (Ask now, a job) is met only by an ask made at or after it, and answered: not by a
    # late answer to an older ask, nor by an ask whose answer was lost (the wait above has
    # passed by now).
    wanted = read.wanted_at
    if (
        wanted is not None
        and wanted <= now
        and (asked is None or asked < wanted or answered < asked)
    ):
        return True
    return back_at is not None and answered < back_at
