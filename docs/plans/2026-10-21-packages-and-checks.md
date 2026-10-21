# Packages and Checks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track every minion's installed packages (and configured "checks" for software outside
the package manager) over time, with the minion as the source of truth, shown next to grains.

**Architecture:** A background sweep (like catch-up runs) asks connected minions for
`pkg.list_pkgs` and each configured check (`cmd.run_all <command>`) when they're due. Answers
arrive as job returns on the event bus; the collector hands them to `Ingest`, which keeps current
entries, per-source read times and a change history, attributing changes to the person's job
that preceded the read. The API serves an explorer view, changes, a per-minion view and fleet
columns (`@source:name` keys); the frontend extends the Grains explorer, fleet columns and minion
page. Design: `docs/plans/2026-10-21-packages-and-checks-design.md`.

**Tech Stack:** FastAPI, SQLAlchemy 2 async + Alembic, pytest; React 19 + TanStack Query +
Vitest; the Docker demo fleet for end to end.

**Conventions (read before starting):**
- Backend commands run from `backend/`: `uv run pytest -q`, `uv run ruff check .`,
  `uv run ruff format .`, `uv run mypy`. Frontend from `frontend/`: `npm test`, `npm run lint`,
  `npm run typecheck`, `npm run build`.
- Every DB write goes through `app/ingest.py` under `self._lock`; methods return `Changes`.
- Comments and UI text are plain English, short sentences, no jargon; match nearby code.
- Before every commit run the three scans from the session rules (sensitive paths, former-employer
  names, secrets). Commit messages end with the `Co-Authored-By` line.
- Key format used everywhere: a grain is its path (`app_version`, `a:b`); an inventory entry is
  `@<source>:<name>` (`@packages:rover-agent`, `@containers:web`), or `@<source>` for a check
  that prints a single value (name `""`). Grain names never start with `@`.

---

### Task 1: Config: `inventory` section

**Files:**
- Modify: `backend/app/config.py` (new `InventoryConfig`, field on `Settings`)
- Test: `backend/tests/test_config.py`

**Step 1: Write the failing tests**

```python
def test_inventory_defaults_and_checks() -> None:
    s = parse_config(MINIMAL, {})
    assert s.inventory.refresh_hours == 6 and s.inventory.checks == {}
    s = parse_config(
        MINIMAL + "inventory: {refresh_hours: 1, checks: {containers: 'podman ps', rover-cli: 'x'}}\n",
        {},
    )
    assert s.inventory.checks["containers"] == "podman ps"


@pytest.mark.parametrize("name", ["packages", "Has Space", "", "a:b", "@x"])
def test_inventory_check_names_are_checked(name: str) -> None:
    with pytest.raises(ConfigError):
        parse_config(MINIMAL + f"inventory: {{checks: {{'{name}': 'true'}}}}\n", {})
```

(Use the existing minimal-config constant and error type in `test_config.py`; check their names
with `grep -n "^MINIMAL\|ConfigError\|raises" tests/test_config.py` and adapt.)

**Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_config.py -k inventory -v` → FAIL (`inventory` unknown).

**Step 3: Implement**

In `app/config.py`, next to `RetentionConfig`:

```python
CHECK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class InventoryConfig(_Strict):
    """Packages and checks: what brine reads from each minion and keeps over time."""

    # How often each connected minion is read again (also after people's jobs and on Ask now).
    refresh_hours: float = Field(default=6, gt=0)
    # name -> a read-only shell command run with cmd.run_all. `name=value` lines become one
    # entry each; any other output is one value. Print nothing when the thing isn't there.
    checks: dict[str, str] = Field(default_factory=dict)

    @field_validator("checks")
    @classmethod
    def _names(cls, checks: dict[str, str]) -> dict[str, str]:
        for name, command in checks.items():
            if name == "packages" or not CHECK_NAME.match(name):
                raise ValueError(
                    f"check name {name!r}: use lowercase letters, digits, - and _ "
                    "(and not 'packages')"
                )
            if not command.strip():
                raise ValueError(f"check {name!r} has no command")
        return checks
```

Add `inventory: InventoryConfig = Field(default_factory=InventoryConfig)` to `Settings`
(match how `retention` is declared). Import `re`/`field_validator` if not already.

**Step 4:** `uv run pytest tests/test_config.py -v` → PASS.

**Step 5: Commit** `git add -A backend && git commit -m "Config: inventory refresh and checks"`

---

### Task 2: Models and migration

**Files:**
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/<generated>_add_inventory.py`
- Test: `backend/tests/test_db.py` (existing `test_migrations_create_schema_matching_models`)

**Step 1: Add the models** (after `GrainsSnapshot`; add them to the module docstring list):

```python
class InventoryRead(Base):
    """One minion's latest read of one source ("packages" or a check's name)."""

    __tablename__ = "inventory_reads"

    minion_id: Mapped[str] = mapped_column(
        ForeignKey("minions.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    asked_at: Mapped[datetime | None]  # brine last asked
    answered_at: Mapped[datetime | None]  # last answer, good or failed
    read_at: Mapped[datetime | None]  # last good answer: entries are as of this
    first_read_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)  # the last answer's error, if it failed
    truncated: Mapped[bool] = mapped_column(default=False)
    # Read again at/after this (a minion start, a person's job finishing).
    wanted_at: Mapped[datetime | None]
    # The person's job that finished before the next read: changes found then are credited to it.
    after_jid: Mapped[str | None] = mapped_column(String(32))
    after_user: Mapped[str | None] = mapped_column(String(255))
    after_at: Mapped[datetime | None]


class InventoryItem(Base):
    """What a minion said it has: a package and its version, or a check's entry."""

    __tablename__ = "inventory_items"
    __table_args__ = (Index("ix_inventory_items_source_name", "source", "name"),)

    minion_id: Mapped[str] = mapped_column(
        ForeignKey("minions.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    since: Mapped[datetime]  # first read with this value


class InventoryChange(Base):
    __tablename__ = "inventory_changes"
    __table_args__ = (
        Index("ix_inventory_changes_source_name_at", "source", "name", "at"),
        Index("ix_inventory_changes_minion_at", "minion_id", "at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    minion_id: Mapped[str] = mapped_column(ForeignKey("minions.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    old: Mapped[str | None] = mapped_column(Text)  # None: wasn't there
    new: Mapped[str | None] = mapped_column(Text)  # None: gone
    at: Mapped[datetime]  # the read that found it
    since: Mapped[datetime | None]  # the read before: it changed between the two
    jid: Mapped[str | None] = mapped_column(String(32))  # credited job, if any
    user: Mapped[str | None] = mapped_column(String(255))
```

**Step 2: Generate the migration**

Run: `uv run alembic revision --autogenerate -m "add inventory"` (uses a throwaway SQLite URL
the way the earlier migrations were made; if autogenerate needs a DB URL, check
`migrations/env.py` and how `2026_10_20_1730-9c7795520cec_add_pending_runs.py` was produced).
Review the file: three `create_table`s and three indexes, `downgrade` drops them.

**Step 3:** `uv run pytest tests/test_db.py -v` → PASS (schema from migrations matches models).

**Step 4: Commit** `git commit -m "Inventory tables: reads, items and changes"`

---

### Task 3: Parsing and helpers (pure functions)

**Files:**
- Create: `backend/app/inventory.py` (this task: the pure part only)
- Test: `backend/tests/test_inventory.py`

**Step 1: Write the failing tests**

