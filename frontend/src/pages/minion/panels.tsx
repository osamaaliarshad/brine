import { CircleCheck, CircleX, RefreshCw, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  GRAINS_HISTORY_LIMIT,
  MINION_CHANGES_LIMIT,
  useGrainsHistory,
  useInventoryChanges,
  useMinionLive,
} from '@/api/queries'
import type { GrainsChange, InventoryChange, LiveKind, MinionDetail } from '@/api/types'
import { JsonTree } from '@/components/JsonView'
import { Badge, StatusDot } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatDuration, formatRelative } from '@/lib/time'
import { ChangeList, FoundWhen } from '@/pages/fleet/ChangeList'

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-6 py-12 text-center text-muted">{children}</div>
}

export function GrainsPanel({ minion, now }: { minion: MinionDetail; now: number }) {
  const [q, setQ] = useState('')
  if (!minion.grains) return <Empty>brine hasn't received grains from {minion.id} yet.</Empty>
  const needle = q.trim().toLowerCase()
  const entries = Object.entries(minion.grains)
    .filter(([k, v]) => !needle || k.toLowerCase().includes(needle) || JSON.stringify(v).toLowerCase().includes(needle))
    .sort(([a], [b]) => a.localeCompare(b))

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b p-4">
        <label className="flex h-10 min-w-0 flex-1 basis-60 items-center gap-2 rounded-lg border bg-bg px-3">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter grains by name or value…"
            aria-label="Filter grains"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
        <span className="text-sm text-muted" title={formatAbsolute(minion.grains_at)}>
          {minion.grains_source === 'master_cache' ? (
            <>
              From the master's cache, <Badge>age unknown</Badge>
            </>
          ) : (
            <>As of {formatRelative(minion.grains_at, now)}, from the minion</>
          )}
        </span>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key} className="border-b align-top last:border-0">
              <th scope="row" className="w-1/4 px-4 py-2 text-left font-mono font-normal text-muted sm:pl-6">
                {key}
              </th>
              <td className="px-4 py-2">
                <JsonTree value={value} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {entries.length === 0 && <Empty>No grains match “{q}”.</Empty>}
    </div>
  )
}

