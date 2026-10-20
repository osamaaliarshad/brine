import { Link } from 'react-router'
import type { MinionStatus } from '@/api/types'
import { StatusDot } from '@/components/ui'

/** A minion's name with its status dot, linking to its page. */
export function MinionChip({ id, status }: { id: string; status?: MinionStatus }) {
  return (
    <Link
      to={`/minions/${encodeURIComponent(id)}`}
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm hover:border-accent hover:text-accent"
    >
      <StatusDot status={status ?? 'unknown'} className="size-2" />
      {id}
    </Link>
  )
}