```python
"""Packages and checks: parsing, due rules, the sweep, ingest and the API."""

from datetime import timedelta

import pytest

from app import inventory as inv
from app.config import parse_config
from tests.conftest import T0


def test_packages_are_name_to_version() -> None:
    assert inv.parse_packages({"bash": "5.2", "kernel": ["6.1", "6.2"]}) == (
        {"bash": "5.2", "kernel": "6.1, 6.2"},
        False,
    )
    assert inv.parse_packages("not a dict") is None


@pytest.mark.parametrize(
    ("stdout", "items"),
    [
        ("web=ghcr.io/acme/web:1.4\ndb=postgres:16\n", {"web": "ghcr.io/acme/web:1.4", "db": "postgres:16"}),
        ("rover-cli 1.2.0\n", {"": "rover-cli 1.2.0"}),
        ("", {}),
        ("  \n", {}),
        ("a=1\nplain line\n", {"": "a=1\nplain line"}),  # mixed: one value
    ],
)
def test_check_output(stdout: str, items: dict[str, str]) -> None:
    assert inv.parse_check({"retcode": 0, "stdout": stdout, "stderr": ""}) == (items, None, False)


def test_a_failing_check_is_an_error_not_an_empty_answer() -> None:
    items, error, _ = inv.parse_check({"retcode": 127, "stdout": "", "stderr": "sh: podman: not found\nmore"})
    assert items == {} and error == "exit 127: sh: podman: not found"


def test_check_output_is_capped() -> None:
    stdout = "\n".join(f"c{i}=v" for i in range(inv.MAX_ENTRIES + 5))
    items, _, truncated = inv.parse_check({"retcode": 0, "stdout": stdout, "stderr": ""})
    assert len(items) == inv.MAX_ENTRIES and truncated


def test_keys_round_trip() -> None:
    assert inv.parse_key("@packages:rover-agent") == ("packages", "rover-agent")
    assert inv.parse_key("@rover-cli") == ("rover-cli", "")
    assert inv.parse_key("app_version") is None
    assert inv.key_of("packages", "x") == "@packages:x" and inv.key_of("rover-cli", "") == "@rover-cli"


def test_which_jobs_can_change_software() -> None:
    assert inv.may_change_software("state.apply") and inv.may_change_software("pkg.install")
    assert inv.may_change_software("cmd.run")
    assert not inv.may_change_software("test.ping") and not inv.may_change_software("pkg.list_pkgs")


def test_acl_lines_are_exact() -> None:
    s = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "inventory: {checks: {rover-cli: '/opt/rover/bin/rover-cli --version || true'}}\n",
        {},
    )
    text = inv.acl_lines(s)
    assert "- pkg.list_pkgs" in text
    assert r"'^/opt/rover/bin/rover\-cli\ \-\-version\ \|\|\ true$'" in text


def test_due_rules() -> None:
    every = timedelta(hours=6)
    read = inv.ReadState(asked_at=None, answered_at=T0, wanted_at=None)
    assert inv.is_due(None, now=T0, every=every, back_at=None)  # never read
    assert not inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=None)
    assert inv.is_due(read, now=T0 + every, every=every, back_at=None)  # refresh
    assert inv.is_due(read, now=T0 + timedelta(hours=1), every=every, back_at=T0 + timedelta(minutes=5))
    wanted = inv.ReadState(asked_at=None, answered_at=T0, wanted_at=T0 + timedelta(minutes=2))
    assert not inv.is_due(wanted, now=T0 + timedelta(minutes=1), every=every, back_at=None)
    assert inv.is_due(wanted, now=T0 + timedelta(minutes=2), every=every, back_at=None)
    # Asked and waiting for the answer: not again until ANSWER_WAIT has passed.
    waiting = inv.ReadState(asked_at=T0 + timedelta(hours=7), answered_at=T0, wanted_at=None)
    assert not inv.is_due(waiting, now=T0 + timedelta(hours=7, minutes=1), every=every, back_at=None)
    assert inv.is_due(waiting, now=T0 + timedelta(hours=7) + inv.ANSWER_WAIT, every=every, back_at=None)
```

**Step 2:** `uv run pytest tests/test_inventory.py -v` → FAIL (no module).

**Step 3: Implement** `app/inventory.py`:

```python
"""Packages and checks: what each minion has installed, read from the minion, kept over time.

brine asks connected minions for `pkg.list_pkgs` (their package manager's own list) and for each
check in `inventory.checks` (a read-only command, run with `cmd.run_all`). It asks every
`inventory.refresh_hours`, again after a person's job that could change software, when a minion
starts or comes back, and when someone clicks Ask now. The answers arrive on the event bus like
any job return; `Ingest` keeps the current entries and every change.

Nothing is installed on the master or the minions, and the minion stays the source of truth:
brine shows what each one said, and when.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.config import Settings

PACKAGES = "packages"
PACKAGES_FUN = "pkg.list_pkgs"
CHECK_FUN = "cmd.run_all"
# A minion that was asked and hasn't answered after this long is asked again when due.
ANSWER_WAIT = timedelta(minutes=10)
# Read again this long after a person's job that could change software finishes on a minion.
AFTER_JOB = timedelta(seconds=60)
# Checks: at most this many entries and this much text, so one noisy command can't flood brine.
MAX_ENTRIES = 500
MAX_TEXT = 64 * 1024
# Jobs whose function starts with one of these may install, remove or start software.
_CHANGING = ("state.", "pkg.", "cmd.", "docker.", "file.", "archive.", "cp.", "service.")


def sources(settings: Settings) -> list[str]:
    return [PACKAGES, *settings.inventory.checks]


def key_of(source: str, name: str) -> str:
    return f"@{source}:{name}" if name else f"@{source}"


def parse_key(key: str) -> tuple[str, str] | None:
    """`@packages:x` -> ("packages", "x"); `@check` -> ("check", ""); a grain -> None."""
    if not key.startswith("@") or len(key) < 2:
        return None
    source, _, name = key[1:].partition(":")
    return source, name


def may_change_software(fun: str) -> bool:
    return fun != PACKAGES_FUN and fun != CHECK_FUN and fun.startswith(_CHANGING)


def parse_packages(data: Any) -> tuple[dict[str, str], bool] | None:
    """A `pkg.list_pkgs` return: {name: version}; several installed versions are joined."""
    if not isinstance(data, dict):
        return None
    items = {
        str(name): ", ".join(map(str, v)) if isinstance(v, list) else str(v)
        for name, v in data.items()
    }
    return items, False


def parse_check(data: Any) -> tuple[dict[str, str], str | None, bool]:
    """A `cmd.run_all` return -> (entries, error, truncated)."""
    if not isinstance(data, dict):
        return {}, f"unexpected answer: {str(data)[:200]}", False
    retcode = data.get("retcode")
    if retcode not in (0, None):
        first = (str(data.get("stderr") or data.get("stdout") or "").strip().splitlines() or [""])[0]
        return {}, f"exit {retcode}: {first[:200]}".rstrip(": "), False
    text = str(data.get("stdout") or "")
    truncated = len(text) > MAX_TEXT
    lines = [line.strip() for line in text[:MAX_TEXT].splitlines() if line.strip()]
    if not lines:
        return {}, None, truncated
    if all("=" in line for line in lines):
        items: dict[str, str] = {}
        for line in lines:
            if len(items) >= MAX_ENTRIES:
                return items, None, True
            name, _, value = line.partition("=")
            items[name.strip()] = value.strip()
        return items, None, truncated
    return {"": "\n".join(lines)}, None, truncated


def check_named(settings: Settings, args: Any) -> str | None:
    """Which configured check a `cmd.run_all` call was, from its arguments."""
    if not isinstance(args, list) or not args or not isinstance(args[0], str):
        return None
    for name, command in settings.inventory.checks.items():
        if args[0] == command:
            return name
    return None


def acl_lines(settings: Settings) -> str:
    """The external_auth entries brine's account needs for packages and checks."""
    lines = ["- '*':", "  - pkg.list_pkgs"]
    if settings.inventory.checks:
        lines += ["  - cmd.run_all:", "      args:"]
        lines += [f"        - '^{re.escape(c)}$'" for c in settings.inventory.checks.values()]
    return "\n".join(lines)


@dataclass
class ReadState:
    asked_at: datetime | None
    answered_at: datetime | None
    wanted_at: datetime | None


def is_due(
    read: ReadState | None, *, now: datetime, every: timedelta, back_at: datetime | None
) -> bool:
    """Should this minion be asked for this source now? `back_at`: when it last came online."""
    if read is None:
        return True
    answered = read.answered_at
    if read.asked_at is not None and (answered is None or read.asked_at > answered):
        if now - read.asked_at < ANSWER_WAIT:
            return False  # waiting for the answer
    if answered is None or now - answered >= every:
        return True
    if read.wanted_at is not None and read.wanted_at <= now and answered < read.wanted_at:
        return True
    return back_at is not None and answered < back_at
```

Note the YAML in `acl_lines`: `re.escape` turns spaces into `\ `; inside single quotes YAML keeps
backslashes as they are, which is what Salt's regex needs.

**Step 4:** `uv run pytest tests/test_inventory.py -v` → PASS. Run `uv run mypy` and
`uv run ruff check .` too.

**Step 5: Commit** `git commit -m "Inventory: parsing, keys and due rules"`

---

### Task 4: Ingest: reads, failures, asks, attribution, retention

**Files:**
- Modify: `backend/app/ingest.py`
- Test: `backend/tests/test_ingest.py` (new section at the end, `# --- inventory ---`)

**Step 1: Write the failing tests**

