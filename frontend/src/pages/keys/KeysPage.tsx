import { Check, Copy, KeyRound } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'
import { useCapabilities, useKeys, useMe } from '@/api/queries'
import type { Capability, Key, KeyState } from '@/api/types'
import { KeyActionDialog, type KeyActionTarget } from '@/components/KeyActionDialog'
import { PageHeader } from '@/components/PageHeader'
import { Card, StatusDot } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { KeyActions } from '@/pages/keys/KeyActions'
import { describeResult } from '@/pages/keys/rules'

const STATES: { value: KeyState | 'all'; label: string }[] = [
  { value: 'all', label: 'All keys' },
  { value: 'pending', label: 'Pending' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'denied', label: 'Denied' },
]

const STATE_STYLE: Record<KeyState, string> = {
  accepted: 'bg-online/15 text-online',
  pending: 'bg-warn/15 text-warn',
  rejected: 'bg-danger/15 text-danger',
  denied: 'bg-danger/15 text-danger',
}

function Fingerprint({ value }: { value: string | null }) {
  const [copied, setCopied] = useState(false)
  if (!value) return <span className="text-muted">—</span>
  const short = value.length > 23 ? `${value.slice(0, 11)}…${value.slice(-11)}` : value
  return (
    <span className="inline-flex items-center gap-1.5">
      <code className="font-mono text-[13px]" title={value}>
        {short}
      </code>
      <button
        type="button"
        aria-label="Copy fingerprint"
        title="Copy fingerprint"
        className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          })
        }}
      >
        {copied ? <Check className="size-3.5 text-online" /> : <Copy className="size-3.5" />}
      </button>
    </span>
  )
}

function Seen({ k, now }: { k: Key; now: number }) {
  if (k.key_state === 'pending')
    return <span title={formatAbsolute(k.first_seen_at)}>Waiting since {formatRelative(k.first_seen_at, now)}</span>
  if (k.status === null) return <span className="text-muted">—</span>
  return (
    <span className="inline-flex items-center gap-2">
      <StatusDot status={k.status} />
      {k.status === 'online' ? (
        'Online'
      ) : (
        <span title={formatAbsolute(k.last_seen_at)}>
          {k.last_seen_at ? `Last seen ${formatRelative(k.last_seen_at, now)}` : 'Never seen'}
        </span>
      )}
    </span>
  )
}

function Footer({ isAdmin, manage }: { isAdmin: boolean; manage: Capability | undefined }) {
  if (!isAdmin) return <>Admins can accept, reject and delete keys here. Every change is recorded in the audit log.</>
  if (manage?.allowed === false)
    return (
      <>
        Key management is off: brine's Salt account isn't allowed to run{' '}
        {manage.missing.map((fun, i) => (
          <span key={fun}>
            {i > 0 && ', '}
            <code className="font-mono">{fun}</code>
          </span>
        ))}
        . Add {manage.missing.length === 1 ? 'it' : 'them'} under <code className="font-mono">@wheel</code> in its
        external_auth entry (docs/permissions-and-salt-acl.md).
      </>
    )
  return <>Every change is recorded in the audit log.</>
}

