import { CircleCheck, CircleX, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { useIssues } from '@/api/queries'
import type { Issue, IssueSeverity } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'

const SEVERITY: Record<IssueSeverity, { label: string; icon: LucideIcon; tone: string }> = {
  critical: { label: 'Critical', icon: CircleX, tone: 'text-danger' },
  warning: { label: 'Warning', icon: TriangleAlert, tone: 'text-warn' },
  info: { label: 'Info', icon: Info, tone: 'text-muted' },
}

const FILTERS: (IssueSeverity | 'all')[] = ['all', 'critical', 'warning', 'info']

function IssueRow({ issue, now }: { issue: Issue; now: number }) {
  const { icon: Icon, tone } = SEVERITY[issue.severity]
  return (
    <li className="flex gap-4 border-t px-4 py-4 sm:px-6">
      <Icon className={cn('mt-0.5 size-5 shrink-0', tone)} aria-label={SEVERITY[issue.severity].label} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <span className="font-medium">{issue.title}</span>
          {issue.since && (
            <span className="text-sm text-muted" title={formatAbsolute(issue.since)}>
              {formatRelative(issue.since, now)}
            </span>
          )}
        </div>
        {issue.detail && <p className="mt-0.5 text-sm text-muted">{issue.detail}</p>}
        {(issue.minion_id || issue.jid) && (
          <div className="mt-2 flex gap-4 text-sm">
            {issue.minion_id &&
              (issue.key.startsWith('key:') ? (
                // A pending key isn't a minion yet: its fingerprint is what to look at.
                <Link to="/keys?state=pending" className="text-accent hover:underline">
                  Review on the Keys page
                </Link>
              ) : (
                <Link to={`/minions/${encodeURIComponent(issue.minion_id)}`} className="text-accent hover:underline">
                  Open {issue.minion_id}
                </Link>
              ))}
            {issue.jid && (
              <Link to={`/jobs/${issue.jid}`} className="text-accent hover:underline">
                View job
              </Link>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

export function IssuesPage() {
  const now = useNow()
  const query = useIssues()
  const [params, setParams] = useSearchParams()
  const filter = FILTERS.find((f) => f === params.get('severity')) ?? 'all'
  const issues = query.data ?? []
  const count = (f: (typeof FILTERS)[number]) => (f === 'all' ? issues.length : issues.filter((i) => i.severity === f).length)
  const shown = filter === 'all' ? issues : issues.filter((i) => i.severity === filter)

  return (
    <>
      <PageHeader title="Issues" subtitle="Things in the fleet that need a human." />
      <Card className="overflow-hidden">
        <div role="tablist" aria-label="Filter by severity" className="flex flex-wrap gap-2 p-3 sm:p-4">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              role="tab"
              aria-selected={filter === f}
              onClick={() => {
                const next = new URLSearchParams(params)
                if (f === 'all') next.delete('severity')
                else next.set('severity', f)
                setParams(next, { replace: true })
              }}
              className={cn(
                'flex h-10 items-center gap-2 rounded-lg border px-3 text-sm hover:bg-surface-2',
                filter === f && 'border-accent bg-accent/10',
              )}
            >
              {f === 'all' ? 'All' : SEVERITY[f].label}
              <span className="rounded-md bg-surface-2 px-1.5 text-xs tabular-nums text-muted">{count(f)}</span>
            </button>
          ))}
        </div>
        {query.isPending ? (
          <div className="border-t px-6 py-12 text-center text-muted">Checking the fleet…</div>
        ) : query.isError ? (
          <div className="border-t px-6 py-12 text-center text-muted">Couldn't load issues: {query.error.message}</div>
        ) : shown.length === 0 ? (
          <div className="flex flex-col items-center gap-2 border-t px-6 py-14 text-center">
            <CircleCheck className="size-8 text-online" aria-hidden />
            <p className="font-medium">{issues.length === 0 ? 'All clear' : 'Nothing at this level'}</p>
            <p className="text-sm text-muted">
              brine checks connections, keys, presence, state runs, failed jobs and Salt versions.
            </p>
          </div>
        ) : (
          <ul aria-label="Issues">
            {shown.map((issue) => (
              <IssueRow key={issue.key} issue={issue} now={now} />
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}