```python
async def items(sessions: Sessions, mid: str, source: str = "packages") -> dict[str, str]:
    async with sessions() as s:
        rows = await s.scalars(select(InventoryItem).filter_by(minion_id=mid, source=source))
        return {r.name: r.value for r in rows}


async def changes_of(sessions: Sessions, mid: str) -> list[InventoryChange]:
    async with sessions() as s:
        q = select(InventoryChange).filter_by(minion_id=mid).order_by(InventoryChange.id)
        return list((await s.scalars(q)).all())


async def test_first_read_records_without_changes(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0)
    assert await items(sessions, "a") == {"bash": "5.2", "agent": "2.3.0"}
    assert await changes_of(sessions, "a") == []  # "already there when brine first looked"


async def test_later_reads_record_each_change(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"bash": "5.2", "agent": "2.3.0"}, at=T0)
    later = T0 + timedelta(hours=6)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1", "curl": "8"}, at=later)
    got = {(c.name, c.old, c.new) for c in await changes_of(sessions, "a")}
    assert got == {("agent", "2.3.0", "2.4.1"), ("curl", None, "8"), ("bash", "5.2", None)}
    assert all(c.since == T0 and c.jid is None for c in await changes_of(sessions, "a"))


async def test_changes_after_a_job_are_credited_to_it(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    job_at = T0 + timedelta(hours=1)
    await ingest.inventory_job_done("a", jid="J1", user="alice@example.com", at=job_at)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=job_at + timedelta(minutes=1))
    (change,) = await changes_of(sessions, "a")
    assert (change.jid, change.user) == ("J1", "alice@example.com")
    # The credit is used up: the next change isn't the job's.
    await ingest.inventory_read("a", "packages", {"agent": "2.5.0"}, at=T0 + timedelta(hours=8))
    assert (await changes_of(sessions, "a"))[-1].jid is None


async def test_late_answers_are_ignored(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + timedelta(hours=1))
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    assert await items(sessions, "a") == {"agent": "2.4.1"}


async def test_a_failed_read_keeps_the_last_good_one(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_failed("a", "packages", "dpkg database locked", at=T0 + timedelta(hours=6))
    assert await items(sessions, "a") == {"agent": "2.3.0"}
    async with sessions() as s:
        read = await s.get(InventoryRead, ("a", "packages"))
        assert read is not None
        assert read.error == "dpkg database locked" and read.read_at == T0
        assert read.answered_at == T0 + timedelta(hours=6)


async def test_old_changes_are_pruned(ingest: Ingest, sessions: Sessions) -> None:
    await ingest.inventory_read("a", "packages", {"agent": "2.3.0"}, at=T0)
    await ingest.inventory_read("a", "packages", {"agent": "2.4.1"}, at=T0 + timedelta(days=1))
    deleted = await ingest.prune(history_before=T0 + timedelta(days=2))
    assert deleted["inventory_changes"] == 1
    assert await items(sessions, "a") == {"agent": "2.4.1"}  # current entries stay
```

