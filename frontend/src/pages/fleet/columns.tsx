import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { MinionSummary } from '@/api/types'
import { Pill } from '@/components/ui'
import { keyDescription, missingLabel, NO_ANSWER_CELL } from '@/lib/inventoryKey'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { columnCell, type SortKey } from '@/pages/fleet/model'

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
      render: (m) => (
        <div>
          <Link to={`/minions/${encodeURIComponent(m.id)}`} className="font-medium hover:text-accent">
            {m.id}
          </Link>
          <div className="text-sm text-muted">{m.ip ?? '—'}</div>
        </div>
      ),
    },
    { key: 'connection', label: 'Connection', render: (m, now) => <ConnectionCell minion={m} now={now} /> },
    {
      key: 'os',
      label: 'OS / Salt',
      render: (m) => (
        <div>
          <div>{m.os ?? '—'}</div>
          <div className="text-sm text-muted">{m.salt_version ? `Salt ${m.salt_version}` : ''}</div>
        </div>
      ),
    },
  ]
}

/** A grain's, package's or check's column. */
export function grainColumn(grain: string, label: string): TableColumn {
  return {
    key: `col:${grain}`,
    label,
    title: keyDescription(grain),
    render: (m) => {
      const cell = columnCell(m, grain)
      switch (cell.kind) {
        case 'value':
          return <Pill title={cell.text}>{cell.text}</Pill>
        case 'empty':
          return <span className="text-muted">(empty)</span>
        case 'missing':
          return (
            <span className="text-muted" title={missingLabel(grain)}>
              —
            </span>
          )
        case 'unknown':
          return (
            <span className="text-muted" title={NO_ANSWER_CELL}>
              ?
            </span>
          )
      }
    },
  }
}
