"""Response shapes for the JSON API. Times are ISO-8601 UTC; `null` means "never" / "unknown"."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.states import StateResult
from app.status import Status


class Column(BaseModel):
    grain: str  # a grain path, or a package's or check's `@` key (`@packages:bash`)
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
    # Values of the fleet's columns, keyed by grain path or `@` key. `@` columns: None means
    # the minion answered without it; a missing key means unknown (no good read of that
    # source yet, or the last one was cut short and doesn't list it).
    columns: dict[str, Any]
    # When the minion's `@` column values are as of: each of their sources' last whole read
    # ("packages", a check's name); None before the first, or when the last was cut short.
    read_at: dict[str, datetime | None]


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
    offline: bool = False  # not asked: presence says it's offline
    data: Any


class SaltApiSettings(BaseModel):
    url: str
    username: str
    eauth: str
    verify_tls: bool
    timeout_seconds: float


class PresenceSettings(BaseModel):
    method: str  # configured
    active_method: str | None  # what's providing presence right now
    poll_seconds: int


class FleetSettings(BaseModel):
    stale_after_minutes: int
    grains_refresh_minutes: int
    columns: list[Column]


class DatabaseSettings(BaseModel):
    backend: str
    url: str  # password removed


class RoleCounts(BaseModel):
    viewer: int
    operator: int
    admin: int


class AuthSettings(BaseModel):
    provider: str
    issuer: str | None
    display_name: str
    configured: bool
    allowed_domains: list[str]
    anonymous_role: str
    session_hours: int
    # How many email patterns grant each role; the patterns themselves stay in the config.
    role_patterns: RoleCounts


class InventoryCheck(BaseModel):
    name: str
    command: str


class InventorySettings(BaseModel):
    refresh_hours: float
    checks: list[InventoryCheck]  # in the config's order
    acl: str  # the external_auth lines brine's Salt account needs (YAML)
    refused: dict[str, str]  # source -> why salt-api refuses to ask for it (configured only)


class SettingsView(BaseModel):
    """The running configuration. Its secrets (passwords, client secrets) stay hidden; check
    commands are shown as written, to every signed-in role."""

    version: str
    salt_api: SaltApiSettings
    presence: PresenceSettings
    fleet: FleetSettings
    jobs_backfill_limit: int
    retention: dict[str, int]  # days each kind of history is kept; 0 = forever
    database: DatabaseSettings
    auth: AuthSettings
    inventory: InventorySettings


class Issue(BaseModel):
    key: str  # stable identity, e.g. "offline:rover-03"
    severity: Literal["critical", "warning", "info"]
    title: str
    detail: str
    since: datetime | None
    minion_id: str | None
    jid: str | None


class Reactor(BaseModel):
    tag: str  # event tag pattern
    sls: list[str]  # reactor SLS files it runs


class Nodegroup(BaseModel):
    name: str
    expression: str  # the compound target that defines it
    members: list[str]


class Nodegroups(BaseModel):
    groups: list[Nodegroup]
    ungrouped: list[str]  # accepted minions in no nodegroup


class StateTop(BaseModel):
    fetched_at: datetime
    minions: dict[str, dict[str, list[str]]]  # minion -> saltenv -> SLS names
    missing: list[str]  # asked, but didn't answer
    skipped: list[str]  # offline per presence, so not asked


class StateFile(BaseModel):
    root: str  # the file_roots directory it lives in
    path: str  # relative to that root


class StateFileContent(BaseModel):
    path: str
    full_path: str
    content: str
    truncated: bool


class FleetLiveView(BaseModel):
    kind: str
    function: str
    fetched_at: datetime
    results: dict[str, Any]  # minion -> what it answered
    missing: list[str]  # asked, but didn't answer in time
    skipped: list[str]  # offline per presence, so not asked


class GrainKey(BaseModel):
    key: str
    minions: int


class GrainValue(BaseModel):
    value: Any  # the grain's value as reported
    text: str  # how it reads in a table (lists joined, objects as JSON)
    minions: list[str]


class GrainDistribution(BaseModel):
    grain: str
    total: int  # accepted minions
    values: list[GrainValue]  # most common first
    missing: list[str]  # accepted minions that don't report this grain


class InventoryKey(BaseModel):
    key: str  # "@packages:rover-agent", or "@rover-cli" for a check's single value
    source: str  # "packages" or the check's name
    name: str  # "" for a check's single value
    kind: Literal["package", "check"]
    minions: int  # accepted minions that have it


class InventoryDistribution(BaseModel):
    key: str
    source: str
    name: str
    kind: Literal["package", "check"]
    total: int  # accepted minions
    values: list[GrainValue]  # newest version first
    missing: list[str]  # answered without it
    # The last answer was an error, and no good read says whether it has it.
    failed: list[str]
    # No answer yet, or the last answer was cut short and doesn't list it (it may be past the
    # cut).
    unknown: list[str]
    oldest_read_at: datetime | None  # of the accepted minions' last good reads
    newest_read_at: datetime | None
    refused: str | None  # why salt-api refuses to ask for this source, if it does


class InventoryChangeView(BaseModel):
    minion_id: str
    source: str
    name: str
    old: str | None  # None: it wasn't there
    new: str | None  # None: it went away
    at: datetime  # the read that found it
    since: datetime | None  # the read before: it changed between the two
    jid: str | None  # the job it was found after, if one job
    user: str | None  # who ran it/them (may be set without jid: several jobs by one person)


class InventoryEntry(BaseModel):
    name: str
    value: str
    since: datetime  # first read with this value


class InventorySource(BaseModel):
    source: str
    kind: Literal["package", "check"]
    read_at: datetime | None  # last good answer: the entries are as of this
    first_read_at: datetime | None
    answered_at: datetime | None  # last answer, good or failed
    error: str | None  # the last answer's error, if it failed
    truncated: bool  # the last good answer was cut short, so some entries may be missing
    refused: str | None  # why salt-api refuses to ask for this source, if it does
    entries: list[InventoryEntry]  # by name


class MinionInventory(BaseModel):
    sources: list[InventorySource]  # packages, then each configured check


class ComparedMinion(BaseModel):
    minion_id: str
    # It and the reference both have a whole read (good, not cut short) of at least one
    # source; the counts are over those sources. False: nothing to compare yet, counts 0.
    read: bool
    sources_compared: list[str]  # those sources: packages, then each check
    different: int  # the same name, another value
    only_reference: int  # the reference has it, this minion doesn't ("missing")
    only_minion: int  # this minion has it, the reference doesn't ("extra")


class FleetComparison(BaseModel):
    reference: str
    reference_sources: list[str]  # the reference's whole reads: what others can be compared on
    minions: list[ComparedMinion]  # every other accepted minion, by ID


class InventoryDifference(BaseModel):
    source: str
    name: str  # "" for a check's single value
    reference: str | None  # None: the reference doesn't have it
    minion: str | None  # None: the minion doesn't have it


class MinionComparison(BaseModel):
    reference: str
    minion: str
    sources_compared: list[str]  # both have a whole read of these: packages, then each check
    differences: list[InventoryDifference]  # by source (as above), then name


class AskRequest(BaseModel):
    minion: str | None = None  # None: every online minion


class AskResult(BaseModel):
    # The online minions asked, or with `queued`, made due for the sweep to ask (BATCH at a
    # time, every few seconds). The answers arrive as they come.
    asked: list[str]
    # The whole fleet was queued for the sweep. False when nobody was asked (stale presence,
    # nobody online), and for one minion: it's asked straight away.
    queued: bool
    failed: dict[str, str] = Field(default_factory=dict)  # source -> why it couldn't be asked
    reason: str | None = None  # why nobody was asked: "no minions are online", "... isn't online"


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
    waiting_runs: list[CatchUpRun]  # commands it missed while offline, to run when it's back


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
    # Of the returns and the catch-ups' answers.
    succeeded: int
    failed: int
    caught_up: int  # minions that missed it and answered a catch-up run of it later
    catching_up: int  # minions that missed it whose catch-up run may still bring an answer


class JobPage(BaseModel):
    jobs: list[JobSummary]
    next_before: str | None  # pass as ?before= for the next (older) page


class CaughtUp(BaseModel):
    jid: str  # the catch-up run's job
    at: datetime  # when brine ran it there


class JobResult(BaseModel):
    minion_id: str
    returned_at: datetime
    success: bool | None
    retcode: int | None
    data: Any
    states: list[StateResult] | None = None  # parsed, for state.apply/highstate/sls jobs
    caught_up: CaughtUp | None = None  # missed the job: this is its answer to a catch-up run


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


class CatchUpRun(BaseModel):
    """A command waiting for an offline minion, or what became of it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    minion_id: str
    source_jid: str  # the job it catches up on
    fun: str
    args: list[Any]
    actor: str
    created_at: datetime
    expires_at: datetime
    state: str  # waiting, sending, sent, expired, cancelled, replaced, refused, failed
    reason: str | None
    sent_jid: str | None  # the job that ran it on the minion
    sent_at: datetime | None
    answered_at: datetime | None = None  # when the minion answered that job (job pages only)


