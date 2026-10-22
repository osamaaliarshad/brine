import { ChevronRight, RefreshCw, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useComparison, useFleet, useFleetComparison } from '@/api/queries'
import type { ComparedMinion, InventorySource, MinionStatus } from '@/api/types'
import { Select } from '@/components/Listbox'
import { MinionChip } from '@/components/MinionChip'
import { cn } from '@/lib/cn'
import { explorerPath, keyDescription, keyKind, keyLabel, keyOf, missingLabel } from '@/lib/inventoryKey'
import { formatAbsolute, formatRelative } from '@/lib/time'

const NOTE = 'px-4 py-3 text-sm text-muted sm:px-6'
// Grows rather than spills when a long minion ID wraps on a phone.
const BUTTON =
  'flex min-h-9 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-left text-sm wrap-anywhere hover:bg-surface-2'

/** "a", "a and b", "a, b and c". */
function listed(items: string[]): string {
  return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}

/** "packages and the containers check", "the containers and gpu checks". */
function sourcesPhrase(sources: string[]): string {
  const checks = sources.filter((s) => s !== 'packages')
  return [
    sources.includes('packages') && 'packages',
    checks.length > 0 && `the ${listed(checks)} check${checks.length === 1 ? '' : 's'}`,
  ]
    .filter(Boolean)
    .join(' and ')
}

/** One side's value; not there reads as in the explorer ("Not installed", "Not reported"). */
function Value({ value, itemKey }: { value: string | null; itemKey: string }) {
  if (value === null) return <span className="font-sans break-normal text-muted">{missingLabel(itemKey)}</span>
  return value === '' ? <span className="text-muted">(empty)</span> : <>{value}</>
}

