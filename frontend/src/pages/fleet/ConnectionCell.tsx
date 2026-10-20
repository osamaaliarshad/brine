import type { ReactNode } from 'react'
import type { MinionSummary } from '@/api/types'
import { Badge, StatusDot } from '@/components/ui'
import { formatAbsolute, formatRelative } from '@/lib/time'

export function ConnectionCell({ minion, now }: { minion: MinionSummary; now: number }) {
  const seen = (
    <span title={formatAbsolute(minion.last_seen_at)}>
      {minion.last_seen_at ? `Last seen ${formatRelative(minion.last_seen_at, now)}` : 'Never seen'}
    </span>
  )
  const grainsNote =
    minion.grains_source === 'master_cache'
      ? "Grains come from the master's cache; when they were collected is unknown."
      : `Grains as of ${formatAbsolute(minion.grains_at)}`

  let label: ReactNode
  let badge: ReactNode = null
  switch (minion.status) {
    case 'online':
      label = 'Online'
      if (minion.grains_source === 'master_cache') badge = <Badge title={grainsNote}>Cached</Badge>
      break
    case 'offline':
      label = seen
      badge = <Badge title={`Showing the last known state. ${grainsNote}`}>Cached</Badge>
      break
    case 'stale':
      label = seen
      badge = (
        <Badge tone="warn" title="brine has no recent presence check, so this is the last known state.">
          Stale
        </Badge>
      )
      break
    case 'unknown':
      label = 'Never seen'
      badge = <Badge title="brine has never seen this minion report.">Unknown</Badge>
      break
  }
  return (
    <div className="flex items-start gap-2.5">
      <StatusDot status={minion.status} className="mt-1.5" />
      <div className="flex flex-col items-start gap-1">
        <span className="text-[15px]">{label}</span>
        {badge}
      </div>
    </div>
  )
}
