import { ChevronRight, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useComparison, useFleet, useFleetComparison } from '@/api/queries'
import type { ComparedMinion, InventorySource, MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { cn } from '@/lib/cn'
import { explorerPath, keyDescription, keyKind, keyLabel, keyOf } from '@/lib/inventoryKey'

const NOTE = 'px-4 py-3 text-sm text-muted sm:px-6'
const BUTTON = 'flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-surface-2'

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

function Value({ value }: { value: string | null }) {
  if (value === null)
    return (
      <span className="text-muted" title="Not there">
        —
      </span>
    )
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
        <p className="font-medium text-fg">{n === 0 ? 'Same packages and checks.' : `${n} difference${n === 1 ? '' : 's'}`}</p>
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
                    <Value value={d.reference} />
                  </td>
                  <td className="px-4 py-2 font-mono text-[13px] break-all sm:pr-6">
                    <Value value={d.minion} />
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

/** "3 different · 1 missing · 2 extra", "Same as rover-01", "Not read yet". */
function differs(m: ComparedMinion, reference: string): string {
  if (!m.read) return 'Not read yet'
  const counts = [
    m.different && `${m.different} different`,
    m.only_reference && `${m.only_reference} missing`,
    m.only_minion && `${m.only_minion} extra`,
  ].filter(Boolean)
  return counts.length ? counts.join(' · ') : `Same as ${reference}`
}

const total = (m: ComparedMinion) => m.different + m.only_reference + m.only_minion

/** Every other minion against `reference`, most different first. */
function FleetDifferences({
  reference,
  statusOf,
  compareLink,
  onPick,
}: {
  reference: string
  statusOf: Record<string, MinionStatus>
  compareLink: (id: string) => string
  onPick: () => void
}) {
  const comparison = useFleetComparison(reference, true)
  if (comparison.isPending) return <p className={NOTE}>Comparing the fleet with {reference}…</p>
  if (comparison.isError) return <p className={NOTE}>Couldn't compare the fleet: {comparison.error.message}</p>
  const rows = [...comparison.data.minions].sort(
    (a, b) => Number(b.read) - Number(a.read) || total(b) - total(a) || a.minion_id.localeCompare(b.minion_id),
  )
  const label = `How the fleet differs from ${reference}`
  return (
    <div className="border-t">
      <p className={NOTE}>
        Missing: {reference} has it, they don't. Extra: they have it, {reference} doesn't.
      </p>
      <ul aria-label={label}>
        {rows.map((m) => (
          <li key={m.minion_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-4 py-2 sm:px-6">
            <MinionChip id={m.minion_id} status={statusOf[m.minion_id]} />
            <span
              className={cn('min-w-0 flex-1 text-sm', !m.read && 'text-muted')}
              title={m.read ? undefined : `brine hasn't read the same packages or checks in full on both yet`}
            >
              {differs(m, reference)}
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
export function Compare({ minionId, sources }: { minionId: string; sources: InventorySource[] }) {
  const [params, setParams] = useSearchParams()
  const other = params.get('compare')
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
        <select
          aria-label="Compare with"
          value={other ?? ''}
          onChange={(e) => setParams(withCompare(e.target.value || null), { replace: true })}
          className="h-9 min-w-0 rounded-lg border bg-bg px-2 text-sm"
        >
          <option value="">Compare with…</option>
          {others.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        {other && (
          <button type="button" onClick={() => setParams(withCompare(null), { replace: true })} className={BUTTON}>
            <X className="size-4 text-muted" aria-hidden />
            Stop comparing
          </button>
        )}
        <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className={BUTTON}>
          <ChevronRight className={cn('size-4 text-muted transition-transform', open && 'rotate-90')} aria-hidden />
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
        />
      )}
    </div>
  )
}
