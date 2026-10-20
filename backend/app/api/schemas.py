"""Response shapes for the JSON API. Times are ISO-8601 UTC; `null` means "never" / "unknown"."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.states import StateResult
from app.status import Status


class Column(BaseModel):
    grain: str
    label: str


class MinionSummary(BaseModel):
    id: str
    status: Status
    connected: bool
    last_seen_at: datetime | None
    key_state: str
    os: str | None
    salt_version: str | None
    ip: str | None
    grains_at: datetime | None
    grains_source: str | None
    # Values of the configured fleet columns, keyed by grain name.
    columns: dict[str, Any]


class FleetSummary(BaseModel):
    total: int
    online: int
    offline: int
    stale: int
    unknown: int
    pending_keys: int


class PresenceInfo(BaseModel):
    method: str | None  # what provided the latest observation: events / connected / ping
    checked_at: datetime | None


class Fleet(BaseModel):
    summary: FleetSummary
    columns: list[Column]  # what `columns` in each minion holds (requested or default)
    default_columns: list[Column]  # fleet.columns from the config
    presence: PresenceInfo
    minions: list[MinionSummary]


class LiveView(BaseModel):
    kind: str
    function: str  # the Salt function that produced `data`
    fetched_at: datetime
    answered: bool  # False: the minion didn't reply in time (offline or busy)
    data: Any


class Reactor(BaseModel):
    tag: str  # event tag pattern
    sls: list[str]  # reactor SLS files it runs


class GrainKey(BaseModel):
    key: str
    minions: int


class PresencePoint(BaseModel):
    at: datetime
    connected: bool


class MinionJob(BaseModel):
    jid: str
    fun: str
    started_at: datetime
    returned_at: datetime
    success: bool | None
    retcode: int | None


class MinionDetail(MinionSummary):
    first_seen_at: datetime
    grains: dict[str, Any] | None
    presence_history: list[PresencePoint]
    recent_jobs: list[MinionJob]


class GrainsChange(BaseModel):
    collected_at: datetime
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, dict[str, Any]]  # grain -> {"from": old, "to": new}


class JobSummary(BaseModel):
    jid: str
    kind: str
    fun: str
    target: str | None
    target_type: str | None
    user: str | None
    started_at: datetime
    finished_at: datetime | None  # latest return so far
    expected: int
    returned: int
    succeeded: int
    failed: int


class JobPage(BaseModel):
    jobs: list[JobSummary]
    next_before: str | None  # pass as ?before= for the next (older) page


class JobResult(BaseModel):
    minion_id: str
    returned_at: datetime
    success: bool | None
    retcode: int | None
    data: Any
    states: list[StateResult] | None = None  # parsed, for state.apply/highstate/sls jobs


class StateDot(BaseModel):
    id: str
    function: str
    result: bool | None
    changed: bool


class StateRun(BaseModel):
    minion_id: str
    jid: str
    fun: str
    started_at: datetime
    returned_at: datetime
    success: bool | None
    total: int
    succeeded: int
    failed: int
    changed: int
    states: list[StateDot]


class StateRuns(BaseModel):
    runs: list[StateRun]
    never: list[str]  # accepted minions brine has no state run for


class JobDetail(JobSummary):
    args: list[Any]
    minions: list[str]
    missing: list[str]  # expected minions that haven't returned
    results: list[JobResult]


class Key(BaseModel):
    id: str
    key_state: str
    fingerprint: str | None
    first_seen_at: datetime
    last_seen_at: datetime | None
    status: Status | None  # accepted keys only


class SaltApiStatus(BaseModel):
    url: str
    connected: bool
    since: datetime | None
    error: str | None
    last_event_at: datetime | None


class SystemStatus(BaseModel):
    version: str
    salt_api: SaltApiStatus
    presence_method_configured: str
    presence: PresenceInfo
    stale_after_minutes: int
