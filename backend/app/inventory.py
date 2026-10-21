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
_SOFTWARE_PREFIXES = ("state.", "pkg.", "cmd.", "docker.", "file.", "archive.", "cp.", "service.")


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
    # A person can run cmd.run_all too, and it could change software. But it's what checks run,
    # so it counts as one of brine's reads, like pkg.list_pkgs.
    return fun.startswith(_SOFTWARE_PREFIXES) and fun not in (PACKAGES_FUN, CHECK_FUN)


def _put(entries: dict[str, str], name: str, value: str) -> bool:
    """Add one entry within the caps. True when it was skipped or cut."""
    if len(name) > MAX_NAME:
        return True
    entries[name] = value[:MAX_VALUE]
    return len(value) > MAX_VALUE


def parse_packages(data: object) -> tuple[dict[str, str], bool] | None:
    """``(entries, truncated)`` from a ``pkg.list_pkgs`` answer; None if it isn't one.

    The answer maps each package to its version, or to a list when several are installed.
    """
    if not isinstance(data, dict):
        return None
    entries: dict[str, str] = {}
    truncated = False
    for name, version in data.items():
        value = ", ".join(map(str, version)) if isinstance(version, list) else str(version)
        truncated |= _put(entries, str(name), value)
    return entries, truncated


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def parse_check(data: object) -> tuple[dict[str, str], str | None, bool]:
    """``(entries, error, truncated)`` from a check's ``cmd.run_all`` answer.

    Output where every line is ``name=value`` is one entry per line. Any other output is one
    entry named "". No output means the thing isn't there. A failing command is an error, so it
    isn't mistaken for an empty answer.
    """
    if not isinstance(data, dict):
        return {}, f"unexpected answer: {str(data)[:200]}", False
    retcode = data.get("retcode")
    stdout = str(data.get("stdout") or "")
    if retcode not in (0, None):
        message = _first_line(str(data.get("stderr") or "")) or _first_line(stdout)
        return {}, f"exit {retcode}: {message[:200]}" if message else f"exit {retcode}", False

    truncated = len(stdout) > MAX_TEXT
    lines = stdout[:MAX_TEXT].splitlines()
    if truncated and len(lines) > 1:
        # Leave out the line the cut went through, rather than keep half of it.
        lines.pop()
    lines = [line.strip() for line in lines if line.strip()]
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
    escaped command allows exactly that command. Each check gets its own ``cmd.run_all`` rule:
    two patterns in one ``args`` list would be the first and second argument of one call.
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
    if read.wanted_at is not None and read.wanted_at <= now and answered < read.wanted_at:
        return True
    return back_at is not None and answered < back_at
