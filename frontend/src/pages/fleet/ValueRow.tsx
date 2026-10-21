import { ChevronRight, TerminalSquare } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import type { MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { Badge, Pill } from '@/components/ui'
import { cn } from '@/lib/cn'
import { keyKind, keyLabel } from '@/lib/inventoryKey'

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

/** One value and the minions that have it; opens to list them. */
export function ValueRow({
  text,
  minions,
  total,
  statusOf,
  muted = false,
  title,
  canRun = false,
}: {
  text: string
  minions: string[]
  total: number
  statusOf: Record<string, MinionStatus>
  /** Not a value: "Not reported", "No answer yet". */
  muted?: boolean
  /** On hover, when there's more to say than `text`. */
  title?: string
  /** The signed-in person may run commands: offer Run on these when open. */
  canRun?: boolean
}) {
  const [open, setOpen] = useState(false)
  const share = total ? Math.round((minions.length / total) * 100) : 0
  const empty = text === ''
  return (
    <li className="border-t first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/40 sm:px-6"
      >
        <ChevronRight className={cn('size-4 shrink-0 text-muted transition-transform', open && 'rotate-90')} aria-hidden />
        <span className="min-w-0 flex-1 truncate">
          {muted || empty ? (
            <span className="text-muted" title={title ?? (empty ? undefined : text)}>
              {empty ? '(empty)' : text}
            </span>
          ) : (
            <Pill title={title ?? text}>{text}</Pill>
          )}
        </span>
        <span className="hidden h-2 w-40 overflow-hidden rounded-full bg-surface-2 sm:block" aria-hidden>
          <span className={cn('block h-full rounded-full', muted ? 'bg-offline' : 'bg-accent')} style={{ width: `${share}%` }} />
        </span>
        <span className="w-24 shrink-0 text-right text-sm tabular-nums">
          {minions.length} <span className="text-muted">· {share}%</span>
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 pl-11 sm:px-6 sm:pl-13">
          {canRun && (
            <div className="mb-3">
              <RunOnThese minions={minions} />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {minions.map((m) => (
              <MinionChip key={m} id={m} status={statusOf[m]} />
            ))}
          </div>
        </div>
      )}
    </li>
  )
}

/** The explorer's heading: a grain's, package's or check's name, what it is, and how it's spread. */
export function ValuesHeader({ itemKey, summary, action }: { itemKey: string; summary?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="truncate font-mono text-lg">{keyLabel(itemKey)}</h2>
          <Badge>{keyKind(itemKey)}</Badge>
        </div>
        {summary && <p className="text-sm text-muted">{summary}</p>}
      </div>
      {action}
    </div>
  )
}
