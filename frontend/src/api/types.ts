// Mirrors backend/app/api/schemas.py. Times are ISO-8601 UTC strings; null = never / unknown.

export type MinionStatus = 'online' | 'offline' | 'stale' | 'unknown'

export type Column = { grain: string; label: string }

export type MinionSummary = {
  id: string
  status: MinionStatus
  connected: boolean
  last_seen_at: string | null
  key_state: string
  os: string | null
  salt_version: string | null
  ip: string | null
  grains_at: string | null
  grains_source: 'minion' | 'master_cache' | null
  columns: Record<string, unknown>
  /** When the `@` columns' values are as of: each source's last good read ("packages", a check's name). */
  read_at: Record<string, string | null>
}

export type PresenceInfo = {
  method: 'events' | 'connected' | 'ping' | null
  checked_at: string | null
}

export type Fleet = {
  summary: {
    total: number
    online: number
    offline: number
    stale: number
    unknown: number
    pending_keys: number
  }
  /** The grain columns each minion's `columns` holds (as requested, or the defaults). */
  columns: Column[]
  /** fleet.columns from the server config: the team default. */
  default_columns: Column[]
  presence: PresenceInfo
  minions: MinionSummary[]
}

export type GrainKey = { key: string; minions: number }

export type SystemStatus = {
  version: string
  salt_api: {
    url: string
    connected: boolean
    since: string | null
    error: string | null
    last_event_at: string | null
  }
  presence_method_configured: string
  presence: PresenceInfo
  stale_after_minutes: number
}

/** Hints sent on /api/stream; clients re-fetch whatever they display. */
export type LiveMessage =
  | { type: 'hello' }
  | { type: 'fleet' }
  | { type: 'status' }
  | { type: 'resync' }
  | { type: 'minion'; id: string }
  // Its packages or checks moved (always with a 'minion' hint for it).
  | { type: 'inventory'; id: string }
  | { type: 'job'; jid: string }

export type PresencePoint = { at: string; connected: boolean }

export type MinionJob = {
  jid: string
  fun: string
  started_at: string
  returned_at: string
  success: boolean | null
  retcode: number | null
}

export type MinionDetail = MinionSummary & {
  first_seen_at: string
  grains: Record<string, unknown> | null
  presence_history: PresencePoint[]
  recent_jobs: MinionJob[]
  /** Commands it missed while offline, to run when it's back. */
  waiting_runs: CatchUpRun[]
}

/** A command waiting for an offline minion (a catch-up run), or what became of it. */
export type CatchUpRun = {
  id: number
  minion_id: string
  source_jid: string
  fun: string
  args: unknown[]
  actor: string
  created_at: string
  expires_at: string
  state: 'waiting' | 'sending' | 'sent' | 'expired' | 'cancelled' | 'replaced' | 'refused' | 'failed'
  reason: string | null
  sent_jid: string | null
  sent_at: string | null
}

export type GrainsChange = {
  collected_at: string
  added: Record<string, unknown>
  removed: Record<string, unknown>
  changed: Record<string, { from: unknown; to: unknown }>
}

export type LiveKind = 'pillar' | 'beacons' | 'schedules' | 'mine'

export type LiveView = {
  kind: LiveKind
  function: string
  fetched_at: string
  answered: boolean
  /** Not asked: presence says the minion is offline. */
  offline?: boolean
  data: unknown
}

export type JobSummary = {
  jid: string
  kind: 'local' | 'runner'
  fun: string
  target: string | null
  target_type: string | null
  user: string | null
  started_at: string
  finished_at: string | null
  expected: number
  returned: number
  succeeded: number
  failed: number
}

export type JobPage = { jobs: JobSummary[]; next_before: string | null }

export type StateResult = {
  id: string
  name: string
  function: string
  sls: string | null
  result: boolean | null
  changed: boolean
  comment: string
  duration_ms: number | null
  /** Orchestration steps: the job the step started. */
  jid?: string | null
}

export type JobResult = {
  minion_id: string
  returned_at: string
  success: boolean | null
  retcode: number | null
  data: unknown
  states: StateResult[] | null
}

export type JobDetail = JobSummary & {
  args: unknown[]
  minions: string[]
  missing: string[]
  results: JobResult[]
  /** Minions that missed it and get it when they're back. */
  catch_up: CatchUpRun[]
  /** This job caught a minion up on that one. */
  catch_up_of: string | null
}

export type StateDot = { id: string; function: string; result: boolean | null; changed: boolean }

export type StateRun = {
  minion_id: string
  jid: string
  fun: string
  started_at: string
  returned_at: string
  success: boolean | null
  total: number
  succeeded: number
  failed: number
  changed: number
  states: StateDot[]
}

