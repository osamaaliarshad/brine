import { Search } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { useMinionInventory } from '@/api/queries'
import type { InventoryEntry, InventorySource, MinionDetail } from '@/api/types'
import { Badge } from '@/components/ui'
import { cn } from '@/lib/cn'
import { describeSource, explorerPath, INVENTORY_SETTINGS, keyOf } from '@/lib/inventoryKey'
import { formatAbsolute, formatDay, formatRelative } from '@/lib/time'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { useReadNow } from '@/lib/useReadNow'
import { ReadNowBar } from '@/pages/fleet/ReadNowBar'
import { Compare } from '@/pages/minion/Compare'

const NOTE = 'px-4 pb-4 text-sm text-muted sm:px-6'

/** The explorer on this package or check entry: who else has it, and which version. */
function explorerLink(source: string, name: string): string {
  return explorerPath(keyOf({ source, name }))
}

/** Already there at brine's first read: how long before that, brine can't say. */
function sinceFirstRead(entry: InventoryEntry, s: InventorySource): boolean {
  return !!s.first_read_at && Date.parse(entry.since) === Date.parse(s.first_read_at)
}

/** When it appeared or changed: "5h ago" under the Since heading, "since 5h ago" on its own.
 * Only for what changed after the first read; the rest is left blank (the heading has that
 * date), so what did change stands out. */
function Since({ entry, now, alone = false }: { entry: InventoryEntry; now: number; alone?: boolean }) {
  return (
    <span title={formatAbsolute(entry.since)}>
      {alone && 'since '}
      {formatRelative(entry.since, now)}
    </span>
  )
}

function Value({ text }: { text: string }) {
  return text === '' ? <span className="text-muted">(empty)</span> : <>{text}</>
}

function ReadWhen({ s, now }: { s: InventorySource; now: number }) {
  if (!s.read_at) return null
  return (
    <span className="text-sm text-muted">
      <span title={formatAbsolute(s.read_at)}>
        {s.error ? 'Last good read' : 'Read'} {formatRelative(s.read_at, now)}
      </span>
      {s.first_read_at && (
        <>
          {' · '}
          <span title={formatAbsolute(s.first_read_at)}>first read {formatDay(s.first_read_at, now)}</span>
        </>
      )}
    </span>
  )
}

