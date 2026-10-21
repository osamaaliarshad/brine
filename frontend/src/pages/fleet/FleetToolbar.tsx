import { RefreshCw, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Fleet, MinionStatus } from '@/api/types'
import { StatusDot } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { FleetView, StatusFilter } from '@/pages/fleet/model'

export const CONTROL =
  'flex h-10 items-center gap-2 rounded-lg border bg-surface px-3 text-sm text-fg transition-colors hover:bg-surface-2'

function StatusTabs({ view, summary, onChange }: {
  view: FleetView
  summary: Fleet['summary'] | undefined
  onChange: (status: StatusFilter) => void
}) {
  const tabs: { value: StatusFilter; label: string; count?: number; dot?: MinionStatus }[] = [
    { value: 'all', label: 'All minions', count: summary?.total },
    { value: 'online', label: 'Online', count: summary?.online, dot: 'online' },
    { value: 'offline', label: 'Offline', count: summary?.offline, dot: 'offline' },
  ]
  // Only offer the "something's off" filters when they'd show anything.
  if (summary?.stale || view.status === 'stale')
    tabs.push({ value: 'stale', label: 'Stale', count: summary?.stale, dot: 'stale' })
  if (summary?.unknown || view.status === 'unknown')
    tabs.push({ value: 'unknown', label: 'Unknown', count: summary?.unknown, dot: 'unknown' })

  return (
    <div role="tablist" aria-label="Filter by status" className="flex flex-wrap gap-2">
      {tabs.map((tab) => {
        const active = view.status === tab.value
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cn(
              CONTROL,
              active && 'border-accent bg-accent/10 hover:bg-accent/15',
            )}
          >
            {tab.dot && <StatusDot status={tab.dot} />}
            {tab.label}
            {tab.count !== undefined && (
              <span className="rounded-md bg-surface-2 px-1.5 text-xs tabular-nums text-muted">
                {tab.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

export function FleetToolbar({
  view,
  fleet,
  columnsMenu,
  onChange,
  onRefresh,
  refreshing,
}: {
  view: FleetView
  fleet: Fleet | undefined
  columnsMenu: ReactNode
  onChange: (patch: Partial<FleetView>) => void
  onRefresh: () => void
  refreshing: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 p-3 sm:p-4">
      <StatusTabs view={view} summary={fleet?.summary} onChange={(status) => onChange({ status })} />

      <label className={cn(CONTROL, 'min-w-0 flex-1 basis-56 cursor-text hover:bg-surface')}>
        <Search className="size-4 shrink-0 text-muted" aria-hidden />
        <input
          type="search"
          value={view.q}
          onChange={(e) => onChange({ q: e.target.value })}
          placeholder="Search minions, IPs, or grains…"
          aria-label="Search minions"
          className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted"
        />
      </label>

      {columnsMenu}

      <button
        type="button"
        className={cn(CONTROL, 'px-2.5')}
        onClick={onRefresh}
        aria-label="Refresh"
        title="Refresh"
      >
        <RefreshCw className={cn('size-4', refreshing && 'animate-spin')} aria-hidden />
      </button>
    </div>
  )
}
