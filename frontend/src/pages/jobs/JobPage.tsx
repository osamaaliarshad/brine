import { ChevronLeft, ChevronRight, LoaderCircle, RotateCcw, Square } from 'lucide-react'
import { Fragment, memo, type ReactNode, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useCapabilities, useJob, useMe } from '@/api/queries'
import type { CatchUpRun, JobDetail, JobResult } from '@/api/types'
import { JsonTree } from '@/components/JsonView'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatDuration, formatRelative, useNow } from '@/lib/time'
import { ResultLabel } from '@/pages/minion/panels'
import { CONTROL } from '@/pages/fleet/FleetToolbar'
import { CatchUpPanel } from '@/pages/jobs/CatchUp'
import { type Missing, STATE_LABEL, STILL_CATCHING_UP, splitMissing } from '@/pages/jobs/catchUpRuns'
import { commandLine, formatArgs } from '@/pages/jobs/format'
import { JobOutcome, StateDots, StateTable, Target } from '@/pages/jobs/parts'

function Fact({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 font-medium wrap-anywhere" title={title}>
        {children}
      </div>
    </Card>
  )
}

// Memoized: the page re-renders as its clock ticks, and a job can have hundreds of results.
const ResultCard = memo(function ResultCard({
  result,
  job,
  defaultOpen,
  now,
}: {
  result: JobResult
  job: JobDetail
  defaultOpen: boolean
  /** For a caught-up result's time; 0 for the rest, so they don't re-render as it ticks. */
  now: number
}) {
  const [open, setOpen] = useState(defaultOpen)
  const failed = result.states?.filter((s) => s.result === false).length ?? 0
  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left hover:bg-surface-2/40 sm:px-6"
      >
        <ChevronRight className={cn('size-4 text-muted transition-transform', open && 'rotate-90')} aria-hidden />
        <span className="font-medium">{job.kind === 'runner' ? 'master' : result.minion_id}</span>
        <ResultLabel success={result.success} retcode={result.retcode} />
        {result.states && (
          <span className="text-sm text-muted">
            {result.states.length} state{result.states.length === 1 ? '' : 's'}
            {failed ? `, ${failed} failed` : ''}
          </span>
        )}
        {result.states && <StateDots states={result.states} max={40} />}
        {!result.caught_up && (
          <span className="ml-auto text-sm text-muted" title={formatAbsolute(result.returned_at)}>
            returned after {formatDuration(Date.parse(result.returned_at) - Date.parse(job.started_at))}
          </span>
        )}
      </button>
      {/* Outside the button: it has a link. */}
      {result.caught_up && (
        <p className="-mt-1 px-4 pb-3 pl-12 text-sm text-muted sm:px-6 sm:pl-14">
          Caught up later, in job{' '}
          <Link to={`/jobs/${result.caught_up.jid}`} className="font-mono text-accent hover:underline">
            {result.caught_up.jid}
          </Link>
          , <span title={formatAbsolute(result.caught_up.at)}>{formatRelative(result.caught_up.at, now)}</span>
        </p>
      )}
      {open && (
        <div className="border-t px-4 py-4 sm:px-6">
          {result.states ? (
            <StateTable states={result.states} />
          ) : (
            <div className="overflow-x-auto">
              <JsonTree value={result.data} expandDepth={2} />
            </div>
          )}
          {job.kind === 'local' && (
            <Link
              to={`/minions/${encodeURIComponent(result.minion_id)}`}
              className="mt-3 inline-block text-sm text-muted hover:text-accent"
            >
              Open {result.minion_id} →
            </Link>
          )}
        </div>
      )}
    </Card>
  )
})

// Minions usually answer within seconds. Until this long after a job started, the ones still out
// are waited for; after it, the page says they haven't returned.
const ANSWER_WAIT_MS = 60_000

// The minions named while waiting; the rest are counted.
const NAMED = 5

/**
 * Whether a job is young: started under ANSWER_WAIT_MS ago by its own time, and opened here under
 * that long ago, so a browser clock behind the master's can't stretch the wait. Re-renders once,
 * when it stops being young.
 */