(Check `prune`'s keyword arguments with `grep -n "async def prune" -A 8 app/ingest.py` and pass
the other two as `None` if they're required.)

**Step 2:** `uv run pytest tests/test_ingest.py -k "read or credited or late or failed or pruned" -v` → FAIL.

**Step 3: Implement** in `app/ingest.py` (import the three models; new section after grains):

```python
    # --- packages and checks --------------------------------------------------------------

    async def _read_row(self, s: AsyncSession, mid: str, source: str) -> InventoryRead:
        await self._get_or_create(s, mid, "accepted")
        read = await s.get(InventoryRead, (mid, source))
        if read is None:
            read = InventoryRead(minion_id=mid, source=source)
            s.add(read)
        return read

    async def inventory_asked(self, mids: Iterable[str], source: str, *, at: datetime) -> None:
        async with self._lock, self._sessions() as s, s.begin():
            for mid in mids:
                (await self._read_row(s, mid, source)).asked_at = at

    async def inventory_wanted(self, mid: str, *, at: datetime) -> None:
        """Read this minion again from `at` on (it started)."""
        async with self._lock, self._sessions() as s, s.begin():
            for read in await s.scalars(select(InventoryRead).filter_by(minion_id=mid)):
                read.wanted_at = at

    async def inventory_job_done(self, mid: str, *, jid: str, user: str | None, at: datetime) -> None:
        """A person's job that may change software finished on `mid`: read it again shortly,
        and credit what changed to that job."""
        async with self._lock, self._sessions() as s, s.begin():
            for read in await s.scalars(select(InventoryRead).filter_by(minion_id=mid)):
                read.wanted_at = at + AFTER_JOB
                read.after_jid, read.after_user, read.after_at = jid, user, at

    async def inventory_read(
        self, mid: str, source: str, entries: dict[str, str], *, at: datetime, truncated: bool = False
    ) -> Changes:
        """A good answer: these are all the entries `mid` has for `source`, as of `at`."""
        async with self._lock, self._sessions() as s, s.begin():
            read = await self._read_row(s, mid, source)
            if read.read_at is not None and at <= read.read_at:
                return Changes()  # an older answer arriving late, or a duplicate
            first = read.first_read_at is None
            credited = read.after_at is not None and read.after_at <= at
            jid, user = (read.after_jid, read.after_user) if credited else (None, None)
            current = {
                i.name: i
                for i in await s.scalars(select(InventoryItem).filter_by(minion_id=mid, source=source))
            }
            moved = False

            def change(name: str, old: str | None, new: str | None) -> None:
                nonlocal moved
                moved = True
                if not first:
                    s.add(InventoryChange(
                        minion_id=mid, source=source, name=name, old=old, new=new,
                        at=at, since=read.read_at, jid=jid, user=user,
                    ))

            for name, value in entries.items():
                item = current.pop(name, None)
                if item is None:
                    s.add(InventoryItem(minion_id=mid, source=source, name=name, value=value, since=at))
                    change(name, None, value)
                elif item.value != value:
                    change(name, item.value, value)
                    item.value, item.since = value, at
            for name, item in current.items():
                await s.delete(item)
                change(name, item.value, None)
            read.read_at = read.answered_at = at
            read.first_read_at = read.first_read_at or at
            read.error, read.truncated = None, truncated
            if credited:
                read.after_jid = read.after_user = read.after_at = None
            if read.wanted_at is not None and read.wanted_at <= at:
                read.wanted_at = None
        return Changes(fleet=moved, minions={mid})

    async def inventory_failed(self, mid: str, source: str, error: str, *, at: datetime) -> Changes:
        """The minion answered, but couldn't say: keep the last good entries."""
        async with self._lock, self._sessions() as s, s.begin():
            read = await self._read_row(s, mid, source)
            if read.answered_at is not None and at <= read.answered_at:
                return Changes()
            read.answered_at, read.error = at, error
            if read.wanted_at is not None and read.wanted_at <= at:
                read.wanted_at = None
        return Changes(minions={mid})
```

Format the long `s.add(InventoryChange(...))` call with ruff. Import `AFTER_JOB` from
`app.inventory` **inside** ingest would create an import cycle if `app.inventory` ever imports
ingest; it doesn't (it imports only config), so a top-level import is fine.

In `prune`, inside `if history_before is not None:` add:

```python
                await drop(
                    s,
                    "inventory_changes",
                    delete(InventoryChange).where(InventoryChange.at < history_before),
                )
```

**Step 4:** `uv run pytest tests/test_ingest.py -v` → PASS; `uv run mypy`.

**Step 5: Commit** `git commit -m "Ingest: package and check reads, changes credited to jobs"`

---

### Task 5: Collector: answers in, reads wanted after jobs and starts

**Files:**
- Modify: `backend/app/salt/collector.py` (`handle`, the `_JOB_RET` branch and `_MINION_START`)
- Test: `backend/tests/test_collector.py`

**Step 1: Write the failing tests** (use the file's `ev()`, `FakeSaltApi`, `make_collector`;
settings there come from a `settings(**presence)` helper: extend it, or build a collector with
`parse_config(... "inventory: {checks: {rover-cli: 'rover-cli --version'}}")`):

```python
async def test_package_and_check_answers_are_stored(make_collector: Any, sessions: Sessions) -> None:
    collector = make_collector(FakeSaltApi([]))  # with the rover-cli check configured
    await collector.handle(ev("salt/job/1/ret/rover-01", id="rover-01", fun="pkg.list_pkgs",
                              fun_args=[], user="brine", success=True, retcode=0,
                              **{"return": {"rover-agent": "2.4.1"}}))
    await collector.handle(ev("salt/job/2/ret/rover-01", id="rover-01", fun="cmd.run_all",
                              fun_args=["rover-cli --version"], user="brine", success=True,
                              **{"return": {"retcode": 0, "stdout": "rover-cli 1.2.0", "stderr": ""}}))
    async with sessions() as s:
        got = {(i.source, i.name, i.value) for i in await s.scalars(select(InventoryItem))}
    assert got == {("packages", "rover-agent", "2.4.1"), ("rover-cli", "", "rover-cli 1.2.0")}


async def test_other_cmd_run_all_calls_are_not_checks(...) -> None:
    # fun_args ["echo hi"] (not a configured check): nothing stored
    ...


async def test_a_persons_state_run_asks_for_a_reread(...) -> None:
    # seed a read for rover-01, then handle a state.apply return with user "alice@example.com"
    # -> InventoryRead.wanted_at == event time + AFTER_JOB and after_jid == the jid
    ...


async def test_brines_own_calls_and_read_only_jobs_dont(...) -> None:
    # grains.items by "brine", test.ping by a person -> wanted_at stays None
    ...


async def test_a_minion_start_asks_for_a_reread(...) -> None:
    # salt/minion/rover-01/start -> wanted_at set
    ...
```

Fill in the elided tests in the same style (each 6–10 lines).

**Step 2:** run them → FAIL.

**Step 3: Implement** in `Collector.handle`, in the `_JOB_RET` branch, after `changes = await
self.ingest.job_return(...)`:

```python
            mid = str(d.get("id") or m["mid"])
            fun = str(d.get("fun", ""))
            changes.merge(await self._inventory_answer(mid, fun, d, at))
            user = actor_of(d.get("metadata")) or d.get("user")
            if not self.ingest.is_housekeeping(user, fun) and inventory.may_change_software(fun):
                await self.ingest.inventory_job_done(mid, jid=m["jid"], user=user, at=at)
```

(compute `mid`/`user` once and reuse them in the `job_return` call above), and add:

```python
    async def _inventory_answer(self, mid: str, fun: str, d: dict[str, Any], at: datetime) -> Changes:
        """A package list or a configured check's output, from brine or anyone else."""
        data, args = d.get("return"), d.get("fun_args") or []
        if fun == inventory.PACKAGES_FUN and not args and d.get("success") is not False:
            parsed = inventory.parse_packages(data)
            if parsed is None:
                return await self.ingest.inventory_failed(mid, inventory.PACKAGES, str(data)[:200], at=at)
            return await self.ingest.inventory_read(mid, inventory.PACKAGES, parsed[0], at=at)
        if fun == inventory.CHECK_FUN and (name := inventory.check_named(self.settings, args)):
            entries, error, truncated = inventory.parse_check(data)
            if error:
                return await self.ingest.inventory_failed(mid, name, error, at=at)
            return await self.ingest.inventory_read(mid, name, entries, at=at, truncated=truncated)
        return Changes()
```

In the `_MINION_START` branch add `await self.ingest.inventory_wanted(m["mid"], at=now)`.
Import: `from app import inventory`.

**Step 4:** `uv run pytest tests/test_collector.py -v` → PASS.

**Step 5: Commit** `git commit -m "Collector: store package and check answers; re-read after jobs and starts"`

---

### Task 6: The sweep and Ask now

**Files:**
- Modify: `backend/app/inventory.py` (add `sweep`, `ask`, `run_forever`, refused state)
- Modify: `backend/app/main.py` (start it with the other background tasks)
- Modify: `backend/tests/test_commands.py` (`FakeSalt.local_async`)
- Test: `backend/tests/test_inventory.py`

**Step 1: Give `FakeSalt` a `local_async`**:

```python
    async def local_async(self, tgt: str, fun: str, **kwargs: Any) -> str | None:
        self.calls.append(("local_async", fun, {"tgt": tgt, **kwargs}))
        if fun in self.forbidden:
            raise SaltApiForbidden(f"brine's Salt account isn't allowed to run {fun}", 403)
        return "20261021000000000001"

    def asked(self, fun: str) -> list[str]:
        """Minions asked for `fun` by brine itself, in order."""
        return [m for k, f, kw in self.calls if k == "local_async" and f == fun for m in kw["tgt"].split(",")]
```

**Step 2: Write the failing tests** (in `test_inventory.py`; reuse `make_api` from
`test_commands.py`: rover-01, rover-02, dock-01 online, rover-03 offline):

```python
def sweep(api: Api, now: datetime | None = None) -> None:
    api.seed(inv.sweep, runtime(api), now or datetime.now(UTC))


def test_connected_minions_are_read_once_until_due(admin) -> None:
    api, salt = admin
    sweep(api)
    assert sorted(salt.asked("pkg.list_pkgs")) == ["dock-01", "rover-01", "rover-02"]
    sweep(api)  # waiting for answers: not again
    assert len(salt.asked("pkg.list_pkgs")) == 3


def test_checks_are_asked_with_their_exact_command(tmp_path) -> None:
    # make_api with inventory.checks {rover-cli: 'rover-cli --version'} (add an optional
    # `extra_config` parameter to make_api for this) -> a cmd.run_all call with
    # arg == ['rover-cli --version'] and tgt_type == 'list'
    ...


def test_a_refused_source_is_remembered_and_cleared(admin) -> None:
    api, salt = admin
    salt.forbidden.add("pkg.list_pkgs")
    sweep(api)
    refused = api.seed(runtime(api).ingest.get_state, inv.REFUSED_STATE)
    assert "pkg.list_pkgs" in refused["packages"]
    salt.forbidden.clear()
    sweep(api, datetime.now(UTC) + inv.ANSWER_WAIT)
    assert api.seed(runtime(api).ingest.get_state, inv.REFUSED_STATE) == {}


def test_ask_now_reads_online_minions_and_is_throttled(admin) -> None:
    api, salt = admin
    post = lambda body: api.client.post("/api/inventory/ask", json=body, headers=CSRF)
    assert sorted(post({}).json()["asked"]) == ["dock-01", "rover-01", "rover-02"]
    assert post({}).status_code == 429
    assert post({"minion": "rover-01"}).json()["asked"] == ["rover-01"]
    assert post({"minion": "rover-03"}).json()["asked"] == []  # offline: not asked
```

(The Ask now API lands in Task 7; write this test now and expect it to pass after Task 7.)

**Step 3: Implement** (append to `app/inventory.py`):

```python
REFUSED_STATE = "inventory_refused"  # {source: why salt-api refused to ask for it}
SWEEP_SECONDS = 15
# One sweep asks at most this many minions per source; the rest follow 15 seconds later.
BATCH = 200
ASK_ALL_EVERY = 60.0  # Ask now for the whole fleet: at most once a minute
ASK_ONE_EVERY = 10.0


async def ask(runtime: Runtime, source: str, mids: list[str], now: datetime) -> bool:
    """Ask these minions for one source. False if salt-api refused (recorded for Settings)."""
    if not mids:
        return True
    if source == PACKAGES:
        call = runtime.client.local_async(",".join(mids), PACKAGES_FUN, tgt_type="list")
    else:
        command = runtime.settings.inventory.checks[source]
        call = runtime.client.local_async(",".join(mids), CHECK_FUN, arg=[command], tgt_type="list")
    try:
        await call
    except SaltApiForbidden as exc:
        await runtime.ingest.set_state_entry(REFUSED_STATE, source, str(exc))
        return False
    except SaltApiError as exc:
        log.warning("asking for %s failed: %s", source, exc)
        return False
    await runtime.ingest.set_state_entry(REFUSED_STATE, source, None)
    await runtime.ingest.inventory_asked(mids, source, at=now)
    return True


async def online(runtime: Runtime, now: datetime, only: str | None = None) -> list[str]:
    """Accepted minions a fresh presence check says are connected."""
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    async with runtime.sessions() as s:
        presence = await presence_info(s)
        if presence.checked_at is None or now - presence.checked_at > stale_after:
            return []
        q = select(Minion.id).where(Minion.connected.is_(True), Minion.key_state == "accepted")
        if only is not None:
            q = q.where(Minion.id == only)
        return list((await s.scalars(q.order_by(Minion.id))).all())


async def sweep(runtime: Runtime, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    mids = await online(runtime, now)
    if not mids:
        return
    every = timedelta(hours=runtime.settings.inventory.refresh_hours)
    async with runtime.sessions() as s:
        reads = {
            (r.minion_id, r.source): r
            for r in await s.scalars(select(InventoryRead).where(InventoryRead.minion_id.in_(mids)))
        }
        back = dict(
            (
                await s.execute(
                    select(PresenceChange.minion_id, func.max(PresenceChange.at))
                    .where(PresenceChange.connected.is_(True), PresenceChange.minion_id.in_(mids))
                    .group_by(PresenceChange.minion_id)
                )
            ).all()
        )
    for source in sources(runtime.settings):
        due = []
        for mid in mids:
            r = reads.get((mid, source))
            state = None if r is None else ReadState(r.asked_at, r.answered_at, r.wanted_at)
            if is_due(state, now=now, every=every, back_at=back.get(mid)):
                due.append(mid)
        await ask(runtime, source, due[:BATCH], now)


async def ask_now(runtime: Runtime, minion: str | None, now: datetime) -> list[str] | None:
    """Ask now: every source, from online minions. None when asked too recently."""
    key, every = (f"inventory-ask:{minion}", ASK_ONE_EVERY) if minion else ("inventory-ask", ASK_ALL_EVERY)
    last = runtime.memo.get(key)
    if last is not None and time.monotonic() - last[0] < every:
        return None
    runtime.memo[key] = (time.monotonic(), None)
    mids = await online(runtime, now, only=minion)
    for source in sources(runtime.settings):
        await ask(runtime, source, mids, now)
    return mids


async def run_forever(runtime: Runtime) -> None:
    while True:
        try:
            await sweep(runtime)
        except Exception:  # a bad sweep mustn't stop the next one
            log.exception("inventory sweep failed")
        await asyncio.sleep(SWEEP_SECONDS)
```

Imports: `asyncio`, `logging`, `time`, `UTC`, `func`/`select` from sqlalchemy,
`presence_info` from `app.api.fleet`, models, `Runtime` (under `TYPE_CHECKING` if importing it at
runtime causes a cycle: `app.runtime` imports `app.ingest`, which imports `app.inventory`; use
`from __future__ import annotations` + `if TYPE_CHECKING:`), `SaltApiError`, `SaltApiForbidden`.
Also move the `presence_info` import inside `online()` if `app.api.fleet` imports create a cycle.

Add to `Ingest` (system state section):

```python
    async def set_state_entry(self, key: str, entry: str, value: Any) -> None:
        """Set (or with None, remove) one entry of a dict kept in system state."""
        async with self._lock, self._sessions() as s, s.begin():
            row = await s.get(SystemState, key)
            current = dict(row.value or {}) if row is not None else {}
            if value is None:
                if entry not in current:
                    return
                current.pop(entry)
            elif current.get(entry) == value:
                return
            else:
                current[entry] = value
            await self._set_state(s, key, current)
```

`app/main.py`: `runtime.background(inventory.run_forever(runtime), "inventory")` next to
catch-up (only where the other background tasks start, i.e. when the collector runs).

**Step 4:** `uv run pytest tests/test_inventory.py -v` → the sweep tests PASS (Ask now waits for
Task 7). Full suite: `uv run pytest -q`.

**Step 5: Commit** `git commit -m "Inventory sweep: ask connected minions when due"`

---

### Task 7: API: explorer values, keys, changes, minion view, Ask now

**Files:**
- Create: `backend/app/api/inventory.py`
- Modify: `backend/app/api/schemas.py`, `backend/app/main.py` (include the router)
- Test: `backend/tests/test_inventory.py`

**Step 1: Schemas** (`schemas.py`):

```python
class InventoryKey(BaseModel):
    key: str  # "@packages:rover-agent", "@rover-cli"
    source: str
    name: str
    kind: Literal["package", "check"]
    minions: int


class InventoryDistribution(BaseModel):
    key: str
    source: str
    name: str
    kind: Literal["package", "check"]
    total: int  # accepted minions
    values: list[GrainValue]  # newest version first
    missing: list[str]  # answered without it
    unknown: list[str]  # never answered, or only failed answers
    oldest_read_at: datetime | None
    newest_read_at: datetime | None
    refused: str | None  # salt-api refuses to ask for this source


class InventoryChangeView(BaseModel):
    minion_id: str
    source: str
    name: str
    old: str | None
    new: str | None
    at: datetime
    since: datetime | None
    jid: str | None
    user: str | None


class InventoryEntry(BaseModel):
    name: str
    value: str
    since: datetime


class InventorySource(BaseModel):
    source: str
    kind: Literal["package", "check"]
    read_at: datetime | None
    first_read_at: datetime | None
    answered_at: datetime | None
    error: str | None
    truncated: bool
    entries: list[InventoryEntry]


class MinionInventory(BaseModel):
    sources: list[InventorySource]


class AskRequest(BaseModel):
    minion: str | None = None


class AskResult(BaseModel):
    asked: list[str]
```

**Step 2: Write the failing tests** (seed with `api.seed(api.ingest.inventory_read, ...)`):

```python
def seed_agent(api: Api) -> None:
    now = datetime.now(UTC)
    for mid, version in [("rover-01", "2.4.1"), ("rover-02", "2.4.1"), ("rover-03", "2.3.0")]:
        api.seed(api.ingest.inventory_read, mid, "packages", {"rover-agent": version, "bash": "5.2"}, at=now)
    api.seed(api.ingest.inventory_read, "dock-01", "packages", {"bash": "5.2"}, at=now)


def test_values_split_versions_missing_and_unknown(admin) -> None:
    api, _ = admin
    seed_agent(api)
    d = api.get("/api/inventory/values", key="@packages:rover-agent")
    assert [(v["text"], v["minions"]) for v in d["values"]] == [
        ("2.4.1", ["rover-01", "rover-02"]),
        ("2.3.0", ["rover-03"]),
    ]
    assert d["missing"] == ["dock-01"] and d["unknown"] == [] and d["kind"] == "package"


def test_never_read_minions_are_unknown_not_missing(admin) -> None:
    api, _ = admin
    api.seed(api.ingest.inventory_read, "rover-01", "packages", {"rover-agent": "2.4.1"}, at=datetime.now(UTC))
    d = api.get("/api/inventory/values", key="@packages:rover-agent")
    assert d["missing"] == [] and sorted(d["unknown"]) == ["dock-01", "rover-02", "rover-03"]


def test_keys_search_packages(admin) -> None:
    api, _ = admin
    seed_agent(api)
    assert [k["key"] for k in api.get("/api/inventory/keys", q="agent")] == ["@packages:rover-agent"]


def test_changes_for_a_package_and_for_a_minion(admin) -> None:
    api, _ = admin
    seed_agent(api)
    later = datetime.now(UTC) + timedelta(minutes=5)
    api.seed(api.ingest.inventory_read, "rover-03", "packages", {"rover-agent": "2.4.1", "bash": "5.2"}, at=later)
    (c,) = api.get("/api/inventory/changes", key="@packages:rover-agent")
    assert (c["minion_id"], c["old"], c["new"]) == ("rover-03", "2.3.0", "2.4.1")
    assert api.get("/api/inventory/changes", minion="rover-03") == [c]


def test_minion_inventory_lists_every_source(admin) -> None:
    api, _ = admin
    seed_agent(api)
    (packages,) = api.get("/api/minions/rover-01/inventory")["sources"]
    assert [e["name"] for e in packages["entries"]] == ["bash", "rover-agent"]


def test_values_of_a_grain_key_are_refused(admin) -> None:
    api, _ = admin
    assert api.client.get("/api/inventory/values", params={"key": "app_version"}).status_code == 422
```

**Step 3: Implement** `app/api/inventory.py`:

```python
"""Packages and checks: the explorer, changes, one minion's entries, and Ask now."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app import inventory
from app.api.deps import CurrentUser, RuntimeDep, SessionDep  # check the real module name
from app.api.schemas import (...)
from app.models import InventoryChange, InventoryItem, InventoryRead, Minion

router = APIRouter(prefix="/api")

_PART = re.compile(r"(\d+)")


def version_key(text: str) -> list[tuple[int, int | str]]:
    """Natural order: 2.10 after 2.9."""
    return [(0, int(p)) if p.isdigit() else (1, p) for p in _PART.split(text) if p]


def _kind(source: str) -> Literal["package", "check"]:
    return "package" if source == inventory.PACKAGES else "check"


def _parse(key: str, runtime) -> tuple[str, str]:
    parsed = inventory.parse_key(key)
    if parsed is None or parsed[0] not in inventory.sources(runtime.settings):
        raise HTTPException(422, f"{key!r} isn't a package or a configured check")
    return parsed


@router.get("/inventory/keys", response_model=list[InventoryKey])
async def keys(runtime: RuntimeDep, session: SessionDep, q: str = "", limit: int = Query(50, ge=1, le=200)) -> list[InventoryKey]:
    """Checks always; packages whose name contains `q` (none without a `q`)."""
    query = (
        select(InventoryItem.source, InventoryItem.name, func.count())
        .join(Minion, Minion.id == InventoryItem.minion_id)
        .where(Minion.key_state == "accepted")
        .group_by(InventoryItem.source, InventoryItem.name)
    )
    needle = q.strip().lower()
    if needle:
        query = query.where(func.lower(InventoryItem.name).contains(needle) | (InventoryItem.source != inventory.PACKAGES))
    else:
        query = query.where(InventoryItem.source != inventory.PACKAGES)
    rows = (await session.execute(query.order_by(InventoryItem.source, InventoryItem.name).limit(limit))).all()
    return [InventoryKey(key=inventory.key_of(src, name), source=src, name=name, kind=_kind(src), minions=n) for src, name, n in rows]


@router.get("/inventory/values", response_model=InventoryDistribution)
async def values(runtime: RuntimeDep, session: SessionDep, key: str) -> InventoryDistribution:
    source, name = _parse(key, runtime)
    accepted = list((await session.scalars(select(Minion.id).where(Minion.key_state == "accepted").order_by(Minion.id))).all())
    reads = {r.minion_id: r for r in await session.scalars(select(InventoryRead).where(InventoryRead.source == source))}
    held = dict((await session.execute(select(InventoryItem.minion_id, InventoryItem.value).filter_by(source=source, name=name))).all())
    groups: dict[str, list[str]] = {}
    missing, unknown = [], []
    for mid in accepted:
        read = reads.get(mid)
        if read is None or read.read_at is None:
            unknown.append(mid)
        elif mid in held:
            groups.setdefault(held[mid], []).append(mid)
        else:
            missing.append(mid)
    times = [r.read_at for m, r in reads.items() if r.read_at and m in set(accepted)]
    refused = (await runtime.ingest.get_state(inventory.REFUSED_STATE) or {}).get(source)
    return InventoryDistribution(
        key=key, source=source, name=name, kind=_kind(source), total=len(accepted),
        values=[GrainValue(value=v, text=v, minions=ms) for v, ms in sorted(groups.items(), key=lambda g: version_key(g[0]), reverse=True)],
        missing=missing, unknown=unknown,
        oldest_read_at=min(times, default=None), newest_read_at=max(times, default=None),
        refused=refused,
    )


@router.get("/inventory/changes", response_model=list[InventoryChangeView])
async def changes(runtime: RuntimeDep, session: SessionDep, key: str | None = None, minion: str | None = None,
                  limit: int = Query(100, ge=1, le=500)) -> list[InventoryChangeView]:
    query = select(InventoryChange).order_by(InventoryChange.at.desc(), InventoryChange.id.desc()).limit(limit)
    if key is not None:
        source, name = _parse(key, runtime)
        query = query.where(InventoryChange.source == source, InventoryChange.name == name)
    if minion is not None:
        query = query.where(InventoryChange.minion_id == minion)
    return [InventoryChangeView.model_validate(c, from_attributes=True) for c in await session.scalars(query)]


@router.get("/minions/{minion_id}/inventory", response_model=MinionInventory)
async def minion_inventory(minion_id: str, runtime: RuntimeDep, session: SessionDep) -> MinionInventory:
    if await session.get(Minion, minion_id) is None:
        raise HTTPException(404, f"No minion {minion_id!r}")
    reads = {r.source: r for r in await session.scalars(select(InventoryRead).filter_by(minion_id=minion_id))}
    entries: dict[str, list[InventoryEntry]] = {}
    for item in await session.scalars(select(InventoryItem).filter_by(minion_id=minion_id).order_by(InventoryItem.name)):
        entries.setdefault(item.source, []).append(InventoryEntry(name=item.name, value=item.value, since=item.since))
    out = []
    for source in inventory.sources(runtime.settings):
        r = reads.get(source)
        out.append(InventorySource(
            source=source, kind=_kind(source),
            read_at=r.read_at if r else None, first_read_at=r.first_read_at if r else None,
            answered_at=r.answered_at if r else None, error=r.error if r else None,
            truncated=bool(r and r.truncated), entries=entries.get(source, []),
        ))
    return MinionInventory(sources=out)


@router.post("/inventory/ask", response_model=AskResult)
async def ask(body: AskRequest, runtime: RuntimeDep, user: CurrentUser) -> AskResult:
    asked = await inventory.ask_now(runtime, body.minion, datetime.now(UTC))
    if asked is None:
        raise HTTPException(429, "Asked a moment ago; try again in a minute.")
    return AskResult(asked=asked)
```

This block is the shape, not final formatting: run `uv run ruff format .` and fix what mypy
reports. Look at `app/api/fleet.py` for the real dependency names (`RuntimeDep`, `SessionDep`,
`CurrentUser`) and how routers are registered in `app/main.py`; the CSRF middleware already
covers POST. Ask now is open to every signed-in role on purpose (it only reads).

**Step 4:** `uv run pytest tests/test_inventory.py -v` → PASS (including Task 6's Ask now
test); full suite.

**Step 5: Commit** `git commit -m "API: packages and checks explorer, changes, minion view, Ask now"`

---

### Task 8: Fleet columns for packages and checks

**Files:**
- Modify: `backend/app/api/fleet.py` (`requested_columns`, `summarize`, `fleet`)
- Test: `backend/tests/test_inventory.py`

**Step 1: Failing test**

```python
def test_fleet_columns_show_versions_missing_and_unknown(admin) -> None:
    api, _ = admin
    now = datetime.now(UTC)
    api.seed(api.ingest.inventory_read, "rover-01", "packages", {"rover-agent": "2.4.1"}, at=now)
    api.seed(api.ingest.inventory_read, "dock-01", "packages", {"bash": "5.2"}, at=now)
    fleet = api.get("/api/fleet", column=["@packages:rover-agent"])
    cols = {m["id"]: m["columns"] for m in fleet["minions"]}
    assert cols["rover-01"] == {"@packages:rover-agent": "2.4.1"}
    assert cols["dock-01"] == {"@packages:rover-agent": None}  # answered without it
    assert cols["rover-02"] == {}  # never answered: unknown, so no value at all
    assert fleet["columns"] == [{"grain": "@packages:rover-agent", "label": "rover-agent"}]
```

**Step 2:** run → FAIL.

**Step 3: Implement.**
- `requested_columns`: label for `@` keys is the name, or the source for single-value checks
  (`labels.get(g) or _label(g)` where `_label` uses `inventory.parse_key`).
- In `fleet()`, before summarizing: for the requested `@` columns, load
  `{(mid, key): value}` from `InventoryItem` and the set of `(mid, source)` with a non-null
  `read_at` from `InventoryRead` (two queries, filtered by the requested sources/names).
- Give `summarize` an optional `inventory: dict[str, dict[str, str | None]] | None` (per minion:
  key -> value or None) and build `columns` as: grain columns as before; for `@` keys, include
  the key only if the minion has a read of that source (value or `None`).
- Update the `MinionSummary.columns` comment in `schemas.py`: "`@` columns: a missing key means
  unknown (the minion hasn't answered for that source)".

**Step 4:** PASS; run `tests/test_api.py` too (fleet tests must still pass).

**Step 5: Commit** `git commit -m "Fleet: packages and checks as columns"`

---

### Task 9: Settings and Issues

**Files:**
- Modify: `backend/app/api/schemas.py` (`InventorySettings`, field on `SettingsView`),
  `backend/app/api/system.py`, `backend/app/api/issues.py`
- Test: `backend/tests/test_inventory.py`

**Step 1: Failing tests**

```python
def test_settings_show_checks_and_acl(admin) -> None:
    api, _ = admin
    inv_settings = api.get("/api/settings")["inventory"]
    assert inv_settings["refresh_hours"] == 6 and inv_settings["checks"] == []
    assert "pkg.list_pkgs" in inv_settings["acl"] and inv_settings["refused"] == {}


def test_a_refused_package_read_is_an_issue(admin) -> None:
    api, salt = admin
    salt.forbidden.add("pkg.list_pkgs")
    api.seed(inv.sweep, runtime(api), datetime.now(UTC))
    (issue,) = [i for i in api.get("/api/issues") if i["key"] == "inventory:packages"]
    assert issue["severity"] == "warning" and "pkg.list_pkgs" in issue["detail"]
```

**Step 3: Implement.**

```python
class InventoryCheck(BaseModel):
    name: str
    command: str


class InventorySettings(BaseModel):
    refresh_hours: float
    checks: list[InventoryCheck]
    acl: str  # the external_auth lines brine's account needs
    refused: dict[str, str]  # source -> why salt-api refused
```

`SettingsView.inventory: InventorySettings`; fill it in `settings_view` (`acl=inventory.acl_lines(s)`,
`refused=await runtime.ingest.get_state(inventory.REFUSED_STATE) or {}`; make the handler use
it). In `issues()`, in the "brine's own connection" section:

```python
    for source, why in (await runtime.ingest.get_state(inventory.REFUSED_STATE) or {}).items():
        what = "packages" if source == inventory.PACKAGES else f"the {source} check"
        found.append(_issue(f"inventory:{source}", "warning", f"brine can't read {what}",
                            f"{why}. Settings › Packages and checks has the ACL lines to add."))
```

**Step 4:** PASS. **Step 5: Commit** `git commit -m "Settings and Issues: packages and checks"`

---

### Task 10: Frontend types, queries and live updates

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/queries.ts`, `frontend/src/api/live.ts`
- Create: `frontend/src/lib/inventoryKey.ts` (+ `inventoryKey.test.ts`)
- Test: `frontend/src/api/live.test.ts` (if it exists; else skip that part)

**Step 1: Failing test** `lib/inventoryKey.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { isInventoryKey, keyLabel, parseInventoryKey } from '@/lib/inventoryKey'

describe('inventory keys', () => {
  it('parses packages and checks, and leaves grains alone', () => {
    expect(parseInventoryKey('@packages:rover-agent')).toEqual({ source: 'packages', name: 'rover-agent' })
    expect(parseInventoryKey('@rover-cli')).toEqual({ source: 'rover-cli', name: '' })
    expect(parseInventoryKey('app_version')).toBeNull()
    expect(isInventoryKey('@packages:x')).toBe(true)
    expect(keyLabel('@packages:rover-agent')).toBe('rover-agent')
    expect(keyLabel('@rover-cli')).toBe('rover-cli')
    expect(keyLabel('os:family')).toBe('os:family')
  })
})
```

**Step 3: Implement** `lib/inventoryKey.ts`:

```ts
/** Explorer and column keys: a grain path (`app_version`), or `@source:name` for a package or a
 * check's entry (`@packages:rover-agent`, `@rover-cli` for a check with a single value). */
export function parseInventoryKey(key: string): { source: string; name: string } | null {
  if (!key.startsWith('@') || key.length < 2) return null
  const rest = key.slice(1)
  const i = rest.indexOf(':')
  return i < 0 ? { source: rest, name: '' } : { source: rest.slice(0, i), name: rest.slice(i + 1) }
}

export const isInventoryKey = (key: string) => parseInventoryKey(key) !== null

export function keyLabel(key: string): string {
  const parsed = parseInventoryKey(key)
  return parsed ? parsed.name || parsed.source : key
}
```

Types (`types.ts`), mirroring the schemas from Task 7/9: `InventoryKey`,
`InventoryDistribution`, `InventoryChange`, `MinionInventory` (+ `InventorySource`,
`InventoryEntry`), `SettingsView.inventory`.

Queries (`queries.ts`), all under `['inventory', ...]` except the minion's:

```ts
export function useInventoryKeys(q: string) {
  return useQuery({
    queryKey: ['inventory', 'keys', q],
    queryFn: () => fetchJson<InventoryKey[]>(`/api/inventory/keys?q=${enc(q)}`),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })
}

export function useInventoryValues(key: string | null) {
  return useQuery({
    queryKey: ['inventory', 'values', key],
    queryFn: () => fetchJson<InventoryDistribution>(`/api/inventory/values?key=${enc(key ?? '')}`),
    enabled: !!key,
    placeholderData: keepPreviousData,
  })
}

export function useInventoryChanges(filter: { key: string } | { minion: string }, enabled = true) {
  const params = new URLSearchParams(filter)
  return useQuery({
    queryKey: 'minion' in filter ? [...queryKeys.minion(filter.minion), 'inventory-changes'] : ['inventory', 'changes', filter.key],
    queryFn: () => fetchJson<InventoryChange[]>(`/api/inventory/changes?${params}`),
    enabled,
  })
}

export function useMinionInventory(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.minion(id), 'inventory'],
    queryFn: () => fetchJson<MinionInventory>(`/api/minions/${enc(id)}/inventory`),
    enabled,
  })
}