function Entries({
  s,
  entries,
  minion,
  now,
}: {
  s: InventorySource
  entries: InventoryEntry[]
  minion: string
  now: number
}) {
  // On a phone, since goes under the value: a third column would wrap it to a word a line.
  const wide = useMediaQuery('(min-width: 640px)')
  const single = entries.length === 1 && entries[0]!.name === ''
  if (single) {
    const entry = entries[0]!
    return (
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 pb-4 text-sm sm:px-6">
        <Link
          to={explorerLink(s.source, '')}
          title={`See ${s.source} across the fleet`}
          className="font-mono text-[13px] break-all whitespace-pre-wrap hover:text-accent"
        >
          <Value text={entry.value} />
        </Link>
        {!sinceFirstRead(entry, s) && (
          <span className="text-muted">
            <Since entry={entry} now={now} alone />
          </span>
        )}
      </div>
    )
  }
  const firstRead = s.first_read_at
    ? `Already there when brine first read ${minion} on ${formatDay(s.first_read_at, now)}`
    : undefined
  return (
    <table className="w-full table-fixed text-sm">
      <thead className="text-left text-xs uppercase tracking-wider text-muted">
        <tr>
          <th className="w-1/2 px-4 py-2 font-medium sm:w-2/5 sm:pl-6">Name</th>
          <th className="px-4 py-2 font-medium">{s.kind === 'package' ? 'Version' : 'Value'}</th>
          {wide && <th className="w-48 px-4 py-2 font-medium sm:pr-6">Since</th>}
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.name} className="border-t align-top">
            <td className="px-4 py-2 font-mono text-[13px] break-all sm:pl-6">
              <Link
                to={explorerLink(s.source, entry.name)}
                title={`See ${entry.name} across the fleet`}
                className="hover:text-accent"
              >
                {entry.name}
              </Link>
            </td>
            <td className="px-4 py-2 font-mono text-[13px] break-all">
              <Value text={entry.value} />
              {!wide && !sinceFirstRead(entry, s) && (
                <div className="mt-0.5 font-sans text-xs break-normal text-muted">
                  <Since entry={entry} now={now} alone />
                </div>
              )}
            </td>
            {wide &&
              (sinceFirstRead(entry, s) ? (
                <td className="px-4 py-2 sm:pr-6" title={firstRead}>
                  <span className="sr-only">Already there at brine's first read</span>
                </td>
              ) : (
                <td className="px-4 py-2 text-muted sm:pr-6">
                  <Since entry={entry} now={now} />
                </td>
              ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** One source: the packages, or one check. */
function SourceSection({
  s,
  entries,
  filtered,
  minion,
  now,
}: {
  s: InventorySource
  /** What to show: all of them, or those the search matches. */
  entries: InventoryEntry[]
  filtered: boolean
  minion: string
  now: number
}) {
  const id = useId()
  const single = s.entries.length === 1 && s.entries[0]!.name === ''
  return (
    <section aria-labelledby={id} className="border-t">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 pt-4 pb-2 sm:px-6">
        <h3 id={id} className={cn('font-medium', s.kind === 'check' && 'font-mono')}>
          {s.kind === 'package' ? 'Packages' : s.source}
        </h3>
        {s.kind === 'check' && <Badge>check</Badge>}
        {!single && s.entries.length > 0 && (
          <span className="text-sm text-muted tabular-nums">
            {filtered ? `${entries.length} of ${s.entries.length}` : s.entries.length}
          </span>
        )}
        <ReadWhen s={s} now={now} />
      </div>
      {s.error && (
        <p className="px-4 pb-2 text-sm text-warn sm:px-6" title={`Answered ${formatAbsolute(s.answered_at)}`}>
          Couldn't read: {s.error}
        </p>
      )}
      {s.refused && (
        <p className="px-4 pb-2 text-sm text-warn sm:px-6">
          brine can't read {describeSource(s.source)}: {s.refused.replace(/\.$/, '')}.{' '}
          <Link to={INVENTORY_SETTINGS} className="text-fg underline underline-offset-2 hover:text-accent">
            Settings › Packages and checks
          </Link>{' '}
          has the lines to add to brine's Salt account.
        </p>
      )}
      {s.truncated && <p className={NOTE}>The last answer was cut short; some entries may be missing.</p>}
      {!s.read_at ? (
        !s.error &&
        !s.refused && <p className={NOTE}>No answer yet. brine reads every online minion within a few minutes.</p>
      ) : s.entries.length === 0 ? (
        <p className={NOTE} title={s.kind === 'check' ? 'The check printed nothing' : undefined}>
          {s.kind === 'check' ? 'Not reported' : 'No packages reported'}
        </p>
      ) : (
        <Entries s={s} entries={entries} minion={minion} now={now} />
      )}
    </section>
  )
}

/** The newest answer from any source: a new one changes it. */
function lastAnswer(sources: InventorySource[]): string | null {
  let last: string | null = null
  for (const s of sources)
    if (s.answered_at && (last === null || Date.parse(s.answered_at) > Date.parse(last))) last = s.answered_at
  return last
}

/** What one minion has installed, and what each check says, as brine last read them. */
export function PackagesPanel({ minion, now }: { minion: MinionDetail; now: number }) {
  const inventory = useMinionInventory(minion.id, true)
  const read = useReadNow()
  const [q, setQ] = useState('')
  if (inventory.isPending) return <p className="px-6 py-12 text-center text-muted">Loading packages and checks…</p>
  if (inventory.isError)
    return (
      <p className="px-6 py-12 text-center text-muted">Couldn't load packages and checks: {inventory.error.message}</p>
    )

  const sources = inventory.data.sources
  const needle = q.trim().toLowerCase()
  // A check whose name matches shows whole; otherwise only the entries whose name or value do.
  const shown = sources.flatMap((s) => {
    const whole = !needle || (s.kind === 'check' && s.source.toLowerCase().includes(needle))
    const entries = whole
      ? s.entries
      : s.entries.filter((e) => e.name.toLowerCase().includes(needle) || e.value.toLowerCase().includes(needle))
    return whole || entries.length > 0 ? [{ s, entries, whole }] : []
  })

  return (
    <div>
      {minion.key_state === 'accepted' && <Compare minionId={minion.id} sources={sources} now={now} />}
      <ReadNowBar
        read={read}
        minion={minion.id}
        watch={{ key: minion.id, at: lastAnswer(sources) }}
        title={`Read ${minion.id}'s packages and checks again`}
      >
        <label className="flex h-10 min-w-0 flex-1 basis-60 items-center gap-2 rounded-lg border bg-bg px-3">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter packages and checks by name or value…"
            aria-label="Filter packages and checks"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
      </ReadNowBar>
      {shown.map(({ s, entries, whole }) => (
        <SourceSection key={s.source} s={s} entries={entries} filtered={!whole} minion={minion.id} now={now} />
      ))}
      {shown.length === 0 && (
        <p className="border-t px-6 py-12 text-center text-muted">No packages or checks match “{q.trim()}”.</p>
      )}
    </div>
  )
}
