import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { MinionSummary } from '@/api/types'
import { Pill } from '@/components/ui'
import { keyDescription, missingFor, noAnswerFor } from '@/lib/inventoryKey'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { cellAsOf, columnCell, grainsAsOf, type SortKey } from '@/pages/fleet/model'

export type TableColumn = {
  key: SortKey
  label: string
  /** The header's tooltip. */
  title?: string
  render: (m: MinionSummary, now: number) => ReactNode
}

export function baseColumns(): TableColumn[] {
  return [
    {
      key: 'id',
      label: 'Minion',
      render: (m, now) => (
        <div>
          <Link to={`/minions/${encodeURIComponent(m.id)}`} className="font-medium hover:text-accent">
            {m.id}
          </Link>
          <div className="text-sm text-muted" title={grainsAsOf(m, now) ?? undefined}>
            {m.ip ?? '—'}
          </div>
        </div>
      ),
    },
    { key: 'connection', label: 'Connection', render: (m, now) => <ConnectionCell minion={m} now={now} /> },
    {
      key: 'os',
      label: 'OS / Salt',
      render: (m, now) => (
        <div title={grainsAsOf(m, now) ?? undefined}>
          <div>{m.os ?? '—'}</div>
          <div className="text-sm text-muted">{m.salt_version ? `Salt ${m.salt_version}` : ''}</div>
        </div>
      ),
    },
  ]
}

/** A grain's, package's or check's column. Each cell's hover says what it is in full, then how
 * fresh it is (the grains', or that package's or check's last read). */
export function grainColumn(grain: string, label: string): TableColumn {
  return {
    key: `col:${grain}`,
    label,
    title: keyDescription(grain),
    render: (m, now) => {
      const cell = columnCell(m, grain)
      const asOf = cellAsOf(m, grain, now)
      const hover = (text: string) => (asOf ? `${text}\n${asOf}` : text)
      switch (cell.kind) {
        case 'value':
          return <Pill title={hover(cell.text)}>{cell.text}</Pill>
        case 'empty':
          return (
            <span className="text-muted" title={asOf ?? undefined}>
              (empty)
            </span>
          )
        case 'missing':
          return (
            <span className="text-muted" title={hover(missingFor(m.id, grain))}>
              —
            </span>
          )
        case 'unknown':
          return (
            <span className="text-muted" title={noAnswerFor(m.id)}>
              ?
            </span>
          )
      }
    },
  }
}
