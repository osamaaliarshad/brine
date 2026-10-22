import { Link } from 'react-router'
import { useCancelCatchUp, useMe } from '@/api/queries'
import type { CatchUpRun } from '@/api/types'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatDuration, formatRelative } from '@/lib/time'
import { STATE_LABEL, unanswered } from '@/pages/jobs/catchUpRuns'

const STATE_STYLE: Record<CatchUpRun['state'], string> = {
  waiting: 'bg-warn/15 text-warn',
  sending: 'bg-warn/15 text-warn',
  failed: 'bg-danger/15 text-danger',
  sent: 'bg-online/15 text-online',
  expired: 'bg-surface-2 text-muted',
  cancelled: 'bg-surface-2 text-muted',
  replaced: 'bg-surface-2 text-muted',
  refused: 'bg-danger/15 text-danger',
}

/** A run's badge: a sent one is "Sent" until it's answered, "No answer" once its minion is missing. */
function badge(run: CatchUpRun, missing: Set<string>): [string, string] {
  if (!unanswered(run)) return [STATE_LABEL[run.state], STATE_STYLE[run.state]]
  return missing.has(run.minion_id) ? ['No answer', STATE_STYLE.failed] : ['Sent', STATE_STYLE.sending]
}

function Detail({ run, now, missing }: { run: CatchUpRun; now: number; missing: Set<string> }) {
  if (run.state === 'waiting')
    return (
      <span title={formatAbsolute(run.expires_at)}>
        Runs when it's back · gives up in {formatDuration(Date.parse(run.expires_at) - now)}
      </span>
    )
  if (run.state === 'sent')
    return (
      <span title={formatAbsolute(run.sent_at)}>
        {unanswered(run) ? 'Sent' : 'Ran'} {formatRelative(run.sent_at, now)}
        {unanswered(run) && (missing.has(run.minion_id) ? ', no answer' : ', no answer yet')} ·{' '}
        <Link to={`/jobs/${run.sent_jid}`} className="text-accent hover:underline">
          its job
        </Link>
      </span>
    )
  return <span>{run.reason}</span>
}

/**
 * Minions that missed this job while offline, and whether they've had it since. `missing`: the
 * job's, so a run sent long ago that was never answered says so, as the job does.
 */
export function CatchUpPanel({ runs, now, missing }: { runs: CatchUpRun[]; now: number; missing: string[] }) {
  const me = useMe().data
  const cancel = useCancelCatchUp()
  if (runs.length === 0) return null
  const gone = new Set(missing)
  const waiting = runs.filter((r) => r.state === 'waiting').length
  return (
    <Card className="mt-4 overflow-hidden sm:mt-6">
      <div className="border-b px-4 py-3 sm:px-6">
        <h2 className="font-medium">Catching up offline minions</h2>
        <p className="text-xs text-muted">
          {waiting > 0
            ? `${waiting} of ${runs.length} still waiting. brine runs it on each one when it's back, one command at a time.`
            : 'Asked for when this ran: minions that were offline get it when they come back.'}
        </p>
      </div>
      <ul>
        {runs.map((run) => (
          <li key={run.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2.5 text-sm last:border-b-0 sm:px-6">
            <Link to={`/minions/${encodeURIComponent(run.minion_id)}`} className="font-mono hover:text-accent">
              {run.minion_id}
            </Link>
            <span className={cn('rounded-md px-2 py-0.5 text-xs font-medium', badge(run, gone)[1])}>
              {badge(run, gone)[0]}
            </span>
            <span className="min-w-0 flex-1 text-muted">
              <Detail run={run} now={now} missing={gone} />
            </span>
            {run.state === 'waiting' && (me?.email === run.actor || me?.role === 'admin') && (
              <button
                type="button"
                aria-label={`Cancel the catch-up for ${run.minion_id}`}
                onClick={() => cancel.mutate(run.id)}
                disabled={cancel.isPending}
                className="h-8 rounded-lg border px-3 text-xs hover:bg-surface-2 disabled:opacity-50"
              >
                Cancel
              </button>
            )}
          </li>
        ))}
      </ul>
      {cancel.isError && (
        <p role="alert" className="border-t px-4 py-2 text-sm text-danger sm:px-6">
          {cancel.error.message}
        </p>
      )}
    </Card>
  )
}
