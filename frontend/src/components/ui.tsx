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

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-2xl border bg-surface', className)}>{children}</div>
}
