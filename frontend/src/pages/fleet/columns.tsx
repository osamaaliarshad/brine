import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { MinionSummary } from '@/api/types'
import { Pill } from '@/components/ui'
import { isInventoryKey, keyDescription, missingLabel } from '@/lib/inventoryKey'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { cellText, type SortKey } from '@/pages/fleet/model'

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
  const inventory = isInventoryKey(grain)
  return {
    key: `col:${grain}`,
    label,
    title: keyDescription(grain),
    render: (m) => {
      // A package or check the minion hasn't answered for is left out: unknown, not missing.
      if (inventory && !(grain in m.columns))
        return (
          <span className="text-muted" title="No answer from this minion yet, or its last answer was cut short">
            ?
          </span>
        )
      const value = m.columns[grain]
      const text = cellText(value)
      if (text !== null) return <Pill title={text}>{text}</Pill>
      return (
        <span className="text-muted" title={inventory && value === null ? missingLabel(grain) : undefined}>
          —
        </span>
      )
    },
  }
}
