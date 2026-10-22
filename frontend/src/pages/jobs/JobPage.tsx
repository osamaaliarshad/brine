import { ChevronLeft, ChevronRight, LoaderCircle, RotateCcw, Square } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useCapabilities, useJob, useMe } from '@/api/queries'
import type { JobDetail, JobResult } from '@/api/types'
import { JsonTree } from '@/components/JsonView'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatDuration, formatRelative, useNow } from '@/lib/time'
import { ResultLabel } from '@/pages/minion/panels'
import { CONTROL } from '@/pages/fleet/FleetToolbar'
import { CatchUpPanel } from '@/pages/jobs/CatchUp'
import { commandLine, formatArgs } from '@/pages/jobs/format'
import { JobOutcome, StateDots, StateTable, Target } from '@/pages/jobs/parts'

function Fact({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 font-medium" title={title}>
        {children}
      </div>
    </Card>
  )
}

function ResultCard({ result, job, defaultOpen }: { result: JobResult; job: JobDetail; defaultOpen: boolean }) {
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
        <span className="ml-auto text-sm text-muted" title={formatAbsolute(result.returned_at)}>
          returned after {formatDuration(Date.parse(result.returned_at) - Date.parse(job.started_at))}
        </span>
      </button>
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
}

// Minions usually answer within seconds. Until this long after a job started, the ones still out
// are waited for; after it, the page says they haven't returned.
const ANSWER_WAIT_MS = 60_000

/** "Waiting for answers from rover-01, rover-02…", with a spinner. */
function Waiting({ minions, className }: { minions: string[]; className?: string }) {
  return (
    <div role="status" className={cn('flex items-center gap-2 rounded-xl border px-4 py-3 text-sm text-muted', className)}>
      <LoaderCircle className="size-4 shrink-0 animate-spin" aria-hidden />
      {minions.length ? `Waiting for answers from ${minions.join(', ')}…` : 'Waiting for an answer…'}
    </div>
  )
}

// Target types the Run page takes; other jobs are re-run on the minions they reached.
const RUN_TARGET_TYPES = new Set(['glob', 'list', 'compound', 'grain', 'nodegroup', 'pcre'])

function runLink(command: string, target?: string, type?: string) {
  const params = new URLSearchParams({ command })
  if (target) params.set('target', target)
  if (type) params.set('type', type)
  return `/run?${params}`
}

/** Run it again, or stop minions still running it: all open the Run page, previewed. */
function JobActions({ job }: { job: JobDetail }) {
  const again =
    job.kind === 'runner'
      ? runLink(`runners.${commandLine(job.fun, job.args)}`)
      : job.target && RUN_TARGET_TYPES.has(job.target_type ?? 'glob')
        ? runLink(commandLine(job.fun, job.args), job.target, job.target_type ?? 'glob')
        : runLink(commandLine(job.fun, job.args), job.minions.join(','), 'list')
  const waiting = job.kind === 'local' && job.missing.length > 0
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
              to={runLink(`saltutil.term_job ${job.jid}`, job.missing.join(','), 'list')}
              className={CONTROL}
              title="Ask the minions still running it to end it (SIGTERM)"
            >
              <Square className="size-4 text-muted" aria-hidden />
              Stop
            </Link>
            <Link
              to={runLink(`saltutil.kill_job ${job.jid}`, job.missing.join(','), 'list')}
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
  // Ticks often, so a young job's wait turns into "No return" soon after it ends.
  const now = useNow(5_000)
  const query = useJob(jid)
  const job = query.data
  const young = !!job && now - Date.parse(job.started_at) < ANSWER_WAIT_MS
  const role = useMe().data?.role
  const canRun = !!useCapabilities(!!role && role !== 'viewer').data?.commands.length

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
              {canRun && <JobActions job={job} />}
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

            {job.missing.length > 0 &&
              (young ? (
                <Waiting minions={job.missing} className="mt-4" />
              ) : (
                <div className="mt-4 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
                  No return from {job.missing.join(', ')}. They may have been offline, or are still running it.
                </div>
              ))}
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
                  job.missing.length === 0 && <Waiting minions={[]} />
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
