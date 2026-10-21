import { ShieldAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useInventoryChanges, useInventoryValues } from '@/api/queries'
import type { InventoryDistribution, MinionStatus } from '@/api/types'
import {
  describeSource,
  INVENTORY_SETTINGS,
  keyLabel,
  missingLabel,
  NO_ANSWER,
  NO_ANSWER_DETAIL,
} from '@/lib/inventoryKey'
import { formatAbsolute, formatRelative, relativeRange } from '@/lib/time'
import type { ReadNow } from '@/lib/useReadNow'
import { ChangeList } from '@/pages/fleet/ChangeList'
import { ReadNowBar } from '@/pages/fleet/ReadNowBar'
import { ValueRow, ValuesHeader } from '@/pages/fleet/ValueRow'

const HOUR = 3600_000

function spread(d: InventoryDistribution): string {
  const having = d.values.reduce((n, v) => n + v.minions.length, 0)
  const noun = d.kind === 'package' ? 'version' : 'value'
  const text = `${d.values.length} distinct ${noun}${d.values.length === 1 ? '' : 's'} across ${having} of ${d.total} minions`
  return d.kind === 'check' && d.name ? `From the ${d.source} check · ${text}` : text
}

function Refused({ source, why }: { source: string; why: string }) {
  return (
    <div className="mx-4 mt-4 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm sm:mx-6">
      <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <div>
        <div className="font-medium">brine can't read {describeSource(source)}</div>
        <div className="mt-1 text-muted">
          {why.replace(/\.$/, '')}.{' '}
          <Link to={INVENTORY_SETTINGS} className="text-fg underline underline-offset-2 hover:text-accent">
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
  if (!newest) return <span>{NO_ANSWER}</span>
  const range = oldest && Date.parse(newest) - Date.parse(oldest) > HOUR ? relativeRange(oldest, newest, now) : null
  if (!range) return <span title={formatAbsolute(newest)}>Read {formatRelative(newest, now)}</span>
  return (
    <span>
      Read between <span title={formatAbsolute(oldest)}>{range[0]}</span> and{' '}
      <span title={formatAbsolute(newest)}>{range[1]}</span>
    </span>
  )
}

function ReadAndAsk({ d, now, read }: { d: InventoryDistribution; now: number; read: ReadNow }) {
  return (
    <div className="border-t">
      {/* The answers for this entry come with its source's reads. */}
      <ReadNowBar
        read={read}
        minion={null}
        watch={{ key: d.source, at: d.newest_read_at }}
        title="Read every online minion's packages and checks again"
      >
        <span className="text-muted">
          <ReadSummary oldest={d.oldest_read_at} newest={d.newest_read_at} now={now} />
        </span>
      </ReadNowBar>
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
  read,
  action,
}: {
  itemKey: string
  statusOf: Record<string, MinionStatus>
  now: number
  /** The signed-in person may run commands: offer Run on these. */
  canRun: boolean
  read: ReadNow
  /** Beside the heading (Add as a Fleet column). */
  action?: ReactNode
}) {
  const dist = useInventoryValues(itemKey)
  const label = keyLabel(itemKey)
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
                canRun={canRun}
              />
            ))}
            {dist.data.missing.length > 0 && (
              <ValueRow
                text={missingLabel(itemKey)}
                minions={dist.data.missing}
                total={dist.data.total}
                statusOf={statusOf}
                muted
                canRun={canRun}
              />
            )}
            {dist.data.unknown.length > 0 && (
              <ValueRow
                text={NO_ANSWER}
                title={NO_ANSWER_DETAIL}
                minions={dist.data.unknown}
                total={dist.data.total}
                statusOf={statusOf}
                muted
                canRun={canRun}
              />
            )}
          </ul>
          <ReadAndAsk d={dist.data} now={now} read={read} />
          <Changes itemKey={itemKey} read={!!dist.data.newest_read_at} statusOf={statusOf} now={now} />
        </>
      )}
    </>
  )
}
