import { RefreshCw, ShieldAlert, TerminalSquare } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { ApiError } from '@/api/client'
import { useAskInventory, useInventoryChanges, useInventoryValues } from '@/api/queries'
import type { AskResult, InventoryDistribution, MinionStatus } from '@/api/types'
import { cn } from '@/lib/cn'
import { describeSource, keyLabel, missingLabel } from '@/lib/inventoryKey'
import { formatAbsolute, formatRelative, relativeRange } from '@/lib/time'
import { ChangeList } from '@/pages/fleet/ChangeList'
import { ValueRow, ValuesHeader } from '@/pages/fleet/ValueRow'

const UNKNOWN = 'Unknown (no answer yet, or the last answer was cut short)'
const HOUR = 3600_000

function spread(d: InventoryDistribution): string {
  const having = d.values.reduce((n, v) => n + v.minions.length, 0)
  const noun = d.kind === 'package' ? 'version' : 'value'
  const text = `${d.values.length} distinct ${noun}${d.values.length === 1 ? '' : 's'} across ${having} of ${d.total} minions`
  return d.kind === 'check' && d.name ? `From the ${d.source} check · ${text}` : text
}

/** The Run page with exactly these minions as a list target; the person types the command. */
function RunOnThese({ minions }: { minions: string[] }) {
  return (
    <Link
      to={`/run?${new URLSearchParams({ target: minions.join(','), type: 'list' })}`}
      title="Open Run with these minions as the target. Nothing runs until you preview it and click Run."
      className="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-surface-2"
    >
      <TerminalSquare className="size-4 text-muted" aria-hidden />
      Run on these
    </Link>
  )
}

function Refused({ source, why }: { source: string; why: string }) {
  return (
    <div className="mx-4 mt-4 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm sm:mx-6">
      <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <div>
        <div className="font-medium">brine can't read {describeSource(source)}</div>
        <div className="mt-1 text-muted">
          {why.replace(/\.$/, '')}.{' '}
          <Link to="/settings" className="text-fg underline underline-offset-2 hover:text-accent">
            Settings › Packages and checks
          </Link>{' '}
          has the lines to add to brine's Salt account.
        </div>
      </div>
    </div>
  )
}

/** "Read 2h ago", or "Read between 3h and 20m ago" when the minions were read far apart. */
function ReadSummary({ oldest, newest, now }: { oldest: string | null; newest: string | null; now: number }) {
  if (!newest) return <span>Not read yet</span>
  const range = oldest && Date.parse(newest) - Date.parse(oldest) > HOUR ? relativeRange(oldest, newest, now) : null
  if (!range) return <span title={formatAbsolute(newest)}>Read {formatRelative(newest, now)}</span>
  return (
    <span>
      Read between <span title={formatAbsolute(oldest)}>{range[0]}</span> and{' '}
      <span title={formatAbsolute(newest)}>{range[1]}</span>
    </span>
  )
}

function Asked({ result }: { result: AskResult }) {
  const n = result.asked.length
  const minions = `${n} minion${n === 1 ? '' : 's'}`
  return (
    <div role="status" className="border-t bg-accent/10 px-4 py-2.5 text-sm sm:px-6">
      <p>
        {n === 0
          ? `Nobody was asked${result.reason ? `: ${result.reason}` : ''}.`
          : result.queued
            ? `Reading ${minions} over the next minute; answers appear as they arrive.`
            : `Asked ${minions}; answers appear as they arrive.`}
      </p>
      {Object.entries(result.failed).map(([source, why]) => (
        <p key={source} className="text-danger">
          Couldn't ask for {describeSource(source)}: {why}
        </p>
      ))}
    </div>
  )
}

