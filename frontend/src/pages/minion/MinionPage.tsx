import { ChevronLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useMinion } from '@/api/queries'
import type { MinionDetail } from '@/api/types'
import { Card } from '@/components/ui'
import { Tabs } from '@/components/Tabs'
import { type TabDef, useTab } from '@/lib/useTab'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import {
  GrainsPanel,
  HistoryPanel,
  JobsPanel,
  LivePanel,
  TimelinePanel,
} from '@/pages/minion/panels'

const TABS = [
  { key: 'grains', label: 'Grains' },
  { key: 'history', label: 'Grains history' },
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
      <div className="mb-6">
        <h1 className="text-4xl font-semibold tracking-tight break-all">{id}</h1>
        {subtitle && <p className="mt-1 text-lg text-muted">{subtitle}</p>}
      </div>

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
            <Facts minion={minion} now={now} />
            <Card className="mt-4 overflow-hidden sm:mt-6">
              <div className="px-2 sm:px-4">
                <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Minion details" />
              </div>
              {tab === 'grains' && <GrainsPanel minion={minion} now={now} />}
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
