import { Check, CheckCheck, CircleCheck, CircleX, Eye, EyeOff, Info, TriangleAlert, Undo2, type LucideIcon } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useIssues, useMarkIssues } from '@/api/queries'
import type { Issue, IssueSeverity } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { INVENTORY_SETTINGS } from '@/lib/inventoryKey'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { CONTROL } from '@/pages/fleet/FleetToolbar'

const SEVERITY: Record<IssueSeverity, { label: string; icon: LucideIcon; tone: string; markAll: string }> = {
  critical: { label: 'Critical', icon: CircleX, tone: 'text-danger', markAll: 'Mark all critical as read' },
  warning: { label: 'Warning', icon: TriangleAlert, tone: 'text-warn', markAll: 'Mark all warnings as read' },
  info: { label: 'Info', icon: Info, tone: 'text-muted', markAll: 'Mark all info as read' },
}

const FILTERS: (IssueSeverity | 'all')[] = ['all', 'critical', 'warning', 'info']

const FILTER_BUTTON = 'flex h-10 items-center gap-2 rounded-lg border px-3 text-sm hover:bg-surface-2'

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function IssueRow({ issue, now, onMark }: { issue: Issue; now: number; onMark: () => void }) {
  const { icon: Icon, tone } = SEVERITY[issue.severity]
  const titleId = useId()
  const buttonId = useId()
  // Salt won't let brine read packages or a check: Settings has the permissions to add.
  const settings = issue.key.startsWith('inventory:')
  return (
    <li className="flex gap-4 border-t px-4 py-4 sm:px-6">
      <Icon
        className={cn('mt-0.5 size-5 shrink-0', issue.read ? 'text-muted' : tone)}
        aria-label={SEVERITY[issue.severity].label}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <span id={titleId} className={cn('font-medium', issue.read && 'text-muted')}>
            {issue.title}
          </span>
          {issue.since && (
            <span className="text-sm text-muted" title={formatAbsolute(issue.since)}>
              {formatRelative(issue.since, now)}
            </span>
          )}
        </div>
        {issue.detail && <p className="mt-0.5 text-sm text-muted">{issue.detail}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          {settings && (
            <Link to={INVENTORY_SETTINGS} className="text-accent hover:underline">
              Open Settings › Packages and checks
            </Link>
          )}
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
          <button
            type="button"
            data-mark
            // A double-click's second click lands on the row that took this one's place.
            onClick={(event) => event.detail < 2 && onMark()}
            aria-labelledby={`${buttonId} ${titleId}`}
            className="ml-auto flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-2.5 text-fg transition-colors hover:bg-surface-2"
          >
            {issue.read ? (
              <Undo2 className="size-4 text-muted" aria-hidden />
            ) : (
              <Check className="size-4 text-muted" aria-hidden />
            )}
            <span id={buttonId}>{issue.read ? 'Mark as unread' : 'Mark as read'}</span>
          </button>
        </div>
      </div>
    </li>
  )
}

export function IssuesPage() {
  const now = useNow()
  const query = useIssues()
  const mark = useMarkIssues()
  const [params, setParams] = useSearchParams()
  const filter = FILTERS.find((f) => f === params.get('severity')) ?? 'all'
  const showRead = params.get('read') === 'show'
  const issues = query.data ?? []
  const atLevel = (f: (typeof FILTERS)[number]) => (f === 'all' ? issues : issues.filter((i) => i.severity === f))
  const listed = atLevel(filter)
  const unread = listed.filter((i) => !i.read)
  const readIssues = listed.filter((i) => i.read)

  const setParam = (name: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null) next.delete(name)
    else next.set(name, value)
    setParams(next, { replace: true })
  }

  // When rows leave a list, keyboard focus goes to the next row's button there, or else to the
  // read toggle or the filter, rather than back to the top of the page.
  const card = useRef<HTMLDivElement>(null)
  const moved = useRef<{ keys: Set<string>; read: boolean; index: number } | null>(null)
  useEffect(() => {
    const m = moved.current
    if (!m || query.data?.some((i) => m.keys.has(i.key) && i.read !== m.read)) return
    const buttons = card.current?.querySelectorAll<HTMLElement>(`[data-list="${m.read ? 'unread' : 'read'}"] [data-mark]`)
    const next =
      buttons?.[Math.min(m.index, buttons.length - 1)] ??
      card.current?.querySelector<HTMLElement>('[data-read-toggle]') ??
      card.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
    next?.focus()
    moved.current = null
  }, [query.data])

  // What happened, for screen readers; shown too when an issue changed and stays unread.
  const [said, setSaid] = useState<{ text: string; changed: boolean } | null>(null)
  const markIssues = (which: Issue[], read: boolean, index = 0) => {
    moved.current = { keys: new Set(which.map((i) => i.key)), read, index }
    const readBefore = readIssues.length
    mark.mutate(
      { issues: which, read },
      {
        onSuccess: (result) => {
          if (!read) {
            const left = readBefore - which.length
            setSaid({ text: `Marked as unread. ${plural(left, 'read issue')} left.`, changed: false })
            return
          }
          const marked = result?.marked.length ?? 0
          const changed = which.filter((i) => result?.changed.includes(i.key))
          const text = [
            marked > 0 && `Marked as read. ${plural(readBefore + marked, 'read issue')} ${showRead ? 'below' : 'hidden'}.`,
            changed.length === 1 && `${changed[0]!.title} changed in the meantime, so it stays unread.`,
            changed.length > 1 && `${changed.length} issues changed in the meantime, so they stay unread.`,
          ]
          setSaid({ text: text.filter(Boolean).join(' '), changed: changed.length > 0 })
        },
        onError: () => {
          moved.current = null
          setSaid(null)
        },
      },
    )
  }
  const readListId = useId()

  return (
    <>
      <PageHeader
        title="Issues"
        subtitle="Things in the fleet that need a human."
        actions={
          unread.length > 0 && (
            <button type="button" onClick={() => markIssues(unread, true)} className={CONTROL}>
              <CheckCheck className="size-4 text-muted" aria-hidden />
              {filter === 'all' ? 'Mark all as read' : SEVERITY[filter].markAll}
            </button>
          )
        }
      />
      {mark.isError && (
        <p role="alert" className="mb-4 text-sm text-danger">
          Couldn't mark {mark.variables.issues.length === 1 ? 'it' : 'them'} as {mark.variables.read ? 'read' : 'unread'}:{' '}
          {mark.error.message}
        </p>
      )}
      <p role="status" className={said?.changed ? 'mb-4 text-sm text-muted' : 'sr-only'}>
        {said?.text}
      </p>
      <Card fill className="overflow-hidden">
        <div ref={card} className="contents">
          <div className="flex flex-wrap items-center gap-2 p-3 sm:p-4">
            <div role="tablist" aria-label="Filter by severity" className="flex flex-wrap gap-2">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  role="tab"
                  aria-selected={filter === f}
                  onClick={() => setParam('severity', f === 'all' ? null : f)}
                  className={cn(FILTER_BUTTON, filter === f && 'border-accent bg-accent/10')}
                >
                  {f === 'all' ? 'All' : SEVERITY[f].label}
                  <span className="rounded-md bg-surface-2 px-1.5 text-xs tabular-nums text-muted">
                    {atLevel(f).filter((i) => !i.read).length}
                  </span>
                </button>
              ))}
            </div>
            {readIssues.length > 0 && (
              <button
                type="button"
                data-read-toggle
                aria-expanded={showRead}
                aria-controls={readListId}
                onClick={() => setParam('read', showRead ? null : 'show')}
                className={cn(FILTER_BUTTON, 'ml-auto')}
              >
                {showRead ? (
                  <EyeOff className="size-4 text-muted" aria-hidden />
                ) : (
                  <Eye className="size-4 text-muted" aria-hidden />
                )}
                {showRead ? 'Hide read' : `Show ${readIssues.length} read`}
              </button>
            )}
          </div>
          {query.isPending ? (
            <div className="border-t px-6 py-12 text-center text-muted">Checking the fleet…</div>
          ) : query.isError ? (
            <div className="border-t px-6 py-12 text-center text-muted">Couldn't load issues: {query.error.message}</div>
          ) : (
            <>
              {unread.length === 0 ? (
                <div className="flex flex-col items-center gap-2 border-t px-6 py-14 text-center">
                  <CircleCheck className="size-8 text-online" aria-hidden />
                  {readIssues.length > 0 ? (
                    <>
                      <p className="font-medium">Nothing new</p>
                      {!showRead && (
                        <p className="text-sm text-muted">{plural(readIssues.length, 'read issue')} hidden.</p>
                      )}
                    </>
                  ) : (
                    <>
                      <p className="font-medium">{issues.length === 0 ? 'All clear' : 'Nothing at this level'}</p>
                      <p className="text-sm text-muted">
                        brine checks connections, keys, presence, state runs, failed jobs and Salt versions.
                      </p>
                    </>
                  )}
                </div>
              ) : (
                <ul aria-label="Issues" data-list="unread">
                  {unread.map((issue, index) => (
                    <IssueRow key={issue.key} issue={issue} now={now} onMark={() => markIssues([issue], true, index)} />
                  ))}
                </ul>
              )}
              {showRead && readIssues.length > 0 && (
                <>
                  <h2 className="border-t bg-surface-2/40 px-4 py-2 text-xs font-medium uppercase tracking-wider text-muted sm:px-6">
                    Read
                  </h2>
                  <ul id={readListId} aria-label="Read issues" data-list="read">
                    {readIssues.map((issue, index) => (
                      <IssueRow key={issue.key} issue={issue} now={now} onMark={() => markIssues([issue], false, index)} />
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      </Card>
    </>
  )
}