export function KeysPage() {
  const now = useNow()
  const query = useKeys()
  const isAdmin = useMe().data?.role === 'admin'
  const capabilities = useCapabilities(isAdmin)
  const manage = capabilities.data?.manage_keys
  // Unknown (salt-api unreachable) still offers the buttons; the server has the final say.
  const canManage = isAdmin && manage?.allowed !== false
  const [target, setTarget] = useState<KeyActionTarget | null>(null)
  // A minion page that just changed a key hands over what happened.
  const handed = (useLocation().state as { notice?: string } | null)?.notice
  const [notice, setNotice] = useState<string | null>(handed ?? null)
  const [params, setParams] = useSearchParams()
  const filter = STATES.find((s) => s.value === params.get('state'))?.value ?? 'all'
  const keys = query.data ?? []
  const count = (state: KeyState | 'all') => (state === 'all' ? keys.length : keys.filter((k) => k.key_state === state).length)
  const shown = filter === 'all' ? keys : keys.filter((k) => k.key_state === filter)
  // Pending keys are what needs a human, so they go first.
  const ordered = [...shown].sort(
    (a, b) => Number(b.key_state === 'pending') - Number(a.key_state === 'pending') || a.id.localeCompare(b.id, undefined, { numeric: true }),
  )
  const pending = count('pending')

  return (
    <>
      <PageHeader title="Keys" subtitle="Minion keys and whether the master trusts them." />

      {pending > 0 && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
          <KeyRound className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <div>
            <span className="font-medium">
              {pending} key{pending === 1 ? '' : 's'} waiting for approval.
            </span>{' '}
            <span className="text-muted">
              Compare fingerprints with the minion (<code className="font-mono">salt-call --local key.finger</code>)
              before accepting.
            </span>
          </div>
        </div>
      )}

      <Card className="overflow-hidden">
        <div role="tablist" aria-label="Filter by key state" className="flex flex-wrap gap-2 p-3 sm:p-4">
          {STATES.filter((s) => s.value === 'all' || count(s.value) > 0 || filter === s.value).map((s) => (
            <button
              key={s.value}
              type="button"
              role="tab"
              aria-selected={filter === s.value}
              onClick={() => {
                const next = new URLSearchParams(params)
                if (s.value === 'all') next.delete('state')
                else next.set('state', s.value)
                setParams(next, { replace: true })
              }}
              className={cn(
                'flex h-10 items-center gap-2 rounded-lg border px-3 text-sm hover:bg-surface-2',
                filter === s.value && 'border-accent bg-accent/10',
              )}
            >
              {s.label}
              <span className="rounded-md bg-surface-2 px-1.5 text-xs tabular-nums text-muted">{count(s.value)}</span>
            </button>
          ))}
        </div>

        {notice && (
          <p role="status" className="border-t bg-accent/10 px-4 py-2.5 text-sm sm:px-6">
            {notice}
          </p>
        )}
        {query.isPending ? (
          <div className="border-t px-6 py-12 text-center text-muted">Loading keys…</div>
        ) : query.isError ? (
          <div className="border-t px-6 py-12 text-center text-muted">Couldn't load keys: {query.error.message}</div>
        ) : ordered.length === 0 ? (
          <div className="border-t px-6 py-12 text-center text-muted">No keys.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium sm:pl-6">Minion</th>
                  <th className="px-4 py-3 font-medium">Key</th>
                  <th className="px-4 py-3 font-medium">Fingerprint</th>
                  <th className="px-4 py-3 font-medium">Seen</th>
                  {canManage && (
                    <th className="px-4 py-3 sm:pr-6">
                      <span className="sr-only">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {ordered.map((k) => (
                  <tr key={k.id} className="border-t align-middle">
                    <td className="px-4 py-3 sm:pl-6">
                      {k.key_state === 'accepted' ? (
                        <Link to={`/minions/${encodeURIComponent(k.id)}`} className="font-medium hover:text-accent">
                          {k.id}
                        </Link>
                      ) : (
                        <span className="font-medium">{k.id}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('rounded-md px-2 py-0.5 text-xs font-medium capitalize', STATE_STYLE[k.key_state])}>
                        {k.key_state}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Fingerprint value={k.fingerprint} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Seen k={k} now={now} />
                    </td>
                    {canManage && (
                      <td className="px-4 py-2 sm:pr-6">
                        <KeyActions k={k} onPick={setTarget} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t px-4 py-3 text-xs text-muted sm:px-6">
          <Footer isAdmin={isAdmin} manage={manage} />
        </div>
      </Card>
      {target && (
        <KeyActionDialog
          target={target}
          onClose={() => setTarget(null)}
          onDone={(result) => setNotice(describeResult(result))}
        />
      )}
    </>
  )
}
