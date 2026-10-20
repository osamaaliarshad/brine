import { CircleAlert, Unplug } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { attentionCount, useFleet, useIssues, useSystemStatus } from '@/api/queries'
import type { SystemStatus } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { Tabs } from '@/components/Tabs'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { useTab } from '@/lib/useTab'
import { ColumnsMenu } from '@/pages/fleet/ColumnsMenu'
import { FleetCards } from '@/pages/fleet/FleetCards'
import { GrainsExplorer } from '@/pages/fleet/GrainsExplorer'
import { NodegroupsView } from '@/pages/fleet/NodegroupsView'
import {
  addGrain,
  type ColumnPrefs,
  DEFAULT_PREFS,
  loadPrefs,
  savePrefs,
} from '@/pages/fleet/columnPrefs'
import { baseColumns, grainColumn } from '@/pages/fleet/columns'
import { FleetTable } from '@/pages/fleet/FleetTable'
import { CONTROL, FleetToolbar } from '@/pages/fleet/FleetToolbar'
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
        . Showing the last known state; statuses turn stale after {status.stale_after_minutes}{' '}
        minutes.
        {status.salt_api.error && <div className="mt-1 text-muted">{status.salt_api.error}</div>}
      </div>
    </div>
  )
}

const FLEET_TABS = [
  { key: 'minions', label: 'Minions' },
  { key: 'grains', label: 'Grains' },
  { key: 'nodegroups', label: 'Nodegroups' },
] as const

export function FleetPage() {
  const [prefs, setPrefsState] = useState<ColumnPrefs>(loadPrefs)
  const setPrefs = (next: ColumnPrefs) => {
    setPrefsState(next)
    savePrefs(next)
  }
  const fleetQuery = useFleet(prefs.grains)
  const statusQuery = useSystemStatus()
  const issuesQuery = useIssues()
  const fleet = fleetQuery.data
  const now = useNow()
  const wide = useMediaQuery('(min-width: 640px)')
  const [params, setParams] = useSearchParams()
  const view = viewFromParams(params)
  const [tab, setTab] = useTab(FLEET_TABS, 'minions')
  const statusOf = Object.fromEntries((fleet?.minions ?? []).map((m) => [m.id, m.status]))

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
  const hidden = new Set(prefs.hidden)
  const columns = allColumns.filter((c) => !hidden.has(c.key))

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

      <StatCards summary={fleet?.summary} attention={attentionCount(issuesQuery.data)} />

      <Card className="mt-4 overflow-hidden sm:mt-6">
        <div className="px-2 sm:px-4">
          <Tabs tabs={FLEET_TABS} active={tab} onSelect={setTab} label="Fleet views" />
        </div>
        {tab === 'grains' && (
          <GrainsExplorer
            statusOf={statusOf}
            columnGrains={(fleet?.columns ?? []).map((c) => c.grain)}
            onAddColumn={(grain) =>
              setPrefs({
                ...prefs,
                grains: addGrain(
                  prefs.grains ?? (fleet?.default_columns ?? []).map((c) => c.grain),
                  grain,
                ),
              })
            }
          />
        )}
        {tab === 'nodegroups' && <NodegroupsView statusOf={statusOf} />}
        {tab === 'minions' && (
          <>
            <FleetToolbar
              view={view}
              fleet={fleet}
              groupColumn={groupColumn}
              groupValues={groupValues}
              columnsMenu={
                <ColumnsMenu
                  grainColumns={fleet?.columns ?? []}
                  builtins={[{ key: 'os', label: 'OS / Salt' }]}
                  hidden={hidden}
                  customized={prefs.grains !== null}
                  buttonClassName={CONTROL}
                  onToggleBuiltin={(key) =>
                    setPrefs({
                      ...prefs,
                      hidden: hidden.has(key)
                        ? prefs.hidden.filter((k) => k !== key)
                        : [...prefs.hidden, key],
                    })
                  }
                  onChangeGrains={(grains) => setPrefs({ ...prefs, grains })}
                  onReset={() => setPrefs({ ...prefs, grains: DEFAULT_PREFS.grains })}
                />
              }
              onChange={update}
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
                compact={
                  wide ? undefined : (
                    <FleetCards
                      minions={paged.items}
                      columns={fleet?.columns ?? []}
                      showOs={!hidden.has('os')}
                      now={now}
                    />
                  )
                }
                onSort={(key) =>
                  update({
                    sort: key,
                    dir: view.sort === key && view.dir === 'asc' ? 'desc' : 'asc',
                  })
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
          </>
        )}
      </Card>
    </>
  )
}