export type StateRuns = { runs: StateRun[]; never: string[] }

export type KeyState = 'accepted' | 'pending' | 'rejected' | 'denied'

export type Key = {
  id: string
  key_state: KeyState
  fingerprint: string | null
  first_seen_at: string
  last_seen_at: string | null
  status: MinionStatus | null
}

export type KeyAction = 'accept' | 'reject' | 'delete'

export type KeyActionRequest = {
  state: KeyState
  /** Accepting: the fingerprint the admin checked. */
  fingerprint?: string | null
  /** Deleting, or rejecting an accepted key: the minion's name, typed. */
  confirm?: string
}

export type KeyActionResult = { id: string; key_state: KeyState | 'deleted' }

export type Capability = { allowed: boolean | null; missing: string[] }
export type Capabilities = {
  manage_keys: Capability
  /** What the signed-in person may run (patterns like test.*); empty: no command box. */
  commands: string[]
}

export type TargetType = 'glob' | 'list' | 'compound' | 'grain' | 'nodegroup' | 'pcre'

export type CommandRequest = {
  command: string
  target: string
  target_type: TargetType
  /** Running: the minions the preview showed. */
  expect?: string[]
  /** Running: also run it on the offline ones when they're back. */
  catch_up?: boolean
}

export type CommandPreview = {
  client: 'local' | 'runner' | 'wheel'
  fun: string
  qualified: string
  args: string[]
  minions: string[]
  offline: string[]
  unknown: string[]
  from_cache: boolean
  /** How long a catch-up run waits for the offline ones. */
  catch_up_days: number
}

export type CommandTemplate = {
  name: string
  description: string
  target: string
  target_type: TargetType
  command: string
  categories: string[]
  source: 'brine' | 'master'
  /** Whether you may use it (run its command). */
  allowed: boolean
}

export type OrchestrationStep = {
  id: string
  function: string
  what: string
  target: string | null
  target_type: string | null
  needs: string[]
  details: Record<string, unknown>
}

/** A pillar key an orchestration reads; required ones are needed to run it at all. */
export type OrchestrationInput = { name: string; required: boolean }

export type Orchestration = {
  sls: string
  path: string
  /** Rendered with "<key>" placeholders for required inputs. */
  steps: OrchestrationStep[]
  error: string | null
  inputs: OrchestrationInput[]
}

export type Orchestrations = {
  saltenv: string
  orchestrations: Orchestration[]
  truncated: boolean
  can_run: boolean
  /** When brine last read the master's .sls files (it keeps the listing ready in the background). */
  listed_at: string
}

export type CommandResult = {
  client: 'local' | 'runner' | 'wheel'
  jid: string | null
  minions: string[]
  result: unknown
  success: boolean | null
  /** Offline minions it'll run on when they're back. */
  waiting: string[]
}

/** One raw Salt event from /api/events/stream. */
export type SaltEventEntry = {
  seq: number
  received_at: string
  tag: string
  data: Record<string, unknown>
}

export type Reactor = { tag: string; sls: string[] }

export type IssueSeverity = 'critical' | 'warning' | 'info'

export type Issue = {
  key: string
  severity: IssueSeverity
  title: string
  detail: string
  since: string | null
  minion_id: string | null
  jid: string | null
}

export type Settings = {
  version: string
  salt_api: { url: string; username: string; eauth: string; verify_tls: boolean; timeout_seconds: number }
  presence: { method: string; active_method: string | null; poll_seconds: number }
  fleet: { stale_after_minutes: number; grains_refresh_minutes: number; columns: Column[] }
  jobs_backfill_limit: number
  /** Days each kind of history is kept; 0 = forever. */
  retention: { jobs_days: number; history_days: number; audit_days: number }
  database: { backend: string; url: string }
  auth: {
    provider: 'oidc' | 'none'
    issuer: string | null
    display_name: string
    configured: boolean
    allowed_domains: string[]
    anonymous_role: Role
    session_hours: number
    role_patterns: Record<Role, number>
  }
  inventory: {
    refresh_hours: number
    /** In the config's order. */
    checks: { name: string; command: string }[]
    /** The external_auth lines brine's Salt account needs (YAML). */
    acl: string
    /** Source -> why salt-api refuses to ask for it (configured sources only). */
    refused: Record<string, string>
  }
}

export type GrainValue = {
  value: unknown
  /** How it reads in a table (lists joined, objects as JSON). */
  text: string
  minions: string[]
}

export type GrainDistribution = {
  grain: string
  total: number
  values: GrainValue[]
  missing: string[]
}

export type InventoryKind = 'package' | 'check'

