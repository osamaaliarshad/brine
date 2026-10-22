import type { ReactNode } from 'react'
import type { MinionStatus } from '@/api/types'
import { cn } from '@/lib/cn'

const DOT: Record<MinionStatus, string> = {
  online: 'bg-online',
  offline: 'bg-offline',
  stale: 'bg-warn',
  unknown: 'border-2 border-dashed border-muted bg-transparent',
}

export function StatusDot({ status, className }: { status: MinionStatus; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('inline-block size-2.5 shrink-0 rounded-full', DOT[status], className)}
    />
  )
}

/** Monospace chip for grain values (sites, branches, versions). */
export function Pill({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-block max-w-56 truncate rounded-md bg-surface-2 px-2 py-0.5 align-middle font-mono text-[13px] text-fg"
    >
      {children}
    </span>
  )
}

/** Small label under a value, e.g. "Cached". */
export function Badge({ children, title, tone = 'muted' }: {
  children: ReactNode
  title?: string
  tone?: 'muted' | 'warn' | 'danger'
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-block rounded-md px-1.5 py-px text-xs',
        tone === 'warn' ? 'bg-warn/15 text-warn' : tone === 'danger' ? 'bg-danger/15 text-danger' : 'bg-surface-2 text-muted',
      )}
    >
      {children}
    </span>
  )
}

/**
 * `fill`: a page's one big panel. It reaches down to the bottom of the window at least, with room
 * to spare inside when there isn't much in it; past it, the page scrolls. It's a column, so a part
 * of it (a picker list) can take the height that's left.
 */
export function Card({
  children,
  className,
  fill = false,
}: {
  children: ReactNode
  className?: string
  fill?: boolean
}) {
  return <div className={cn('rounded-2xl border bg-surface', fill && 'flex grow flex-col', className)}>{children}</div>
}