/** Every package and check entry where `other` differs from `reference`. */
function Differences({ reference, other, sources }: { reference: string; other: string; sources: InventorySource[] }) {
  const comparison = useComparison(reference, other)
  if (comparison.isPending) return <p className={NOTE}>Comparing with {other}…</p>
  if (comparison.isError)
    return (
      <p className={NOTE}>
        {comparison.error instanceof ApiError && comparison.error.status === 404
          ? `brine has no accepted minion called ${other}.`
          : `Couldn't compare with ${other}: ${comparison.error.message}`}
      </p>
    )
  const { differences, sources_compared: compared } = comparison.data
  if (compared.length === 0)
    return (
      <p className={NOTE}>
        Nothing to compare yet: {reference} and {other} haven't both been read in full.
      </p>
    )
  const left = sources.map((s) => s.source).filter((s) => !compared.includes(s))
  const n = differences.length
  return (
    <>
      <div className={NOTE}>
        <p className="font-medium text-fg">
          {n === 0
            ? `${reference} and ${other} have the same packages and checks.`
            : `${n} difference${n === 1 ? '' : 's'}`}
        </p>
        {left.length > 0 && <p>Not compared: {sourcesPhrase(left)}, until both have been read in full.</p>}
      </div>
      {n > 0 && (
        <table aria-label={`Where ${reference} and ${other} differ`} className="w-full table-fixed text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-muted">
            <tr>
              <th className="w-2/5 px-4 py-2 font-medium sm:pl-6">Package or check</th>
              <th className="px-4 py-2 font-medium normal-case tracking-normal">{reference}</th>
              <th className="px-4 py-2 font-medium normal-case tracking-normal sm:pr-6">{other}</th>
            </tr>
          </thead>
          <tbody>
            {differences.map((d) => {
              const key = keyOf(d)
              return (
                <tr key={key} className="border-t align-top">
                  <td className="px-4 py-2 sm:pl-6">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <Link
                        to={explorerPath(key)}
                        title={`${keyDescription(key)}: see it across the fleet`}
                        className="font-mono text-[13px] break-all hover:text-accent"
                      >
                        {keyLabel(key)}
                      </Link>
                      <span className="text-xs text-muted">{keyKind(key)}</span>
                    </div>
                  </td>
                  <td className="px-4 py-2 font-mono text-[13px] break-all">
                    <Value value={d.reference} itemKey={key} />
                  </td>
                  <td className="px-4 py-2 font-mono text-[13px] break-all sm:pr-6">
                    <Value value={d.minion} itemKey={key} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </>
  )
}

/** "3 different · 1 missing · 2 extra", "Same as rover-01 · packages not compared",
 * "Nothing to compare yet". */
function differs(m: ComparedMinion, reference: string, referenceSources: string[]): string {
  if (!m.read) return 'Nothing to compare yet'
  const counts = [
    m.different && `${m.different} different`,
    m.only_reference && `${m.only_reference} missing`,
    m.only_minion && `${m.only_minion} extra`,
  ].filter(Boolean)
  const left = referenceSources.filter((s) => !m.sources_compared.includes(s))
  return [counts.length ? counts.join(' · ') : `Same as ${reference}`, left.length && `${sourcesPhrase(left)} not compared`]
    .filter(Boolean)
    .join(' · ')
}

const total = (m: ComparedMinion) => m.different + m.only_reference + m.only_minion

/** Every other minion against `reference`, most different first. */
function FleetDifferences({
  reference,
  statusOf,
  compareLink,
  onPick,
  now,
}: {
  reference: string
  statusOf: Record<string, MinionStatus>
  compareLink: (id: string) => string
  onPick: () => void
  now: number
}) {
  const comparison = useFleetComparison(reference, true)
  if (comparison.isPending) return <p className={cn(NOTE, 'border-t')}>Comparing the fleet with {reference}…</p>
  if (comparison.isError)
    return <p className={cn(NOTE, 'border-t')}>Couldn't compare the fleet: {comparison.error.message}</p>
  const { minions, reference_sources: referenceSources } = comparison.data
  if (referenceSources.length === 0)
    return <p className={cn(NOTE, 'border-t')}>Nothing to compare until {reference} has been read in full.</p>
  const rows = [...minions].sort(
    (a, b) => Number(b.read) - Number(a.read) || total(b) - total(a) || a.minion_id.localeCompare(b.minion_id),
  )
  const at = new Date(comparison.dataUpdatedAt).toISOString()
  return (
    <div className="border-t">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 text-sm text-muted sm:px-6">
        <p>
          Missing: {reference} has it, they don't. Extra: they have it, {reference} doesn't.
        </p>
        <span className="flex items-center gap-1.5">
          <span title={formatAbsolute(at)}>Compared {formatRelative(at, now)}</span>·
          <button
            type="button"
            onClick={() => void comparison.refetch()}
            disabled={comparison.isFetching}
            className="flex items-center gap-1 text-fg hover:text-accent disabled:opacity-50"
          >
            <RefreshCw className={cn('size-3.5', comparison.isFetching && 'animate-spin')} aria-hidden />
            Compare again
          </button>
        </span>
      </div>
      <ul aria-label={`How the fleet differs from ${reference}`}>
        {rows.map((m) => (
          <li key={m.minion_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-4 py-2 sm:px-6">
            <MinionChip id={m.minion_id} status={statusOf[m.minion_id]} />
            <span
              className={cn('min-w-0 flex-1 text-sm', !m.read && 'text-muted')}
              title={m.read ? undefined : `brine hasn't read the same packages or checks in full on both yet`}
            >
              {differs(m, reference, referenceSources)}
            </span>
            {m.read && (
              <Link
                to={compareLink(m.minion_id)}
                replace
                onClick={onPick}
                aria-label={`Compare with ${m.minion_id}`}
                className="flex h-8 items-center rounded-lg border px-3 text-sm hover:bg-surface-2"
              >
                Compare
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Compare this minion's packages and checks with another's, or see how the whole fleet differs from it. */
export function Compare({ minionId, sources, now }: { minionId: string; sources: InventorySource[]; now: number }) {
  const [params, setParams] = useSearchParams()
  // Compared with itself: nothing to say.
  const asked = params.get('compare')
  const other = asked && asked !== minionId ? asked : null
  const fleet = useFleet()
  const [open, setOpen] = useState(false)
  const minions = fleet.data?.minions ?? []
  const statusOf = Object.fromEntries(minions.map((m) => [m.id, m.status]))
  const others = minions.map((m) => m.id).filter((id) => id !== minionId)
  // A link may name one the fleet hasn't loaded (or doesn't have): keep it pickable.
  if (other && !others.includes(other)) others.push(other)
  const withCompare = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('compare', id)
    else next.delete('compare')
    return next
  }
  if (fleet.isSuccess && others.length === 0) return null // nobody to compare with

  return (
    <div className="border-b">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 sm:px-6">
        <Select
          label="Compare with"
          placeholder="Compare with…"
          value={other ?? ''}
          options={others.map((id) => ({ value: id, label: id }))}
          onChange={(id) => setParams(withCompare(id), { replace: true })}
          className="min-w-0"
        />
        {other && (
          <button type="button" onClick={() => setParams(withCompare(null), { replace: true })} className={BUTTON}>
            <X className="size-4 shrink-0 text-muted" aria-hidden />
            Stop comparing
          </button>
        )}
        <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className={cn(BUTTON, 'min-w-0')}>
          <ChevronRight
            className={cn('size-4 shrink-0 text-muted transition-transform', open && 'rotate-90')}
            aria-hidden
          />
          How the fleet differs from {minionId}
        </button>
      </div>
      {other && <Differences key={other} reference={minionId} other={other} sources={sources} />}
      {open && (
        <FleetDifferences
          reference={minionId}
          statusOf={statusOf}
          compareLink={(id) => `?${withCompare(id)}`}
          onPick={() => setOpen(false)}
          now={now}
        />
      )}
    </div>
  )
}
