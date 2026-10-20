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