function ReadAndAsk({ d, now }: { d: InventoryDistribution; now: number }) {
  const ask = useAskInventory()
  return (
    <div className="border-t">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm text-muted sm:px-6">
        <ReadSummary oldest={d.oldest_read_at} newest={d.newest_read_at} now={now} />
        <button
          type="button"
          onClick={() => ask.mutate(null)}
          disabled={ask.isPending}
          title="Ask every online minion for its packages and checks again"
          className="flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-fg hover:bg-surface-2 disabled:opacity-50"
        >
          <RefreshCw className={cn('size-3.5', ask.isPending && 'animate-spin')} aria-hidden />
          Ask now
        </button>
      </div>
      {ask.data && <Asked result={ask.data} />}
      {ask.isError && (
        // Asked too soon is a wait, not a failure.
        <p
          role="alert"
          className={cn(
            'border-t px-4 py-2.5 text-sm sm:px-6',
            ask.error instanceof ApiError && ask.error.status === 429 ? 'text-muted' : 'text-danger',
          )}
        >
          {ask.error.message}
        </p>
      )}
    </div>
  )
}

function Changes({
  itemKey,
  read,
  statusOf,
  now,
}: {
  itemKey: string
  read: boolean
  statusOf: Record<string, MinionStatus>
  now: number
}) {
  const changes = useInventoryChanges({ key: itemKey })
  const note = 'px-4 pb-4 text-sm text-muted sm:px-6'
  return (
    <section className="border-t">
      <h3 className="px-4 pt-4 pb-2 text-xs font-medium uppercase tracking-wider text-muted sm:px-6">Changes</h3>
      {changes.isPending ? (
        <p className={note}>Loading changes…</p>
      ) : changes.isError ? (
        <p className={note}>Couldn't load changes: {changes.error.message}</p>
      ) : changes.data.length === 0 ? (
        <p className={note}>{read ? 'No changes since brine first looked.' : 'No changes yet.'}</p>
      ) : (
        <ChangeList changes={changes.data} now={now} statusOf={statusOf} label={`Changes to ${keyLabel(itemKey)}`} />
      )}
    </section>
  )
}

/** One package or check entry across the fleet: who has which value, who lacks it, who hasn't answered. */
export function InventoryValues({
  itemKey,
  statusOf,
  now,
  canRun,
  action,
}: {
  itemKey: string
  statusOf: Record<string, MinionStatus>
  now: number
  /** The signed-in person may run commands: offer Run on these. */
  canRun: boolean
  /** Beside the heading (Add as a Fleet column). */
  action?: ReactNode
}) {
  const dist = useInventoryValues(itemKey)
  const label = keyLabel(itemKey)
  const runOn = (minions: string[]) => (canRun ? <RunOnThese minions={minions} /> : undefined)
  return (
    <>
      <ValuesHeader itemKey={itemKey} summary={dist.data && spread(dist.data)} action={action} />
      {dist.isPending ? (
        <p className="px-6 py-10 text-center text-muted">Loading…</p>
      ) : dist.isError ? (
        <p className="px-6 py-10 text-center text-muted">
          Couldn't load {label}: {dist.error.message}
        </p>
      ) : (
        <>
          {dist.data.refused && <Refused source={dist.data.source} why={dist.data.refused} />}
          <ul aria-label={`${dist.data.kind === 'package' ? 'Versions' : 'Values'} of ${label}`}>
            {dist.data.values.map((v) => (
              <ValueRow
                key={v.text}
                text={v.text}
                minions={v.minions}
                total={dist.data.total}
                statusOf={statusOf}
                action={runOn(v.minions)}
              />
            ))}
            {dist.data.missing.length > 0 && (
              <ValueRow
                text={missingLabel(itemKey)}
                minions={dist.data.missing}
                total={dist.data.total}
                statusOf={statusOf}
                muted
                action={runOn(dist.data.missing)}
              />
            )}
            {dist.data.unknown.length > 0 && (
              <ValueRow
                text={UNKNOWN}
                minions={dist.data.unknown}
                total={dist.data.total}
                statusOf={statusOf}
                muted
                action={runOn(dist.data.unknown)}
              />
            )}
          </ul>
          <ReadAndAsk d={dist.data} now={now} />
          <Changes itemKey={itemKey} read={!!dist.data.newest_read_at} statusOf={statusOf} now={now} />
        </>
      )}
    </>
  )
}