function useYoung(startedAt: string | undefined): boolean {
  const [openedAt] = useState(Date.now)
  const [now, setNow] = useState(Date.now)
  const until = startedAt ? Math.min(Date.parse(startedAt), openedAt) + ANSWER_WAIT_MS : -Infinity
  useEffect(() => {
    if (until === -Infinity) return
    const id = setTimeout(() => setNow(Date.now()), Math.max(0, until - Date.now()))
    return () => clearTimeout(id)
  }, [until])
  return now < until
}

/** "Waiting for 2 of 3 minions" (all a screen reader hears), with a spinner, then their names. */
function Waiting({ missing, total, className }: { missing: string[]; total: number; className?: string }) {
  const rest = missing.length - NAMED
  return (
    <div className={cn('rounded-xl border px-4 py-3 text-sm text-muted', className)}>
      <div role="status" className="flex items-center gap-2">
        <LoaderCircle className="size-4 shrink-0 animate-spin" aria-hidden />
        {total ? `Waiting for ${missing.length} of ${total} minion${total === 1 ? '' : 's'}` : 'Waiting for an answer'}
      </div>
      {missing.length > 0 && (
        <p className="mt-1 pl-6">
          {missing.slice(0, NAMED).join(', ')}
          {rest > 0 && ` and ${rest} more`}
        </p>
      )}
    </div>
  )
}

/** "Waiting to catch up: rover-03 (runs when it's back)", naming the first few. */
function CatchingUp({ minions }: { minions: Missing['catchingUp'] }) {
  const rest = minions.length - NAMED
  return (
    <div className="mt-4 rounded-xl border px-4 py-3 text-sm">
      Waiting to catch up:{' '}
      {minions.slice(0, NAMED).map(([mid, run], i) => (
        <Fragment key={mid}>
          {i > 0 && ', '}
          {mid} <span className="text-muted">({STILL_CATCHING_UP[run.state]})</span>
        </Fragment>
      ))}
      {rest > 0 && ` and ${rest} more`}.
    </div>
  )
}

/** "rover-03 (catch-up cancelled)" for a minion whose catch-up run came to nothing. */
function noReturnName([mid, run]: [string, CatchUpRun | undefined]): string {
  return run ? `${mid} (catch-up ${STATE_LABEL[run.state].toLowerCase()})` : mid
}

// Target types the Run page takes; other jobs are re-run on the minions they reached.
const RUN_TARGET_TYPES = new Set(['glob', 'list', 'compound', 'grain', 'nodegroup', 'pcre'])

function runLink(command: string, target?: string, type?: string) {
  const params = new URLSearchParams({ command })
  if (target) params.set('target', target)
  if (type) params.set('type', type)
  return `/run?${params}`
}

/**
 * Run it again, or stop it on `running` (the minions that may still be running it): all open the
 * Run page, previewed.
 */
function JobActions({ job, running }: { job: JobDetail; running: string[] }) {
  const again =
    job.kind === 'runner'
      ? runLink(`runners.${commandLine(job.fun, job.args)}`)
      : job.target && RUN_TARGET_TYPES.has(job.target_type ?? 'glob')
        ? runLink(commandLine(job.fun, job.args), job.target, job.target_type ?? 'glob')
        : runLink(commandLine(job.fun, job.args), job.minions.join(','), 'list')
  const waiting = job.kind === 'local' && running.length > 0
  return (
    <div className="flex flex-col gap-2 sm:items-end">
      <div className="flex flex-wrap gap-2">
        <Link to={again} className={CONTROL}>
          <RotateCcw className="size-4 text-muted" aria-hidden />
          Run again
        </Link>
        {waiting && (
          <>
            <Link
              to={runLink(`saltutil.term_job ${job.jid}`, running.join(','), 'list')}
              className={CONTROL}
              title="Ask the minions still running it to end it (SIGTERM)"
            >
              <Square className="size-4 text-muted" aria-hidden />
              Stop
            </Link>
            <Link
              to={runLink(`saltutil.kill_job ${job.jid}`, running.join(','), 'list')}
              className={CONTROL}
              title="End it at once on the minions still running it (SIGKILL)"
            >
              Kill
            </Link>
          </>
        )}
      </div>
      {/* Spelled out, not only in titles: a touch screen has no hover. */}
      {waiting && (
        <p className="max-w-md text-sm text-muted sm:text-right">
          Stop asks it to end (saltutil.term_job): it gets a chance to clean up. Kill ends it at once
          (saltutil.kill_job), like kill -9. Both open Run first; nothing runs until you click Run.
        </p>
      )}
    </div>
  )
}