class JobDetail(JobSummary):
    args: list[Any]
    minions: list[str]
    # Expected minions with no return, here or from a catch-up run, and none to come: no
    # catch-up run, or one that came to nothing (cancelled, expired, replaced, refused, failed).
    missing: list[str]
    results: list[JobResult]  # the catch-ups' answers too, marked caught_up
    catch_up: list[CatchUpRun]  # minions that missed it and get it when they're back
    catch_up_of: str | None  # this job caught a minion up on that one


class Key(BaseModel):
    id: str
    key_state: str
    fingerprint: str | None
    first_seen_at: datetime
    last_seen_at: datetime | None
    status: Status | None  # accepted keys only


KeyState = Literal["pending", "accepted", "rejected", "denied"]


class KeyActionRequest(BaseModel):
    state: KeyState  # the state the admin saw; the action is refused if Salt's differs
    fingerprint: str | None = None  # required to accept: the fingerprint the admin checked
    confirm: str | None = None  # the minion's name, typed, for deletes and rejecting accepted keys


class KeyActionResult(BaseModel):
    id: str
    key_state: str  # where the key is now: accepted, rejected, pending (re-sent), or deleted


class Capability(BaseModel):
    allowed: bool | None  # None: salt-api can't be asked right now
    missing: list[str]  # Salt functions the service account's external_auth lacks


