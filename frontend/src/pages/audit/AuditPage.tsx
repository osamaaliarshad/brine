import { Link, useSearchParams } from 'react-router'
import { useAuditLog, useMe } from '@/api/queries'
import type { AuditEntry } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { useKeptFor } from '@/lib/useKeptFor'

const ACTIONS: Record<string, string> = {
  'auth.login': 'Signed in',
  'auth.login_denied': 'Sign-in refused',
  'auth.logout': 'Signed out',
  'pillar.view': 'Viewed pillar',
  'key.accept': 'Accepted key',
  'key.reject': 'Rejected key',
  'key.delete': 'Deleted key',
  'command.run': 'Ran command',
  'command.failed': 'Command failed',
  'command.catch_up': 'Caught up a minion',
  'command.catch_up_cancelled': 'Cancelled a catch-up',
}

const FILTERS = [
  { value: null, label: 'Everything' },
  { value: 'auth.', label: 'Sign-ins' },
  { value: 'command.', label: 'Commands' },
  { value: 'key.', label: 'Keys' },
  { value: 'pillar.', label: 'Data access' },
] as const

function details(entry: AuditEntry): string {
  const d = entry.detail ?? {}
  return Object.entries(d)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ')
}

/** A command reads as what was typed, with its job one click away. */
function Details({ entry }: { entry: AuditEntry }) {
  const d = entry.detail ?? {}
  if (!entry.action.startsWith('command.') || typeof d.command !== 'string') return <>{details(entry) || '—'}</>
  const args = Array.isArray(d.args) ? d.args.map(String) : []
  return (
    <>
      <code className="font-mono text-[13px] text-fg">{[d.command, ...args].join(' ')}</code>
      {typeof d.minions === 'number' && ` · ${d.minions} minion${d.minions === 1 ? '' : 's'}`}
      {d.success === false && ' · failed'}
      {typeof d.jid === 'string' && (
        <>
          {' · '}
          <Link to={`/jobs/${d.jid}`} className="text-accent hover:underline">
            job
          </Link>
        </>
      )}
    </>
  )
}

export function AuditPage() {
  const now = useNow()
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const filter = FILTERS.find((f) => f.value === params.get('action'))?.value ?? null
  const query = useAuditLog(filter)
  const entries = query.data?.pages.flatMap((p) => p.entries) ?? []
  const keptFor = useKeptFor('audit_days')

  if (me.data && me.data.role !== 'admin') {
    return (
      <>
        <PageHeader title="Audit log" />
        <Card className="px-6 py-10 text-center text-muted">The audit log is for admins.</Card>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Audit log" subtitle="Who did what, and when." />
      <Card className="overflow-hidden">
        <div role="tablist" aria-label="Filter the audit log" className="flex flex-wrap gap-2 p-3 sm:p-4">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              role="tab"
              aria-selected={filter === f.value}
              onClick={() => {
                const next = new URLSearchParams(params)
                if (f.value) next.set('action', f.value)
                else next.delete('action')
                setParams(next, { replace: true })
              }}
              className={cn(
                'h-10 rounded-lg border px-3 text-sm hover:bg-surface-2',
                filter === f.value && 'border-accent bg-accent/10',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        {query.isPending ? (
          <div className="border-t px-6 py-12 text-center text-muted">Loading…</div>
        ) : query.isError ? (
          <div className="border-t px-6 py-12 text-center text-muted">Couldn't load the audit log: {query.error.message}</div>
        ) : entries.length === 0 ? (
          <div className="border-t px-6 py-12 text-center text-muted">Nothing recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium sm:pl-6">When</th>
                  <th className="px-4 py-3 font-medium">Who</th>
                  <th className="px-4 py-3 font-medium">What</th>
                  <th className="px-4 py-3 font-medium">Details</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className="border-t align-top">
                    <td className="px-4 py-3 whitespace-nowrap sm:pl-6" title={formatAbsolute(e.at)}>
                      {formatRelative(e.at, now)}
                    </td>
                    <td className="px-4 py-3">{e.actor}</td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          (e.action.endsWith('_denied') ||
                            e.action === 'key.reject' ||
                            e.action === 'key.delete' ||
                            e.action === 'command.failed') &&
                            'text-danger',
                        )}
                      >
                        {ACTIONS[e.action] ?? e.action}
                      </span>
                      {e.target && <span className="text-muted"> · {e.target}</span>}
                    </td>
                    <td className="px-4 py-3 text-muted">
                      <Details entry={e} />
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
              className="rounded-lg border px-4 py-2 text-sm hover:bg-surface-2"
            >
              Load older entries
            </button>
          </div>
        )}
        {keptFor && <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">{keptFor}</p>}
      </Card>
    </>
  )
}