export function JobPage() {
  const { jid = '' } = useParams()
  // Its own state per job: going from one job to another (a catch-up run's link) starts afresh,
  // so the next job's wait is timed from when it was opened.
  return <JobView key={jid} jid={jid} />
}

function JobView({ jid }: { jid: string }) {
  const now = useNow()
  const query = useJob(jid)
  const job = query.data
  const young = useYoung(job?.started_at)
  const role = useMe().data?.role
  const canRun = !!useCapabilities(!!role && role !== 'viewer').data?.commands.length
  // Minions waiting to catch up are waited for in their own catch-up job (with its own Stop);
  // only the missing ones may still be running this one.
  const { catchingUp, noReturn } = job ? splitMissing(job) : { catchingUp: [], noReturn: [] }
  const running = noReturn.map(([mid]) => mid)

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted">
        <Link to="/jobs" className="inline-flex items-center gap-1 hover:text-fg">
          <ChevronLeft className="size-4" aria-hidden />
          Jobs
        </Link>
      </nav>

      {query.isPending ? (
        <p className="text-muted">Loading job {jid}…</p>
      ) : query.isError ? (
        <Card className="px-6 py-10 text-center">
          {query.error instanceof ApiError && query.error.status === 404
            ? `brine has no job ${jid}. It may have run before brine was connected and left the master's job cache.`
            : `Couldn't load job ${jid}: ${query.error.message}`}
        </Card>
      ) : (
        job && (
          <>
            <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
              <div className="min-w-0">
                <h1 className="font-mono text-3xl font-semibold tracking-tight break-all">
                  {job.fun}
                  {job.args.length > 0 && (
                    <>
                      {' '}
                      <span className="text-muted">{formatArgs(job.args)}</span>
                    </>
                  )}
                </h1>
                <p className="mt-1 font-mono text-sm text-muted">{job.jid}</p>
              </div>
              {canRun && <JobActions job={job} running={running} />}
            </div>

            <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
              <Fact label="Target">
                <Target job={job} />
              </Fact>
              <Fact label="Started" title={formatAbsolute(job.started_at)}>
                {formatRelative(job.started_at, now)}
                {job.user && <span className="text-muted"> by {job.user}</span>}
              </Fact>
              <Fact label="Took" title={formatAbsolute(job.finished_at)}>
                {job.finished_at
                  ? formatDuration(Date.parse(job.finished_at) - Date.parse(job.started_at))
                  : '—'}
              </Fact>
              <Fact label="Results">
                <JobOutcome job={job} />
              </Fact>
            </div>

            {running.length > 0 &&
              (young ? (
                <Waiting missing={running} total={job.minions.length} className="mt-4" />
              ) : (
                <div className="mt-4 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
                  No return from {noReturn.map(noReturnName).join(', ')}. They may have been offline, or are still
                  running it.
                </div>
              ))}
            {catchingUp.length > 0 && <CatchingUp minions={catchingUp} />}
            {job.catch_up_of && (
              <div className="mt-4 rounded-xl border px-4 py-3 text-sm">
                A catch-up run: {job.target} was offline when{' '}
                <Link to={`/jobs/${job.catch_up_of}`} className="text-accent hover:underline">
                  the original job
                </Link>{' '}
                ran, so brine ran it here once it was back.
              </div>
            )}
            <CatchUpPanel runs={job.catch_up} now={now} />

            <div className="mt-4 flex flex-col gap-3 sm:mt-6">
              {job.results.length === 0 ? (
                // While young, the line above already says it's waiting (and for whom).
                young ? (
                  job.missing.length === 0 && catchingUp.length === 0 && <Waiting missing={[]} total={0} />
                ) : (
                  <Card className="px-6 py-10 text-center text-muted">No results recorded yet.</Card>
                )
              ) : (
                job.results.map((result) => (
                  <ResultCard
                    key={result.minion_id}
                    result={result}
                    job={job}
                    defaultOpen={job.results.length <= 3 || result.success === false}
                    now={result.caught_up ? now : 0}
                  />
                ))
              )}
            </div>
          </>
        )
      )}
    </>
  )
}