export function useAskInventory() {
  return useMutation({
    mutationFn: (minion: string | null) => postJson<{ asked: string[] }>('/api/inventory/ask', { minion }),
  })
}
```

`live.ts`: in the `'fleet'` case add `queue(['inventory'])` (reads change the fleet when values
move; the minion's own queries already refresh on `'minion'`).

**Step 4:** `npm test -- inventoryKey` PASS; `npm run typecheck`.

**Step 5: Commit** `git commit -m "Frontend: inventory types, queries and keys"`

---

### Task 11: The explorer: grains, packages and checks in one place

**Files:**
- Modify: `frontend/src/pages/fleet/GrainsExplorer.tsx` (export `ValueRow`; picker lists
  inventory keys; the right side switches on the key kind)
- Create: `frontend/src/pages/fleet/InventoryValues.tsx`
- Modify: `frontend/src/pages/fleet/FleetPage.tsx` (tab label "Grains & packages")
- Test: `frontend/src/pages/fleet/FleetPage.test.tsx` (follow its fetch-mock pattern)

**Step 1: Failing tests** (in `FleetPage.test.tsx`, using its existing mock helpers):
1. Typing `agent` in "Find a grain or package…" lists `rover-agent` marked "package".
2. Opening `/?tab=grains&grain=@packages:rover-agent` shows rows `2.4.1 · 2`, `2.3.0 · 1`,
   `Not installed · 1`, `Unknown · 0` hidden when empty, a "Run on these" link to
   `/run?target=rover-01%2Crover-02&type=list`, and the Changes list with
   "after job … by alice@example.com" for a credited change and "between … and …" otherwise.
3. Ask now posts to `/api/inventory/ask` with `{ minion: null }` and shows "Asked 3 minions".

**Step 3: Implement.**
- `GrainsExplorer`: placeholder/aria "Find a grain or package…". Below the grains list, a
  second list "Packages and checks" from `useInventoryKeys(filter)` (checks always; packages once
  something is typed), each button showing `keyLabel(k.key)`, a small muted kind label
  (`package` / `check`) and the count. Selecting sets `grain=<key>` as today.
- Right side: `isInventoryKey(grain) ? <InventoryValues key={grain} … /> : <existing grain view>`;
  the heading uses `keyLabel(grain)` plus the kind label. "Add as a Fleet column" stays as is
  (the key is the column).
- `InventoryValues.tsx`:

```tsx
/** One package or check across the fleet: versions, who lacks it, who hasn't answered. */
export function InventoryValues({ itemKey, statusOf, now }: { itemKey: string; statusOf: Record<string, MinionStatus>; now: number }) {
  const dist = useInventoryValues(itemKey)
  const changes = useInventoryChanges({ key: itemKey })
  const askNow = useAskInventory()
  if (dist.isPending) return <p className="px-6 py-10 text-center text-muted">Loading…</p>
  if (dist.isError) return <p className="px-6 py-10 text-center text-muted">Couldn't load it: {dist.error.message}</p>
  const d = dist.data
  return (
    <>
      {d.refused && <p className="border-b bg-warn/10 px-6 py-3 text-sm">{d.refused} Settings has the ACL lines to add.</p>}
      <ul aria-label={`Versions of ${keyLabel(itemKey)}`}>
        {d.values.map((v) => (
          <ValueRow key={v.text} text={v.text} minions={v.minions} total={d.total} statusOf={statusOf}
            action={<RunOn minions={v.minions} />} />
        ))}
        {d.missing.length > 0 && <ValueRow text={d.kind === 'package' ? 'Not installed' : 'Nothing reported'} minions={d.missing} total={d.total} statusOf={statusOf} muted />}
        {d.unknown.length > 0 && <ValueRow text="Unknown (no answer yet)" minions={d.unknown} total={d.total} statusOf={statusOf} muted />}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-sm text-muted sm:px-6">
        <span>{readSummary(d, now)}</span>
        <button type="button" disabled={askNow.isPending} onClick={() => askNow.mutate(null)}
          className="flex h-8 items-center gap-1.5 rounded-lg border px-3 hover:bg-surface-2 disabled:opacity-50">
          <RefreshCw className="size-4" aria-hidden /> Ask now
        </button>
      </div>
      {askNow.data && <p role="status" className="px-6 pb-3 text-sm text-muted">Asked {askNow.data.asked.length} minions; answers appear as they arrive.</p>}
      {askNow.isError && <p role="alert" className="px-6 pb-3 text-sm text-danger">{askNow.error.message}</p>}
      <ChangeList changes={changes.data ?? []} now={now} />
    </>
  )
}
```

  `RunOn` renders `<Link to={`/run?${new URLSearchParams({ target: minions.join(','), type: 'list' })}`}>Run on these</Link>`.
  `readSummary`: "Read 2h ago" (newest) or "Read between 3h and 20m ago" when oldest and newest
  differ by more than an hour; "Not read yet" when both are null. `ChangeList` (put it in its own
  file `pages/fleet/ChangeList.tsx`, reused by the minion History tab) renders each change as
  `<time> <minion> old → new <why>`, where why is `after job <Link to /jobs/:jid>` + `by <user>`
  or `between <since> and <at>`; `(new)` / `(removed)` for null old/new; shows nothing when
  the list is empty.
- `ValueRow`: add an optional `action?: React.ReactNode` rendered in the expanded area, before
  the chips (keep the row button itself a single control).
- `FleetPage.tsx`: `{ key: 'grains', label: 'Grains & packages' }`; pass `now` to the explorer.

**Step 4:** `npm test`, `npm run lint`, `npm run typecheck` → PASS.

**Step 5: Commit** `git commit -m "Explorer: packages and checks next to grains"`

---

### Task 12: Fleet table cells for package columns

**Files:**
- Modify: `frontend/src/pages/fleet/columns.tsx` (`grainColumn`), wherever labels for column
  chips are shown (`ColumnsMenu.tsx`: use `keyLabel`)
- Test: `frontend/src/pages/fleet/FleetPage.test.tsx`

**Step 1: Failing test:** a fleet response with `columns: [{grain: '@packages:rover-agent',
label: 'rover-agent'}]` and minions whose `columns` are `{'@packages:rover-agent': '2.4.1'}`,
`{'@packages:rover-agent': null}` and `{}` renders `2.4.1`, `—` and `?` (with title "No answer
yet").

**Step 3: Implement** in `grainColumn`:

```tsx
    render: (m) => {
      if (isInventoryKey(grain) && !(grain in m.columns))
        return <span className="text-muted" title="No answer from this minion yet">?</span>
      const text = cellText(m.columns[grain])
      return text === null ? <span className="text-muted">—</span> : <Pill title={text}>{text}</Pill>
    },
