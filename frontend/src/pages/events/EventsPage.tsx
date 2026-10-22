import { ChevronRight, Pause, Play, Search, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useReactors } from '@/api/queries'
import type { SaltEventEntry } from '@/api/types'
import { JsonTree } from '@/components/JsonView'
import { PageHeader } from '@/components/PageHeader'
import { Tabs } from '@/components/Tabs'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute } from '@/lib/time'
import { useTab } from '@/lib/useTab'
import { type EventKind, eventKind, matchesFilter, summarize } from '@/pages/events/eventModel'
import { MAX_EVENTS, useEventStream } from '@/pages/events/useEventStream'

const TABS = [
  { key: 'live', label: 'Live' },
  { key: 'reactors', label: 'Reactors' },
] as const

const KIND_STYLE: Record<EventKind, string> = {
  job: 'bg-accent',
  runner: 'bg-accent/50',
  presence: 'bg-offline',
  key: 'bg-warn',
  minion: 'bg-online',
  beacon: 'bg-fg/60',
  other: 'border border-muted bg-transparent',
}

const BTN = 'flex h-10 items-center gap-2 rounded-lg border px-3 text-sm hover:bg-surface-2'

function time(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour12: false })
}

function EventRow({ event }: { event: SaltEventEntry }) {
  const [open, setOpen] = useState(false)
  const kind = eventKind(event.tag)
  return (
    <li className="border-t">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm hover:bg-surface-2/40 sm:px-6"
      >
        <ChevronRight className={cn('size-3.5 shrink-0 text-muted transition-transform', open && 'rotate-90')} aria-hidden />
        <span className="w-20 shrink-0 font-mono text-xs text-muted tabular-nums" title={formatAbsolute(event.received_at)}>
          {time(event.received_at)}
        </span>
        <span className={cn('size-2 shrink-0 rounded-full', KIND_STYLE[kind])} aria-hidden />
        <span className="min-w-0 shrink truncate font-mono text-[13px] sm:w-80 sm:shrink-0">{event.tag}</span>
        <span className="hidden min-w-0 flex-1 truncate text-muted sm:block">{summarize(event)}</span>
      </button>
      {open && (
        <div className="overflow-x-auto px-4 pb-3 pl-14 sm:px-6 sm:pl-16">
          <p className="mb-1 text-sm text-muted sm:hidden">{summarize(event)}</p>
          <JsonTree value={event.data} expandDepth={2} />
        </div>
      )}
    </li>
  )
}

function LiveTab() {
  const [filter, setFilter] = useState('')
  const [showPresence, setShowPresence] = useState(false)
  const { events, waiting, connected, paused, togglePause, clear } = useEventStream()
  const shown = events.filter(
    (e) => (showPresence || eventKind(e.tag) !== 'presence') && matchesFilter(e, filter),
  )

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 p-3 sm:p-4">
        <button type="button" className={cn(BTN, paused && 'border-warn bg-warn/10')} onClick={togglePause}>
          {paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}
          {paused ? `Resume${waiting ? ` (${waiting} new)` : ''}` : 'Pause'}
        </button>
        <label className="flex h-10 min-w-0 flex-1 basis-60 items-center gap-2 rounded-lg border bg-surface px-3">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by tag or content…"
            aria-label="Filter events"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
        <label className="flex h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm hover:bg-surface-2">
          <input
            type="checkbox"
            className="accent-[var(--accent)]"
            checked={showPresence}
            onChange={(e) => setShowPresence(e.target.checked)}
          />
          Presence
        </label>
        <button type="button" className={BTN} onClick={clear} aria-label="Clear events" title="Clear">
          <Trash2 className="size-4" aria-hidden />
        </button>
      </div>
      <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted sm:px-6">
        <span className="inline-flex items-center gap-2">
          <span className={cn('size-2 rounded-full', connected ? 'bg-online' : 'bg-offline')} aria-hidden />
          {connected ? 'Connected to the event bus' : 'Connecting…'}
        </span>
        <span>
          Showing {shown.length} of {events.length} (last {MAX_EVENTS} kept)
        </span>
      </div>
      {shown.length === 0 ? (
        <div className="border-t px-6 py-12 text-center text-muted">
          {events.length ? 'No events match.' : 'Waiting for events… Run a job on the master to see some.'}
        </div>
      ) : (
        <ol aria-label="Events">
          {shown.map((event) => (
            <EventRow key={event.seq} event={event} />
          ))}
        </ol>
      )}
    </>
  )
}

function ReactorsTab() {
  const query = useReactors(true)
  if (query.isPending) return <div className="border-t px-6 py-12 text-center text-muted">Loading reactors…</div>
  if (query.isError)
    return <div className="border-t px-6 py-12 text-center text-muted">Couldn't load reactors: {query.error.message}</div>
  if (query.data.length === 0)
    return (
      <div className="border-t px-6 py-12 text-center text-muted">
        No reactors configured. They live under <code className="font-mono">reactor:</code> in the master config.
      </div>
    )
  return (
    <table className="w-full text-sm">
      <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
        <tr>
          <th className="px-4 py-3 font-medium sm:pl-6">Event tag</th>
          <th className="px-4 py-3 font-medium">Runs</th>
        </tr>
      </thead>
      <tbody>
        {query.data.map((r) => (
          <tr key={r.tag} className="border-t align-top">
            <td className="px-4 py-3 font-mono sm:pl-6">{r.tag}</td>
            <td className="px-4 py-3 font-mono">
              {r.sls.map((s) => (
                <div key={s}>{s}</div>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function EventsPage() {
  const [tab, setTab] = useTab(TABS, 'live')
  return (
    <>
      <PageHeader title="Events" subtitle="The Salt event bus, live." />
      <Card fill className="overflow-hidden">
        <div className="px-2 sm:px-4">
          <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Event views" />
        </div>
        {tab === 'live' ? <LiveTab /> : <ReactorsTab />}
      </Card>
    </>
  )
}
