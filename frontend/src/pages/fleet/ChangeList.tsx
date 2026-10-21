import { Link } from 'react-router'
import type { InventoryChange, MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { Pill } from '@/components/ui'
import { formatAbsolute, formatRelative, relativeRange } from '@/lib/time'

/**
 * Where a change sits in time. brine only sees a change when it reads the minion again, so it's
 * "found after" a job (or several by one person), never "made by" it: the read also catches
 * anything else since the one before. Without a job, all brine knows is the two reads around it.
 */
function FoundWhen({ change, now }: { change: InventoryChange; now: number }) {
  const { jid, user, since, at } = change
  if (jid)
    return (
      <>
        found after job{' '}
        <Link to={`/jobs/${encodeURIComponent(jid)}`} className="font-mono hover:text-accent">
          {jid}
        </Link>
        {user && ` by ${user}`}
      </>
    )
  if (user) return <>found after jobs by {user}</>
  if (!since) return null
  const range = relativeRange(since, at, now)
  if (!range) return <>sometime around {formatRelative(at, now)}</>
  return (
    <>
      sometime between <span title={formatAbsolute(since)}>{range[0]}</span> and{' '}
      <span title={formatAbsolute(at)}>{range[1]}</span>
    </>
  )
}

function OldToNew({ change }: { change: InventoryChange }) {
  if (change.old === null)
    return (
      <>
        <Pill title={change.new ?? ''}>{change.new}</Pill> <span className="text-muted">(new)</span>
      </>
    )
  if (change.new === null)
    return (
      <>
        <Pill title={change.old}>{change.old}</Pill> <span className="text-muted">(removed)</span>
      </>
    )
  return (
    <>
      <Pill title={change.old}>{change.old}</Pill> → <Pill title={change.new}>{change.new}</Pill>
    </>
  )
}

/** Package or check changes, newest first: when, which minion, old → new, and what it was found after. */
export function ChangeList({
  changes,
  now,
  statusOf = {},
  label,
}: {
  changes: InventoryChange[]
  now: number
  statusOf?: Record<string, MinionStatus>
  label: string
}) {
  return (
    <ul aria-label={label}>
      {changes.map((c, i) => (
        <li
          key={`${c.minion_id}:${c.source}:${c.name}:${c.at}:${i}`}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-4 py-2.5 text-sm first:border-t-0 sm:px-6"
          title={c.since ? `Between brine's reads at ${formatAbsolute(c.since)} and ${formatAbsolute(c.at)}` : undefined}
        >
          <span className="min-w-16 text-muted tabular-nums" title={formatAbsolute(c.at)}>
            {formatRelative(c.at, now)}
          </span>{' '}
          <MinionChip id={c.minion_id} status={statusOf[c.minion_id]} />{' '}
          <span className="flex min-w-0 items-center gap-1.5">
            <OldToNew change={c} />
          </span>{' '}
          <span className="text-muted">
            <FoundWhen change={c} now={now} />
          </span>
        </li>
      ))}
    </ul>
  )
}