```

**Step 4/5:** tests PASS; commit `git commit -m "Fleet table: package and check columns"`.

---

### Task 13: Minion page: Packages tab and one History

**Files:**
- Create: `frontend/src/pages/minion/PackagesPanel.tsx`
- Modify: `frontend/src/pages/minion/MinionPage.tsx` (TABS), `frontend/src/pages/minion/panels.tsx` (`HistoryPanel`)
- Test: `frontend/src/pages/minion/MinionPage.test.tsx`

**Step 1: Failing tests:**
1. The Packages tab lists entries with versions, filters by the search box, shows "Read 2h ago"
   and each check as its own section ("rover-cli: rover-cli 1.2.0"); a source with an error
   shows "Couldn't read: exit 127: …" and keeps the entries.
2. The History tab (label "History") shows a grains change and a package change
   ("rover-agent 2.3.0 → 2.4.1 after job … by alice@example.com"), newest first.

**Step 3: Implement.**
- TABS: insert `{ key: 'packages', label: 'Packages' }` after grains; rename `history` label to
  `History`.
- `PackagesPanel({ minionId, now })`: `useMinionInventory(minionId, true)`; one section per
  source (packages first): heading (`Packages` or the check name), "Read X ago · first read
  <date>", error line, "Only the first 500 entries" when truncated, then a searchable table
  (Name | Version/Value | Since: "since brine first looked" when `since === first_read_at`,
  else relative time). Ask now button: `useAskInventory().mutate(minionId)`.
- `HistoryPanel`: also call `useInventoryChanges({ minion: minionId })`; render the existing
  grains entries and the inventory changes in one list ordered by time (newest first). Group
  inventory changes with the same `at` into one entry titled "Packages: 2 changed" (or the check
  name) using `ChangeList` rows. Empty state: "No grains or packages collected yet."

**Step 4:** `npm test`, lint, typecheck. **Step 5: Commit** `git commit -m "Minion page: Packages tab and one History"`

---

### Task 14: Settings page section

**Files:**
- Modify: `frontend/src/pages/settings/SettingsPage.tsx`, its test

**Step 1: Failing test:** Settings shows "Packages and checks" with "Read every 6 hours, after
people's jobs, and on Ask now", each check as `name: command` in mono, and, when `refused` is
non-empty, the ACL lines in a `<pre>` with "Add these to brine's account in the master's
external_auth" (and no `<pre>` otherwise).

**Step 3: Implement** following the existing `Row` pattern next to retention.

**Step 4/5:** tests PASS; commit `git commit -m "Settings: packages and checks"`.

---

### Task 15: Demo fleet: a versioned .deb, a check, and the ACL

**Files:**
- Modify: `demo/Dockerfile` (build two tiny debs into `/srv/debs`)
- Modify: `demo/entrypoint-minion.sh` (pre-install a version per minion; a hand-installed CLI)
- Modify: `docker-compose.demo.yml` (env per minion), `demo/master.d/brine-demo.conf`
  (file_roots + ACL), `demo/brine.yaml` (check)
- Create: `demo/states/agent.sls`

**Step 1: Build the debs in the image** (`demo/Dockerfile`, after the Salt install):

```dockerfile
# A tiny versioned package for the Packages demo: rover-agent 2.3.0 and 2.4.1, served to minions
# from salt://debs/ and pre-installed on some of them (like software that predates Salt).
RUN set -eux; \
    for v in 2.3.0 2.4.1; do \
      d=/tmp/rover-agent_$v; mkdir -p $d/DEBIAN $d/opt/rover-agent; \
      printf 'Package: rover-agent\nVersion: %s\nArchitecture: all\nMaintainer: brine demo <demo@example.com>\nDescription: brine demo agent\n' $v > $d/DEBIAN/control; \
      echo $v > $d/opt/rover-agent/VERSION; \
      mkdir -p /srv/debs/debs; dpkg-deb --build --root-owner-group $d /srv/debs/debs/rover-agent_${v}_all.deb; \
      rm -rf $d; \
    done
