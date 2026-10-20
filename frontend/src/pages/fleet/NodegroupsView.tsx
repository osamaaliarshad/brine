import { useNodegroups } from '@/api/queries'
import type { MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { Card } from '@/components/ui'

function Group({
  name,
  expression,
  members,
  statusOf,
}: {
  name: string
  expression?: string
  members: string[]
  statusOf: Record<string, MinionStatus>
}) {
  const online = members.filter((m) => statusOf[m] === 'online').length
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">{name}</h3>
        <span className="text-sm text-muted">
          {members.length} minion{members.length === 1 ? '' : 's'} · {online} online
        </span>
      </div>
      {expression && <code className="mt-1 block font-mono text-xs text-muted">{expression}</code>}
      <div className="mt-3 flex flex-wrap gap-2">
        {members.length ? (
          members.map((m) => <MinionChip key={m} id={m} status={statusOf[m]} />)
        ) : (
          <span className="text-sm text-muted">No minions match right now.</span>
        )}
      </div>
    </Card>
  )
}

/** The master's nodegroups (from its config) and who's in each. */
export function NodegroupsView({ statusOf }: { statusOf: Record<string, MinionStatus> }) {
  const query = useNodegroups(true)
  if (query.isPending) return <p className="border-t px-6 py-10 text-center text-muted">Loading nodegroups…</p>
  if (query.isError)
    return <p className="border-t px-6 py-10 text-center text-muted">Couldn't load nodegroups: {query.error.message}</p>
  const { groups, ungrouped } = query.data
  if (groups.length === 0)
    return (
      <p className="border-t px-6 py-10 text-center text-muted">
        No nodegroups configured. They're defined under <code className="font-mono">nodegroups:</code> in the master config.
      </p>
    )
  return (
    <div className="grid gap-3 border-t p-3 sm:gap-4 sm:p-4 lg:grid-cols-2">
      {groups.map((g) => (
        <Group key={g.name} name={g.name} expression={g.expression} members={g.members} statusOf={statusOf} />
      ))}
      {ungrouped.length > 0 && <Group name="Not in any nodegroup" members={ungrouped} statusOf={statusOf} />}
    </div>
  )
}
