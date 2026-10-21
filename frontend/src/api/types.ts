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
}

export type GrainDistribution = {
  grain: string
  total: number
  values: { value: unknown; text: string; minions: string[] }[]
  missing: string[]
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
