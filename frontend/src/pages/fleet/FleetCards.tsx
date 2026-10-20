import { Link } from 'react-router'
import type { Column, MinionSummary } from '@/api/types'
import { Pill } from '@/components/ui'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { cellText } from '@/pages/fleet/model'

/** The fleet as a list of cards, for phone-width screens. */
export function FleetCards({
  minions,
  columns,
  showOs,
  now,
}: {
  minions: MinionSummary[]
  columns: Column[]
  showOs: boolean
  now: number
}) {
  return (
    <ul className="divide-y border-t" aria-label="Minions">
      {minions.map((m) => (
        <li key={m.id}>
          <Link to={`/minions/${encodeURIComponent(m.id)}`} className="block px-4 py-3 hover:bg-surface-2/40">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-medium">{m.id}</span>
              <span className="text-xs text-muted">{m.ip ?? ''}</span>
            </div>
            <div className="mt-1.5">
              <ConnectionCell minion={m} now={now} />
            </div>
            {(showOs || columns.length > 0) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                {showOs && m.os && (
                  <span>
                    {m.os}
                    {m.salt_version && ` · Salt ${m.salt_version}`}
                  </span>
                )}
                {columns.map((c) => {
                  const text = cellText(m.columns[c.grain])
                  return text === null ? null : (
                    <Pill key={c.grain} title={`${c.label}: ${text}`}>
                      {text}
                    </Pill>
                  )
                })}
              </div>
            )}
          </Link>
        </li>
      ))}
    </ul>
  )
}
