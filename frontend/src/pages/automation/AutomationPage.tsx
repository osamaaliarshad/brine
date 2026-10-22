import { RefreshCw } from 'lucide-react'
import { useAutomation, useFleet } from '@/api/queries'
import type { MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { PageHeader } from '@/components/PageHeader'
import { Tabs } from '@/components/Tabs'
import { Badge, Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { useTab } from '@/lib/useTab'
import { beaconRows, scheduleRows } from '@/pages/automation/schedule'

const TABS = [
  { key: 'schedules', label: 'Schedules' },
  { key: 'beacons', label: 'Beacons' },
] as const

function Enabled({ on }: { on: boolean }) {
  return on ? (
    <span className="text-online">Enabled</span>
  ) : (
    <Badge tone="warn">Disabled</Badge>
  )
}

function View({ kind, now, statusOf }: { kind: 'schedules' | 'beacons'; now: number; statusOf: Record<string, MinionStatus> }) {
  const query = useAutomation(kind)
  const data = query.data
  const schedules = kind === 'schedules' && data ? scheduleRows(data.results) : []
  const beacons = kind === 'beacons' && data ? beaconRows(data.results) : []
  const count = kind === 'schedules' ? schedules.length : beacons.length

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 sm:px-6">
        <p className="text-sm text-muted">
          {kind === 'schedules'
            ? "Every minion's scheduled jobs (schedule.list), asked live."
            : "Every minion's beacons (beacons.list), asked live."}
        </p>
        <div className="flex items-center gap-3 text-sm text-muted">
          {data && <span title={formatAbsolute(data.fetched_at)}>Asked {formatRelative(data.fetched_at, now)}</span>}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="flex h-8 items-center gap-1.5 rounded-lg border px-2.5 hover:bg-surface-2"
          >
            <RefreshCw className={cn('size-3.5', query.isFetching && 'animate-spin')} aria-hidden />
            Refresh
          </button>
        </div>
      </div>
      {query.isPending ? (
        <div className="border-t px-6 py-12 text-center text-muted">Asking the minions…</div>
      ) : query.isError ? (
        <div className="border-t px-6 py-12 text-center text-muted">Couldn't ask the minions: {query.error.message}</div>
      ) : count === 0 ? (
        <div className="border-t px-6 py-12 text-center text-muted">
          No {kind} on any minion that answered.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
              {kind === 'schedules' ? (
                <tr>
                  <th className="px-4 py-3 font-medium sm:pl-6">Minion</th>
                  <th className="px-4 py-3 font-medium">Job</th>
                  <th className="px-4 py-3 font-medium">Runs</th>
                  <th className="px-4 py-3 font-medium">When</th>
                  <th className="px-4 py-3 font-medium">State</th>
                </tr>
              ) : (
                <tr>
                  <th className="px-4 py-3 font-medium sm:pl-6">Minion</th>
                  <th className="px-4 py-3 font-medium">Beacon</th>
                  <th className="px-4 py-3 font-medium">Config</th>
                  <th className="px-4 py-3 font-medium">State</th>
                </tr>
              )}
            </thead>
            <tbody>
              {kind === 'schedules'
                ? schedules.map((r) => (
                    <tr key={`${r.minion}/${r.name}`} className="border-t align-middle">
                      <td className="px-4 py-3 sm:pl-6">
                        <MinionChip id={r.minion} status={statusOf[r.minion]} />
                      </td>
                      <td className="px-4 py-3 font-medium">{r.name}</td>
                      <td className="px-4 py-3 font-mono text-[13px]">
                        {r.fun}
                        {r.args && <span className="text-muted"> {r.args}</span>}
                      </td>
                      <td className="px-4 py-3">{r.when}</td>
                      <td className="px-4 py-3">
                        <Enabled on={r.enabled} />
                      </td>
                    </tr>
                  ))
                : beacons.map((r) => (
                    <tr key={`${r.minion}/${r.name}`} className="border-t align-middle">
                      <td className="px-4 py-3 sm:pl-6">
                        <MinionChip id={r.minion} status={statusOf[r.minion]} />
                      </td>
                      <td className="px-4 py-3 font-medium">{r.name}</td>
                      <td className="max-w-md truncate px-4 py-3 font-mono text-[13px]" title={r.config}>
                        {r.config || '—'}
                      </td>
                      <td className="px-4 py-3">
                        <Enabled on={r.enabled} />
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.missing.length > 0 && (
        <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">Didn't answer: {data.missing.join(', ')}</p>
      )}
      {data && data.skipped.length > 0 && (
        <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">
          Offline, not asked: {data.skipped.join(', ')}
        </p>
      )}
    </>
  )
}

export function AutomationPage() {
  const now = useNow()
  const [tab, setTab] = useTab(TABS, 'schedules')
  const fleet = useFleet()
  const statusOf = Object.fromEntries((fleet.data?.minions ?? []).map((m) => [m.id, m.status]))
  return (
    <>
      <PageHeader title="Automation" subtitle="What runs on its own: schedules and beacons across the fleet." />
      <Card fill className="overflow-hidden">
        <div className="px-2 sm:px-4">
          <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Automation views" />
        </div>
        <View key={tab} kind={tab} now={now} statusOf={statusOf} />
      </Card>
    </>
  )
}
