import type { ReactNode } from 'react'

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-4xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-lg text-muted">{subtitle}</p>}
      </div>
      {actions}
    </div>
  )
}

/** Stand-in body for pages that haven't been built yet. */
export function ComingSoon({ phase }: { phase: string }) {
  return (
    <div className="rounded-2xl border border-dashed bg-surface/50 p-10 text-center text-muted">
      Coming in {phase}. See <code className="font-mono text-fg">docs/backlog.md</code>.
    </div>
  )
}