```

**Step 2: Minion entrypoint**: before `exec salt-minion`:

```sh
# Software that was there before Salt: rover-agent pre-installed at AGENT_VERSION (if set), and
# a hand-copied CLI at /opt/rover/bin (if CLI_VERSION is set), which no package manager knows.
if [ -n "${AGENT_VERSION:-}" ] && ! dpkg -s rover-agent >/dev/null 2>&1; then
  dpkg -i "/srv/debs/debs/rover-agent_${AGENT_VERSION}_all.deb"
fi
if [ -n "${CLI_VERSION:-}" ]; then
  mkdir -p /opt/rover/bin
  printf '#!/bin/sh\necho "rover-cli %s"\n' "$CLI_VERSION" > /opt/rover/bin/rover-cli
  chmod 755 /opt/rover/bin/rover-cli
fi
```

`docker-compose.demo.yml`: rover-01 and rover-02 `AGENT_VERSION: "2.4.1"`, rover-03 `"2.3.0"`,
dock-01 none, rover-04 `"2.4.1"`; `CLI_VERSION` "1.2.0" on the rovers, "1.1.0" on rover-03,
none on dock-01.

**Step 3: Master config** (`brine-demo.conf`):
- `file_roots: base: [/srv/salt, /srv/debs]` (check whether file_roots is already set; extend it).
- In brine's read-only `'*'` list add `- pkg.list_pkgs` and:

```yaml
        - cmd.run_all:
            args:
              - '^/opt/rover/bin/rover\-cli\ \-\-version\ 2>/dev/null\ \|\|\ true$'