class Capabilities(BaseModel):
    manage_keys: Capability
    commands: list[str]  # what the signed-in person may run (patterns); empty: no command box


TargetType = Literal["glob", "list", "compound", "grain", "nodegroup", "pcre"]


class CommandRequest(BaseModel):
    command: str  # as typed: "state.apply webserver test=True", "runners.manage.status"
    target: str = ""
    target_type: TargetType = "glob"
    # Running: the minions the preview showed. Refused if the target matches others by then.
    expect: list[str] | None = None
    # Running: also run it on the offline ones when they're back (catch-up runs).
    catch_up: bool = False


class CommandPreview(BaseModel):
    client: str  # local (minions), runner or wheel (the master)
    fun: str
    qualified: str  # how allowlists name it: runners.manage.status
    args: list[str]
    minions: list[str]  # what the target matches now (minion commands only)
    offline: list[str]  # of those, the ones presence says are offline: they won't answer
    unknown: list[str]  # list targets that aren't accepted minions
    from_cache: bool  # matched from the master's cache (grain, compound, nodegroup)
    catch_up_days: int  # how long a catch-up run would wait for the offline ones


class OrchestrationStep(BaseModel):
    id: str
    function: str  # salt.state, salt.function, salt.runner, salt.wheel
    what: str  # the SLS a salt.state step applies, or the function the others run
    target: str | None
    target_type: str | None
    needs: list[str]  # requisites: step IDs it requires, "watch x", "onfail y", ...
    details: dict[str, Any]  # every other argument


class OrchestrationInput(BaseModel):
    name: str  # a pillar key it reads
    required: bool  # pillar['key']: it can't render without it; pillar.get('key'): optional


class Orchestration(BaseModel):
    sls: str  # what state.orchestrate takes: orch.rollout
    path: str
    steps: list[OrchestrationStep]  # rendered with "<key>" placeholders for required inputs
    error: str | None  # the master couldn't render it
    inputs: list[OrchestrationInput]  # pillar it reads, to give when running it


class Orchestrations(BaseModel):
    saltenv: str
    orchestrations: list[Orchestration]
    truncated: bool  # more .sls files than brine reads in one listing
    can_run: bool  # whether the signed-in person may run runners.state.orchestrate
    listed_at: datetime  # when brine last read the master's .sls files for this listing


class CommandTemplate(BaseModel):
    name: str
    description: str
    target: str
    target_type: str
    command: str
    categories: list[str]
    source: Literal["brine", "master"]  # brine's config, or saltgui_templates on the master
    allowed: bool  # whether the signed-in person may use it (run its command)


class CommandResult(BaseModel):
    client: str
    jid: str | None = None  # minion and runner commands: follow it on the job page
    minions: list[str] = Field(default_factory=list)
    result: Any = None  # runner/wheel: what the master answered
    success: bool | None = None
    waiting: list[str] = Field(default_factory=list)  # offline minions it'll catch up


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
