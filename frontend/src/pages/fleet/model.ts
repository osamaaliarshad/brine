import type { MinionStatus, MinionSummary } from '@/api/types'

export type StatusFilter = 'all' | MinionStatus
export type SortDir = 'asc' | 'desc'
/** `id`, `connection`, `os`, or `col:<grain>` for a configured grain column. */
export type SortKey = string

export type FleetView = {
  status: StatusFilter
  q: string
  sort: SortKey
  dir: SortDir
  page: number
}

export const PAGE_SIZE = 25

export const DEFAULT_VIEW: FleetView = {
  status: 'all',
  q: '',
  sort: 'id',
  dir: 'asc',
  page: 1,
}

/** Grain values as display text: null for missing, lists joined, objects as JSON. */
export function cellText(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
  if (Array.isArray(value)) return value.map((v) => cellText(v) ?? '').join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function matchesSearch(minion: MinionSummary, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const haystack = [
    minion.id,
    minion.ip,
    minion.os,
    minion.salt_version,
    ...Object.values(minion.columns).map(cellText),
  ]
  return haystack.some((value) => value?.toLowerCase().includes(q))
}

export function filterMinions(minions: MinionSummary[], view: Pick<FleetView, 'status' | 'q'>): MinionSummary[] {
  return minions.filter((m) => (view.status === 'all' || m.status === view.status) && matchesSearch(m, view.q))
}

// Online first, then the ones that need a look, then offline.
const STATUS_RANK: Record<MinionStatus, number> = { online: 0, stale: 1, unknown: 2, offline: 3 }

function compareText(a: string | null, b: string | null): number {
  if (a === b) return 0
  if (a === null) return 1 // missing values sort last
  if (b === null) return -1
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
}

export function sortMinions(minions: MinionSummary[], sort: SortKey, dir: SortDir): MinionSummary[] {
  const sign = dir === 'asc' ? 1 : -1
  const compare = (a: MinionSummary, b: MinionSummary): number => {
    if (sort === 'connection') {
      const byStatus = STATUS_RANK[a.status] - STATUS_RANK[b.status]
      if (byStatus !== 0) return byStatus
      // Most recently seen first within a status.
      return compareText(b.last_seen_at, a.last_seen_at)
    }
    if (sort === 'os') return compareText(a.os, b.os)
    if (sort.startsWith('col:')) {
      const grain = sort.slice(4)
      return compareText(cellText(a.columns[grain]), cellText(b.columns[grain]))
    }
    return compareText(a.id, b.id)
  }
  return [...minions].sort((a, b) => sign * compare(a, b) || compareText(a.id, b.id))
}

export function paginate<T>(items: T[], page: number, size = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(items.length / size))
  const current = Math.min(Math.max(1, page), pages)
  return { items: items.slice((current - 1) * size, current * size), page: current, pages }
}

/** Most recent grains collection across the fleet ("Grains updated 4m ago"). */
export function latestGrainsAt(minions: MinionSummary[]): string | null {
  let latest: string | null = null
  for (const m of minions) {
    if (m.grains_at && (latest === null || m.grains_at > latest)) latest = m.grains_at
  }
  return latest
}

export function viewFromParams(params: URLSearchParams): FleetView {
  const status = params.get('status')
  const dir = params.get('dir')
  const page = Number(params.get('page'))
  return {
    status: (['online', 'offline', 'stale', 'unknown'] as const).find((s) => s === status) ?? 'all',
    q: params.get('q') ?? '',
    sort: params.get('sort') ?? DEFAULT_VIEW.sort,
    dir: dir === 'desc' ? 'desc' : 'asc',
    page: Number.isInteger(page) && page > 0 ? page : 1,
  }
}

/** Only non-default values go in the URL, so a plain /fleet link stays plain. */
export function paramsFromView(view: FleetView): URLSearchParams {
  const params = new URLSearchParams()
  if (view.status !== DEFAULT_VIEW.status) params.set('status', view.status)
  if (view.q) params.set('q', view.q)
  if (view.sort !== DEFAULT_VIEW.sort) params.set('sort', view.sort)
  if (view.dir !== DEFAULT_VIEW.dir) params.set('dir', view.dir)
  if (view.page !== 1) params.set('page', String(view.page))
  return params
}
