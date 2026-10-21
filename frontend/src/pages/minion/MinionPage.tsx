import { ChevronLeft, TerminalSquare } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useCapabilities, useMe, useMinion } from '@/api/queries'
import type { KeyState, MinionDetail } from '@/api/types'
import { KeyActionDialog, type KeyActionTarget } from '@/components/KeyActionDialog'
import { Card } from '@/components/ui'
import { Tabs } from '@/components/Tabs'
import { type TabDef, useTab } from '@/lib/useTab'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { commandLine } from '@/pages/jobs/format'
import { KeyActions } from '@/pages/keys/KeyActions'
import { ACTIONS_FOR, describeResult } from '@/pages/keys/rules'
import {
  GrainsPanel,
  HistoryPanel,
  JobsPanel,
  LivePanel,
  TimelinePanel,
} from '@/pages/minion/panels'
import { PackagesPanel } from '@/pages/minion/PackagesPanel'

const TABS = [
  { key: 'grains', label: 'Grains' },
  { key: 'packages', label: 'Packages' },
  { key: 'history', label: 'History' },
  { key: 'jobs', label: 'Jobs' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'pillar', label: 'Pillar' },
  { key: 'beacons', label: 'Beacons' },
  { key: 'schedules', label: 'Schedules' },
  { key: 'mine', label: 'Mine' },
] as const satisfies readonly TabDef<string>[]

type TabKey = (typeof TABS)[number]['key']

function Fact({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 text-lg font-medium" title={title}>
        {children}
      </div>
    </Card>
  )
}

function Facts({ minion, now }: { minion: MinionDetail; now: number }) {
  const lastChange = minion.presence_history[0]
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <Fact label="Connection">
        <ConnectionCell minion={minion} now={now} />
      </Fact>
      <Fact label={minion.connected ? 'Online since' : 'Offline since'} title={formatAbsolute(lastChange?.at)}>
        {lastChange ? formatRelative(lastChange.at, now) : '—'}
      </Fact>
      <Fact label="Grains as of" title={formatAbsolute(minion.grains_at)}>
        {minion.grains_source === 'master_cache' ? 'Unknown (master cache)' : formatRelative(minion.grains_at, now)}
      </Fact>
      <Fact label="First seen by brine" title={formatAbsolute(minion.first_seen_at)}>
        {formatRelative(minion.first_seen_at, now)}
      </Fact>
    </div>
  )
}

export function MinionPage() {
  const { id = '' } = useParams()
  const now = useNow()
  const query = useMinion(id)
  const [tab, setTab] = useTab<TabKey>(TABS, 'grains')
  const minion = query.data
  const navigate = useNavigate()
  const role = useMe().data?.role
  const isAdmin = role === 'admin'
  const capabilities = useCapabilities(!!role && role !== 'viewer')
  const canManage = isAdmin && capabilities.data?.manage_keys.allowed !== false
  const canRun = !!capabilities.data?.commands.length
  const [target, setTarget] = useState<KeyActionTarget | null>(null)
  const keyState = minion && minion.key_state in ACTIONS_FOR ? (minion.key_state as KeyState) : null

  const subtitle = minion
    ? [minion.ip, minion.os, minion.salt_version && `Salt ${minion.salt_version}`, minion.key_state !== 'accepted' && `key ${minion.key_state}`]
        .filter(Boolean)
        .join(' · ')
    : ''

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted">
        <Link to="/" className="inline-flex items-center gap-1 hover:text-fg">
          <ChevronLeft className="size-4" aria-hidden />
          Fleet
        </Link>
      </nav>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-4xl font-semibold tracking-tight break-all">{id}</h1>
          {subtitle && <p className="mt-1 text-lg text-muted">{subtitle}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {canRun && minion?.key_state === 'accepted' && (
            <Link
              to={`/run?type=list&target=${encodeURIComponent(id)}`}
              className="flex h-10 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-surface-2"
            >
              <TerminalSquare className="size-4 text-muted" aria-hidden />
              Run command
            </Link>
          )}
          {canManage && keyState && (
            <KeyActions labelled k={{ id, key_state: keyState, fingerprint: null }} onPick={setTarget} />
          )}
        </div>
      </div>
      {target && (
        <KeyActionDialog
          target={target}
          onClose={() => setTarget(null)}
          onDone={(result) => {
            if (result.key_state !== 'accepted')
              void navigate('/keys', { state: { notice: describeResult(result) } })
          }}
        />
      )}

      {query.isPending ? (
        <p className="text-muted">Loading {id}…</p>
      ) : query.isError ? (
        <Card className="px-6 py-10 text-center">
          {query.error instanceof ApiError && query.error.status === 404 ? (
            <>
              brine doesn't know a minion called <span className="font-mono">{id}</span>.{' '}
              <Link to="/" className="text-accent hover:underline">
                Back to the fleet
              </Link>
            </>
          ) : (
            <>Couldn't load {id}: {query.error.message}</>
          )}
        </Card>
      ) : (
        minion && (
          <>
            {minion.waiting_runs.length > 0 && (
              <div className="mb-4 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm sm:mb-6">
                <div className="font-medium">
                  {minion.waiting_runs.length} command{minion.waiting_runs.length === 1 ? '' : 's'} waiting for {id} to
                  come back
                </div>
                <ul className="mt-1.5 flex flex-col gap-1">
                  {minion.waiting_runs.map((run) => (
                    <li key={run.id} className="text-muted">
                      <code className="font-mono text-fg">{commandLine(run.fun, run.args)}</code> · from{' '}
                      <Link to={`/jobs/${run.source_jid}`} className="text-accent hover:underline">
                        this job
                      </Link>{' '}
                      by {run.actor}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Facts minion={minion} now={now} />
            <Card className="mt-4 overflow-hidden sm:mt-6">
              <div className="px-2 sm:px-4">
                <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Minion details" />
              </div>
              {tab === 'grains' && <GrainsPanel minion={minion} now={now} />}
              {tab === 'packages' && <PackagesPanel minion={minion} now={now} />}
              {tab === 'history' && <HistoryPanel minionId={id} now={now} />}
              {tab === 'jobs' && <JobsPanel minion={minion} now={now} />}
              {tab === 'timeline' && <TimelinePanel minion={minion} now={now} />}
              {(tab === 'pillar' || tab === 'beacons' || tab === 'schedules' || tab === 'mine') && (
                <LivePanel key={tab} minionId={id} kind={tab} now={now} />
              )}
            </Card>
          </>
        )
      )}
    </>
  )
}