function Change({ label, tone, children }: { label: string; tone: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1 font-mono text-[13px]">
      <span className={cn('w-4 shrink-0 text-center font-semibold', tone)}>{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

/** "1 changed · 2 added". */
function counts(changed: number, added: number, removed: number): string {
  return [changed && `${changed} changed`, added && `${added} added`, removed && `${removed} removed`]
    .filter(Boolean)
    .join(' · ')
}

function GrainsEntry({ entry, first }: { entry: GrainsChange; first: boolean }) {
  const added = Object.entries(entry.added)
  const removed = Object.entries(entry.removed)
  const changed = Object.entries(entry.changed)
  return (
    <>
      <span className="text-sm text-muted">
        {first
          ? `First collection · ${added.length} grains`
          : `Grains: ${counts(changed.length, added.length, removed.length)}`}
      </span>
      {!first && (
        <div className="mt-2 basis-full">
          {changed.map(([key, { from, to }]) => (
            <Change key={key} label="~" tone="text-warn">
              <span className="text-muted">{key}: </span>
              <span className="line-through opacity-60">{JSON.stringify(from)}</span>
              {' → '}
              <span>{JSON.stringify(to)}</span>
            </Change>
          ))}
          {added.map(([key, value]) => (
            <Change key={key} label="+" tone="text-online">
              <span className="text-muted">{key}: </span>
              {JSON.stringify(value)}
            </Change>
          ))}
          {removed.map(([key, value]) => (
            <Change key={key} label="−" tone="text-danger">
              <span className="text-muted">{key}: </span>
              <span className="line-through opacity-60">{JSON.stringify(value)}</span>
            </Change>
          ))}
        </div>
      )}
    </>
  )
}

/** "Packages: 1 changed · 1 added", "rover-cli check: changed". */
function readTitle(source: string, changes: InventoryChange[]): string {
  const what = source === 'packages' ? 'Packages' : `${source} check`
  const added = changes.filter((c) => c.old === null).length
  const removed = changes.filter((c) => c.new === null).length
  if (changes.length === 1 && changes[0]!.name === '')
    return `${what}: ${added ? 'added' : removed ? 'removed' : 'changed'}`
  return `${what}: ${counts(changes.length - added - removed, added, removed)}`
}

type HistoryEntry =
  | { kind: 'grains'; at: string; entry: GrainsChange; first: boolean }
  | { kind: 'read'; at: string; source: string; changes: InventoryChange[] }

/** Grains entries and package and check reads, newest first, and whether older ones were left out. */
function timeline(grains: GrainsChange[], changes: InventoryChange[]): { entries: HistoryEntry[]; more: boolean } {
  const grainsFull = grains.length < GRAINS_HISTORY_LIMIT
  const changesFull = changes.length < MINION_CHANGES_LIMIT
  const entries: HistoryEntry[] = grains.map((entry, i) => ({
    kind: 'grains',
    at: entry.collected_at,
    entry,
    // Unless the list was cut, its oldest entry is the first collection.
    first: grainsFull && i === grains.length - 1,
  }))
  // Changes found by the same read: the same time and source.
  const reads = new Map<string, InventoryChange[]>()
  for (const c of changes) {
    const key = `${c.at} ${c.source}`
    const group = reads.get(key)
    if (group) group.push(c)
    else reads.set(key, [c])
  }
  for (const group of reads.values()) {
    group.sort((a, b) => a.name.localeCompare(b.name))
    entries.push({ kind: 'read', at: group[0]!.at, source: group[0]!.source, changes: group })
  }
  // Each list stops at its limit; past the end of either, the other would go on alone, as if
  // nothing else changed. So the timeline stops there.
  const ends = [grainsFull ? null : grains.at(-1)?.collected_at, changesFull ? null : changes.at(-1)?.at]
  const cut = Math.max(...ends.map((at) => (at ? Date.parse(at) : -Infinity)))
  return {
    entries: entries.filter((e) => Date.parse(e.at) >= cut).sort((a, b) => Date.parse(b.at) - Date.parse(a.at)),
    more: cut > -Infinity,
  }
}

export function HistoryPanel({ minionId, now }: { minionId: string; now: number }) {
  const grains = useGrainsHistory(minionId, true)
  const changes = useInventoryChanges({ minion: minionId })
  if (grains.isPending || changes.isPending) return <Empty>Loading history…</Empty>
  if (grains.isError && changes.isError) return <Empty>Couldn't load history: {grains.error.message}</Empty>
  const { entries, more } = timeline(grains.data ?? [], changes.data ?? [])
  const failed = grains.isError
    ? `Couldn't load grains history: ${grains.error.message}`
    : changes.isError
      ? `Couldn't load package and check changes: ${changes.error.message}`
      : null
  return (
    <>
      {failed && <p className="border-b px-4 py-3 text-sm text-danger sm:px-6">{failed}</p>}
      {entries.length === 0 ? (
        !failed && <Empty>No grains or packages collected yet.</Empty>
      ) : (
        <ol aria-label="History">
          {entries.map((e) => {
            const title = e.kind === 'read' ? readTitle(e.source, e.changes) : ''
            return (
              <li
                key={e.kind === 'grains' ? e.at : `${e.at} ${e.source}`}
                className="flex flex-wrap items-baseline gap-x-3 border-b px-4 py-4 last:border-0 sm:px-6"
              >
                <span className="font-medium" title={formatAbsolute(e.at)}>
                  {formatRelative(e.at, now)}
                </span>
                {e.kind === 'grains' ? (
                  <GrainsEntry entry={e.entry} first={e.first} />
                ) : (
                  <>
                    <span className="text-sm text-muted">{title}</span>
                    <span className="text-sm text-muted">
                      <FoundWhen change={e.changes[0]!} now={now} />
                    </span>
                    <div className="mt-1 basis-full">
                      <ChangeList changes={e.changes} now={now} label={title} showName oneRead />
                    </div>
                  </>
                )}
              </li>
            )
          })}
        </ol>
      )}
      {more && <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">Older history isn't shown.</p>}
    </>
  )
}

export function JobsPanel({ minion, now }: { minion: MinionDetail; now: number }) {
  if (minion.recent_jobs.length === 0) return <Empty>No jobs recorded for {minion.id} yet.</Empty>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
          <tr>
            <th className="px-4 py-3 font-medium sm:pl-6">Function</th>
            <th className="px-4 py-3 font-medium">Started</th>
            <th className="px-4 py-3 font-medium">Result</th>
            <th className="px-4 py-3 font-medium">Job ID</th>
          </tr>
        </thead>
        <tbody>
          {minion.recent_jobs.map((job) => (
            <tr key={job.jid} className="border-t">
              <td className="px-4 py-3 font-mono sm:pl-6">
                <Link to={`/jobs/${job.jid}`} className="hover:text-accent">
                  {job.fun}
                </Link>
              </td>
              <td className="px-4 py-3" title={formatAbsolute(job.started_at)}>
                {formatRelative(job.started_at, now)}
              </td>
              <td className="px-4 py-3">
                <ResultLabel success={job.success} retcode={job.retcode} />
              </td>
              <td className="px-4 py-3 font-mono text-muted">{job.jid}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ResultLabel({ success, retcode }: { success: boolean | null; retcode: number | null }) {
  if (success === null) return <span className="text-muted">—</span>
  return success ? (
    <span className="inline-flex items-center gap-1.5 text-online">
      <CircleCheck className="size-4" aria-hidden /> Succeeded
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-danger">
      <CircleX className="size-4" aria-hidden /> Failed{retcode ? ` (${retcode})` : ''}
    </span>
  )
}

export function TimelinePanel({ minion, now }: { minion: MinionDetail; now: number }) {
  const points = minion.presence_history
  if (points.length === 0)
    return <Empty>No presence changes recorded yet. brine logs each time {minion.id} comes or goes.</Empty>
  return (
    <ol className="px-4 py-2 sm:px-6">
      {points.map((point, i) => {
        // Newest first: this state lasted until the next-newer change (or now).
        const until = i === 0 ? now : Date.parse(points[i - 1]!.at)
        const lasted = until - Date.parse(point.at)
        return (
          <li key={point.at + i} className="relative flex gap-4 pb-5 last:pb-2">
            {i < points.length - 1 && <span className="absolute top-4 left-[5px] h-full w-px bg-border" aria-hidden />}
            <StatusDot status={point.connected ? 'online' : 'offline'} className="relative mt-1.5 size-3" />
            <div>
              <div className="font-medium">{point.connected ? 'Came online' : 'Went offline'}</div>
              <div className="text-sm text-muted" title={formatAbsolute(point.at)}>
                {formatRelative(point.at, now)} · {i === 0 ? 'for' : 'lasted'} {formatDuration(lasted)}
                {i === 0 && ' so far'}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

const LIVE_HELP: Record<LiveKind, string> = {
  pillar: 'Pillar keys with values masked (pillar.obfuscate). Revealing values will need an admin role and is audited.',
  beacons: 'Beacons configured on the minion (beacons.list).',
  schedules: "The minion's scheduler (schedule.list).",
  mine: 'Mine functions the minion publishes (mine.valid).',
}

export function LivePanel({ minionId, kind, now }: { minionId: string; kind: LiveKind; now: number }) {
  const live = useMinionLive(minionId, kind, true)
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <p className="text-sm text-muted">{LIVE_HELP[kind]}</p>
        <div className="flex items-center gap-3 text-sm text-muted">
          {live.data && (
            <span title={formatAbsolute(live.data.fetched_at)}>
              Fetched live {formatRelative(live.data.fetched_at, now)}
            </span>
          )}
          <button
            type="button"
            onClick={() => void live.refetch()}
            className="flex h-8 items-center gap-1.5 rounded-lg border px-2.5 hover:bg-surface-2"
          >
            <RefreshCw className={cn('size-3.5', live.isFetching && 'animate-spin')} aria-hidden />
            Refresh
          </button>
        </div>
      </div>
      {live.isPending ? (
        <Empty>Asking {minionId}…</Empty>
      ) : live.isError ? (
        <Empty>Couldn't ask {minionId}: {live.error.message}</Empty>
      ) : live.data.offline ? (
        <Empty>{minionId} is offline, so brine didn't ask it. This loads when it's back.</Empty>
      ) : !live.data.answered ? (
        <Empty>{minionId} didn't answer within 10 seconds. It may be offline.</Empty>
      ) : isEmpty(live.data.data) ? (
        <Empty>Nothing configured.</Empty>
      ) : (
        <div className="overflow-x-auto px-4 py-4 sm:px-6">
          <JsonTree value={live.data.data} expandDepth={4} />
        </div>
      )}
    </div>
  )
}

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') {
    const keys = Object.keys(value)
    // beacons.list / schedule.list report an "enabled" flag even when nothing is configured.
    return keys.length === 0 || (keys.length === 1 && keys[0] === 'enabled')
  }
  return false
}