/** A package or a check's entry the fleet has, for the explorer's picker. */
export type InventoryKey = {
  /** `@packages:rover-agent`, or `@rover-cli` for a check's single value. */
  key: string
  /** "packages" or the check's name. */
  source: string
  /** "" for a check's single value. */
  name: string
  kind: InventoryKind
  /** Accepted minions that have it. */
  minions: number
}

export type InventoryDistribution = {
  key: string
  source: string
  name: string
  kind: InventoryKind
  /** Accepted minions. */
  total: number
  /** Newest version first. */
  values: GrainValue[]
  /** Answered without it. */
  missing: string[]
  /** The last answer was an error, and no good read says whether it has it. */
  failed: string[]
  /** No answer yet, or the last answer was cut short and doesn't list it. */
  unknown: string[]
  /** Of the accepted minions' last good reads. */
  oldest_read_at: string | null
  newest_read_at: string | null
  /** Why salt-api refuses to ask for this source, if it does. */
  refused: string | null
}

export type InventoryChange = {
  minion_id: string
  source: string
  name: string
  /** null: it wasn't there. */
  old: string | null
  /** null: it went away. */
  new: string | null
  /** The read that found it. */
  at: string
  /** The read before: it changed between the two. */
  since: string | null
  /** The job it was found after, if one job. */
  jid: string | null
  /** Who ran it, or them: set without `jid` for several jobs by one person. */
  user: string | null
}

export type InventoryEntry = {
  name: string
  value: string
  /** First read with this value. */
  since: string
}

export type InventorySource = {
  source: string
  kind: InventoryKind
  /** Last good answer: the entries are as of this. */
  read_at: string | null
  first_read_at: string | null
  /** Last answer, good or failed. */
  answered_at: string | null
  /** The last answer's error, if it failed. */
  error: string | null
  /** The last good answer was cut short, so some entries may be missing. */
  truncated: boolean
  /** Why salt-api refuses to ask for this source, if it does. */
  refused: string | null
  /** By name. */
  entries: InventoryEntry[]
}

/** Packages, then each configured check. */
export type MinionInventory = { sources: InventorySource[] }

export type ComparedMinion = {
  minion_id: string
  /** It and the reference both have a whole read of at least one source (else the counts are 0). */
  read: boolean
  /** Those sources, which the counts are over: packages, then each check. */
  sources_compared: string[]
  /** The same name, another value. */
  different: number
  /** The reference has it, this minion doesn't ("missing"). */
  only_reference: number
  /** This minion has it, the reference doesn't ("extra"). */
  only_minion: number
}

/** How every other accepted minion differs from the reference, by ID. */
export type FleetComparison = {
  reference: string
  /** The reference's whole reads: what the others can be compared on. */
  reference_sources: string[]
  minions: ComparedMinion[]
}

export type InventoryDifference = {
  source: string
  /** "" for a check's single value. */
  name: string
  /** null: the reference doesn't have it. */
  reference: string | null
  /** null: the minion doesn't have it. */
  minion: string | null
}

export type MinionComparison = {
  reference: string
  minion: string
  /** Both have a whole read of these: packages, then each check. */
  sources_compared: string[]
  /** By source (as above), then name. */
  differences: InventoryDifference[]
}

export type AskResult = {
  /** The minions asked, or with `queued`, queued for brine's sweep to read. */
  asked: string[]
  /** The whole fleet was queued. False when nobody was asked, and for one minion (asked straight away). */
  queued: boolean
  /** Source -> why it couldn't be asked. */
  failed: Record<string, string>
  /** Why nobody was asked: "no minions are online", "rover-03 isn't online". */
  reason: string | null
}

export type Nodegroups = {
  groups: { name: string; expression: string; members: string[] }[]
  ungrouped: string[]
}

export type StateTop = {
  fetched_at: string
  minions: Record<string, Record<string, string[]>>
  missing: string[]
  skipped: string[]
}

export type StateFile = { root: string; path: string }

export type StateFileContent = { path: string; full_path: string; content: string; truncated: boolean }

export type FleetLiveView = {
  kind: 'schedules' | 'beacons'
  function: string
  fetched_at: string
  results: Record<string, unknown>
  missing: string[]
  skipped: string[]
}

export type Role = 'viewer' | 'operator' | 'admin'

export type User = {
  email: string
  name: string
  picture: string | null
  role: Role
  provider: 'oidc' | 'none'
}

export type AuthInfo = { provider: 'oidc' | 'none'; display_name: string }

export type AuditEntry = {
  id: number
  at: string
  actor: string
  action: string
  target: string | null
  detail: Record<string, unknown> | null
}

export type AuditPage = { entries: AuditEntry[]; next_before: number | null }
