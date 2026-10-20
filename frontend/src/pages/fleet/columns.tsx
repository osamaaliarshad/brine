import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { MinionSummary } from '@/api/types'
import { Pill } from '@/components/ui'
import { ConnectionCell } from '@/pages/fleet/ConnectionCell'
import { cellText, type SortKey } from '@/pages/fleet/model'

export type TableColumn = {
  key: SortKey
  label: string
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

export function grainColumn(grain: string, label: string): TableColumn {
  return {
    key: `col:${grain}`,
    label,
    render: (m) => {
      const text = cellText(m.columns[grain])
      return text === null ? <span className="text-muted">—</span> : <Pill title={text}>{text}</Pill>
    },
  }
}
