import { Search } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { type JobFilters, useJobs, useStateRuns } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { Tabs } from '@/components/Tabs'
import { Card, FILL } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { useKeptFor } from '@/lib/useKeptFor'
import { useTab } from '@/lib/useTab'
import { JobOutcome, StateDots, StateLegend, Target } from '@/pages/jobs/parts'

const TABS = [
  { key: 'all', label: 'All jobs' },
  { key: 'states', label: 'State runs' },
] as const

const KINDS: { value: JobFilters['kind']; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'local', label: 'Minion jobs' },
  { value: 'runner', label: 'Runners' },
]

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="border-t px-6 py-12 text-center text-muted">{children}</div>
}

function AllJobs({ now }: { now: number }) {
  const [params, setParams] = useSearchParams()
  const filters: JobFilters = {
    q: params.get('q') ?? '',
    kind: params.get('kind') === 'local' || params.get('kind') === 'runner' ? (params.get('kind') as 'local' | 'runner') : null,
  }
  const set = (patch: Partial<JobFilters>) => {
    const next = new URLSearchParams(params)
    const merged = { ...filters, ...patch }
    if (merged.q) next.set('q', merged.q)
    else next.delete('q')
    if (merged.kind) next.set('kind', merged.kind)
    else next.delete('kind')
    setParams(next, { replace: true })
  }
  const query = useJobs(filters)
  const jobs = query.data?.pages.flatMap((p) => p.jobs) ?? []
  const keptFor = useKeptFor('jobs_days')

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 p-3 sm:p-4">
        <div role="tablist" aria-label="Job kind" className="flex gap-2">
          {KINDS.map((k) => (
            <button
              key={k.label}
              type="button"
              role="tab"
              aria-selected={filters.kind === k.value}
              onClick={() => set({ kind: k.value })}
              className={cn(
                'h-10 rounded-lg border px-3 text-sm hover:bg-surface-2',
                filters.kind === k.value && 'border-accent bg-accent/10',
              )}
            >
              {k.label}
            </button>
          ))}
        </div>
        <label className="flex h-10 min-w-0 flex-1 basis-60 items-center gap-2 rounded-lg border bg-surface px-3">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={filters.q}
            onChange={(e) => set({ q: e.target.value })}
            placeholder="Search function, target, user, or job ID…"
            aria-label="Search jobs"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
      </div>

      {query.isPending ? (
        <Empty>Loading jobs…</Empty>
      ) : query.isError ? (
        <Empty>Couldn't load jobs: {query.error.message}</Empty>
      ) : jobs.length === 0 ? (
        <Empty>
          {filters.q || filters.kind
            ? 'No jobs match these filters.'
            : 'No jobs yet. brine records every job the master runs from now on, plus what the job cache still holds.'}
        </Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-3 font-medium sm:pl-6">Function</th>
                <th className="px-4 py-3 font-medium">Target</th>
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Started</th>
                <th className="px-4 py-3 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.jid} className="border-t align-middle hover:bg-surface-2/40">
                  <td className="max-w-80 px-4 py-3 sm:pl-6">
                    <Link to={`/jobs/${job.jid}`} className="font-mono hover:text-accent">
                      {job.fun}
                    </Link>
                    <div className="truncate text-xs text-muted">{job.jid}</div>
                  </td>
                  <td className="px-4 py-3">
                    <Target job={job} />
                  </td>
                  <td className="px-4 py-3">{job.user ?? <span className="text-muted">—</span>}</td>
                  <td className="px-4 py-3 whitespace-nowrap" title={formatAbsolute(job.started_at)}>
                    {formatRelative(job.started_at, now)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <JobOutcome job={job} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.hasNextPage && (
        <div className="border-t p-3 text-center">
          <button
            type="button"
            onClick={() => void query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
            className="rounded-lg border px-4 py-2 text-sm hover:bg-surface-2 disabled:opacity-50"
          >
            {query.isFetchingNextPage ? 'Loading…' : 'Load older jobs'}
          </button>
        </div>
      )}
      {keptFor && <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">{keptFor}</p>}
    </>
  )
}

function StateRunsTab({ now }: { now: number }) {
  const query = useStateRuns(true)
  if (query.isPending) return <Empty>Loading state runs…</Empty>
  if (query.isError) return <Empty>Couldn't load state runs: {query.error.message}</Empty>
  const { runs, never } = query.data
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <p className="text-sm text-muted">The latest state.apply / highstate / sls run on each minion.</p>
        <StateLegend />
      </div>
      {runs.length === 0 ? (
        <Empty>No state runs recorded yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-3 font-medium sm:pl-6">Minion</th>
                <th className="px-4 py-3 font-medium">Last run</th>
                <th className="px-4 py-3 font-medium">Summary</th>
                <th className="px-4 py-3 font-medium">States</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.minion_id} className="border-t align-middle">
                  <td className="px-4 py-3 sm:pl-6">
                    <Link to={`/minions/${encodeURIComponent(run.minion_id)}`} className="font-medium hover:text-accent">
                      {run.minion_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <Link to={`/jobs/${run.jid}`} className="font-mono hover:text-accent">
                      {run.fun}
                    </Link>
                    <div className="text-xs text-muted" title={formatAbsolute(run.returned_at)}>
                      {formatRelative(run.returned_at, now)}
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className={run.failed ? 'text-danger' : 'text-online'}>
                      {run.failed ? `${run.failed} failed` : `${run.succeeded}/${run.total} ok`}
                    </span>
                    {run.changed > 0 && <span className="text-muted"> · {run.changed} changed</span>}
                  </td>
                  <td className="px-4 py-3">
                    <StateDots states={run.states} />
                    {run.states.length > 60 && <span className="text-muted">{run.total} states</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {never.length > 0 && (
        <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">
          No state run recorded for: {never.join(', ')}
        </p>
      )}
    </>
  )
}

export function JobsPage() {
  const now = useNow()
  const [tab, setTab] = useTab(TABS, 'all')
  return (
    <>
      <PageHeader title="Jobs" subtitle="Every job, kept longer than the master's job cache." />
      <Card className={`${FILL} overflow-hidden`}>
        <div className="px-2 sm:px-4">
          <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Job views" />
        </div>
        {tab === 'all' ? <AllJobs now={now} /> : <StateRunsTab now={now} />}
      </Card>
    </>
  )
}
