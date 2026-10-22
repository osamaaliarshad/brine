import { Server, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { Fleet } from '@/api/types'
import { Card, StatusDot } from '@/components/ui'

function Stat({ icon, value, label, title }: {
  icon: ReactNode
  value: number | string
  label: string
  title?: string
}) {
  return (
    <Card className="flex items-center gap-3 px-4 py-4 sm:gap-4 sm:px-6 sm:py-5">
      <span className="hidden size-10 shrink-0 items-center justify-center sm:flex">{icon}</span>
      <div className="min-w-0" title={title}>
        <div className="flex items-center gap-2 text-2xl font-semibold tabular-nums sm:text-3xl">
          <span className="flex sm:hidden">{icon}</span>
          {value}
        </div>
        <div className="text-sm leading-tight text-muted sm:text-base">{label}</div>
      </div>
    </Card>
  )
}

export function StatCards({
  summary,
  attention,
}: {
  summary: Fleet['summary'] | undefined
  /** Critical + warning issues not marked as read. */
  attention: number | undefined
}) {
  const value = (n: number | undefined) => (n === undefined ? '–' : n)
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <Stat
        icon={<Server className="size-5 text-muted sm:size-7" strokeWidth={1.5} />}
        value={value(summary?.total)}
        label="Total minions"
      />
      <Stat icon={<StatusDot status="online" className="size-3 sm:size-4" />} value={value(summary?.online)} label="Online" />
      <Stat icon={<StatusDot status="offline" className="size-3 sm:size-4" />} value={value(summary?.offline)} label="Offline" />
      <Link to="/issues" className="rounded-2xl transition-opacity hover:opacity-80" aria-label="Need attention: see issues">
        <Stat
          icon={<TriangleAlert className="size-5 text-warn sm:size-7" strokeWidth={1.75} />}
          value={value(attention)}
          label="Need attention"
          title="Critical and warning issues you haven't marked as read; see the Issues page"
        />
      </Link>
    </div>
  )
}
