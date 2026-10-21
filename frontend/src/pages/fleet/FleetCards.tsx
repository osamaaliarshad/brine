import { Link } from 'react-router'
import type { Column, MinionSummary } from '@/api/types'
import { Pill } from '@/components/ui'
import { isInventoryKey, missingLabel, NO_ANSWER_CELL } from '@/lib/inventoryKey'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { type Cell, columnCell } from '@/pages/fleet/model'

/**
 * One column's value on a card. A grain's value speaks for itself; a package's version or a
 * check's value goes with its name, and a card says when it's missing or unknown too.
 */
function CardValue({ column, cell }: { column: Column; cell: Cell }) {
  const inventory = isInventoryKey(column.grain)
  if (cell.kind === 'value') {
    const text = inventory ? `${column.label} ${cell.text}` : cell.text
    return <Pill title={`${column.label}: ${cell.text}`}>{text}</Pill>
  }
  if (!inventory) return null
  if (cell.kind === 'unknown') return <span title={NO_ANSWER_CELL}>{column.label}: ?</span>
  return (
    <span>
      {column.label}: {cell.kind === 'empty' ? '(empty)' : missingLabel(column.grain).toLowerCase()}
    </span>
  )
}

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
                {columns.map((c) => (
                  <CardValue key={c.grain} column={c} cell={columnCell(m, c.grain)} />
                ))}
              </div>
            )}
          </Link>
        </li>
      ))}
    </ul>
  )
}