```

  (generate the exact line with `inv.acl_lines` against `demo/brine.yaml` rather than by hand).

`demo/brine.yaml`:

```yaml
# Packages are read from every minion; checks add software no package manager knows about.
inventory:
  checks:
    rover-cli: "/opt/rover/bin/rover-cli --version 2>/dev/null || true"
```

`demo/states/agent.sls`:

```yaml
# Installs rover-agent at a chosen version: state.apply agent pillar='{"agent_version": "2.4.1"}'
rover-agent:
  pkg.installed:
    - sources:
      - rover-agent: salt://debs/rover-agent_{{ pillar.get('agent_version', '2.4.1') }}_all.deb
```

**Step 4: Verify by hand**

```bash
docker compose -f docker-compose.demo.yml up -d --build --wait
uv run --project backend python demo/smoke_test.py --presence
```

Then with a salt-api token (see the session's earlier curl): `pkg.list_pkgs` on rover-03 includes
`rover-agent: 2.3.0`; `cmd.run_all ['/opt/rover/bin/rover-cli --version 2>/dev/null || true']`
as brine returns `rover-cli 1.1.0`; the same command with another argument is refused (proves
the ACL limit).

**Step 5: Commit** `git commit -m "Demo: a versioned rover-agent package and a rover-cli check"`

---

### Task 16: End to end against the demo fleet

**Files:**
- Modify: `backend/tests/test_demo_integration.py` (new test)

**Step 1: Write the test** (style of `test_demo_fleet_end_to_end`; settings fixture gets the
`inventory.checks` from `demo/brine.yaml`):

```python
def test_packages_and_checks_end_to_end(settings: Settings) -> None:
    app = create_app(settings, frontend_dist=Path("/nonexistent"))
    with TestClient(app) as c:
        wait_until("rover-agent read everywhere", lambda: not get(c, "/api/inventory/values", key="@packages:rover-agent")["unknown"], 120)
        d = get(c, "/api/inventory/values", key="@packages:rover-agent")
        assert {v["text"]: v["minions"] for v in d["values"]} == {"2.4.1": ["rover-01", "rover-02"], "2.3.0": ["rover-03"]}
        assert d["missing"] == ["dock-01"]
        cli = get(c, "/api/inventory/values", key="@rover-cli")
        assert {v["text"] for v in cli["values"]} == {"rover-cli 1.2.0", "rover-cli 1.1.0"}

        # Upgrade rover-03 from brine; the change is credited to that job.
        run = c.post("/api/commands/run", headers={"X-Requested-With": "test"}, json={
            "command": 'state.apply agent pillar=\'{"agent_version": "2.4.1"}\'',
            "target": "rover-03", "target_type": "list", "expect": ["rover-03"]})
        assert run.status_code == 200, run.text
        jid = run.json()["jid"]
        wait_until("the upgrade recorded", lambda: any(ch["jid"] == jid and ch["new"] == "2.4.1"
                   for ch in get(c, "/api/inventory/changes", key="@packages:rover-agent")), 180)
        # Put the demo back the way it was.
        c.post("/api/commands/run", headers={"X-Requested-With": "test"}, json={
            "command": 'state.apply agent pillar=\'{"agent_version": "2.3.0"}\'',
            "target": "rover-03", "target_type": "list", "expect": ["rover-03"]})
```

The `AFTER_JOB` re-read takes ~60–75 s; the 180 s budget covers it. Check the real shape of the
`/api/commands/run` response (`jid` field name) in `test_commands.py`.

**Step 2:** `BRINE_DEMO_SALT_API=http://127.0.0.1:8001 uv run pytest tests/test_demo_integration.py -v`
→ PASS (both tests). Then `SALT_VERSION=3008` (fresh containers: `down` first) → PASS.

**Step 3: Commit** `git commit -m "End to end: packages and checks on the demo fleet"`

---

### Task 17: Docs, screenshots, changelog

**Files:**
- Modify: `docs/permissions-and-salt-acl.md` (read-only ACL gains `pkg.list_pkgs`; new section
  "Checks" with the args-limited `cmd.run_all`; "What brine never asks for" now says brine runs
  exactly the check commands you configure and nothing else for itself)
- Modify: `config.example.yaml` (an `inventory:` section with a commented podman example)
- Modify: `README.md` (Fleet › Grains & packages paragraph; Minion paragraph mentions Packages
  and History; feature bullet "What's installed where"), `CHANGELOG.md` (0.1.0 bullet),
  `SECURITY.md` (package lists and check output are visible to everyone signed in; keep secrets
  out of checks), `docs/decisions.md` (new decision: packages and checks; why not grains, why
  brine asks, attribution rules), `docs/saltgui-parity.md` ("Only in brine" bullet)
- Modify: `scripts/screenshots.mjs`: the `grains` shot becomes
  `/?tab=grains&grain=${encodeURIComponent('@packages:rover-agent')}`; add a `packages` shot of
  `/minions/rover-01?tab=packages` (README "Minion" section shows it); README image alt texts
  updated to match.

**Step 1:** write the docs. **Step 2:** regenerate screenshots against the demo backend on 8010
(`node scripts/screenshots.mjs --base http://127.0.0.1:8010 --stop-minion rover-03`, Docker on
PATH) and look at each changed image. **Step 3:** commit
`git commit -m "Docs and screenshots: packages and checks"`.

---

### Task 18: Final checks, tidy, push

1. Backend: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`.
2. Frontend: `npm run lint && npm run typecheck && npm test && npm run build`.
3. Image: `BRINE_PORT=8090 BRINE_VERSION=ci docker compose -f docker-compose.demo.yml --profile brine up -d --build --wait`;
   `/api/inventory/values?key=@packages:rover-agent` shows versions within a minute.
4. Fold this plan and the design into `docs/decisions.md` (the decision written in Task 17), then
   `git rm -r docs/plans` so the public repo carries no planning files.
5. Scans (sensitive paths, former-employer names, secrets), commit, `git push`, watch CI
   (`gh run watch`), then ask the user before tagging v0.1.0.
