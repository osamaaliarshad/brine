import { CircleAlert, Unplug } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useFleet, useSystemStatus } from '@/api/queries'
import type { SystemStatus } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { baseColumns, grainColumn } from '@/pages/fleet/columns'
import { FleetTable } from '@/pages/fleet/FleetTable'
import { FleetToolbar } from '@/pages/fleet/FleetToolbar'
import {
  distinctValues,
  filterMinions,
  type FleetView,
  latestGrainsAt,
  PAGE_SIZE,
  paginate,
  paramsFromView,
  sortMinions,
  viewFromParams,
} from '@/pages/fleet/model'
import { StatCards } from '@/pages/fleet/StatCards'

const HIDDEN_COLUMNS_KEY = 'brine-fleet-hidden-columns'

function loadHidden(): Set<string> {
  try {
    const saved = JSON.parse(localStorage.getItem(HIDDEN_COLUMNS_KEY) ?? '[]') as unknown
    return new Set(Array.isArray(saved) ? saved.filter((k): k is string => typeof k === 'string') : [])
  } catch {
    return new Set()
  }
}

function saveHidden(hidden: Set<string>) {
  try {
    localStorage.setItem(HIDDEN_COLUMNS_KEY, JSON.stringify([...hidden]))
  } catch {
    // storage unavailable: the choice lasts for this page load only
  }
}

function ConnectionBanner({ status, now }: { status: SystemStatus | undefined; now: number }) {
  if (!status || status.salt_api.connected) return null
  return (
    <div
      role="status"
      className="mb-6 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm"
    >
      <Unplug className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <div>
        <span className="font-medium">brine can't reach salt-api</span>
        {status.salt_api.since && (
          <span className="text-muted" title={formatAbsolute(status.salt_api.since)}>
            {' '}
            (since {formatRelative(status.salt_api.since, now)})
          </span>
        )}
        . Showing the last known state; statuses turn stale after {status.stale_after_minutes} minutes.
        {status.salt_api.error && <div className="mt-1 text-muted">{status.salt_api.error}</div>}
      </div>
    </div>
  )
}

export function FleetPage() {
  const fleetQuery = useFleet()
  const statusQuery = useSystemStatus()
  const fleet = fleetQuery.data
  const now = useNow()
  const [params, setParams] = useSearchParams()
  const view = viewFromParams(params)
  const [hidden, setHidden] = useState(loadHidden)

  const update = (patch: Partial<FleetView>) => {
    // Any change other than paging starts again from page 1.
    const next = { ...view, page: 1, ...patch }
    setParams(paramsFromView(next), { replace: true })
  }

  const groupColumn = fleet?.columns[0]
  // Plain recomputation on each render: fleets are at most a few thousand rows, and renders
  // are rare (data changes, plus a 15s clock tick).
  const groupValues = fleet && groupColumn ? distinctValues(fleet.minions, groupColumn.grain) : []
  const allColumns = [
    ...baseColumns(),
    ...(fleet?.columns ?? []).map((c) => grainColumn(c.grain, c.label)),
  ]
  const columns = allColumns.filter((c) => !hidden.has(c.key))
  const toggleable = allColumns
    .filter((c) => c.key !== 'id' && c.key !== 'connection')
    .map((c) => ({ key: c.key, label: c.label }))

  const shown = sortMinions(
    filterMinions(fleet?.minions ?? [], view, groupColumn?.grain),
    view.sort,
    view.dir,
  )
  const paged = paginate(shown, view.page)

  const presence = fleet?.presence
  const grainsAt = fleet ? latestGrainsAt(fleet.minions) : null

  return (
    <>
      <PageHeader
        title="Fleet"
        subtitle="Your minions, at a glance."
        actions={
          fleet && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              <span title={formatAbsolute(presence?.checked_at)}>
                Presence checked {formatRelative(presence?.checked_at, now)}
                {presence?.method && presence.method !== 'events' && ` (via ${presence.method})`}
              </span>
              <span aria-hidden>•</span>
              <span title={formatAbsolute(grainsAt)}>
                Grains updated{' '}
                <span className="rounded-md bg-surface-2 px-1.5 py-0.5">
                  {formatRelative(grainsAt, now)}
                </span>
              </span>
            </div>
          )
        }
      />

      <ConnectionBanner status={statusQuery.data} now={now} />

      <StatCards summary={fleet?.summary} />

      <Card className="mt-4 overflow-hidden sm:mt-6">
        <FleetToolbar
          view={view}
          fleet={fleet}
          groupColumn={groupColumn}
          groupValues={groupValues}
          toggleableColumns={toggleable}
          hiddenColumns={hidden}
          onChange={update}
          onToggleColumn={(key) => {
            const next = new Set(hidden)
            if (next.has(key)) next.delete(key)
            else next.add(key)
            setHidden(next)
            saveHidden(next)
          }}
          onRefresh={() => {
            void fleetQuery.refetch()
            void statusQuery.refetch()
          }}
          refreshing={fleetQuery.isFetching}
        />

        {fleetQuery.isError ? (
          <div className="flex flex-col items-center gap-3 border-t px-6 py-12 text-center">
            <CircleAlert className="size-6 text-danger" aria-hidden />
            <p>Couldn't load the fleet: {fleetQuery.error.message}</p>
            <button
              type="button"
              className="rounded-lg border px-3 py-1.5 text-sm hover:bg-surface-2"
              onClick={() => void fleetQuery.refetch()}
            >
              Try again
            </button>
          </div>
        ) : (
          <FleetTable
            columns={columns}
            minions={paged.items}
            view={view}
            now={now}
            total={shown.length}
            page={paged.page}
            pages={paged.pages}
            pageSize={PAGE_SIZE}
            loading={fleetQuery.isPending}
            onSort={(key) =>
              update({ sort: key, dir: view.sort === key && view.dir === 'asc' ? 'desc' : 'asc' })
            }
            onPage={(page) => update({ page })}
            empty={
              fleetQuery.isPending
                ? 'Loading the fleet…'
                : fleet?.minions.length
                  ? 'No minions match these filters.'
                  : 'No minions yet. brine adds them as soon as salt-api reports accepted keys.'
            }
          />
        )}
      </Card>
    </>
  )
}
