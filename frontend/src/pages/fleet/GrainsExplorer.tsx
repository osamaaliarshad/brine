import { ChevronRight, Columns3, Search } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useGrainKeys, useGrainValues } from '@/api/queries'
import type { MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { Pill } from '@/components/ui'
import { cn } from '@/lib/cn'

function ValueRow({
  text,
  minions,
  total,
  statusOf,
  muted = false,
}: {
  text: string
  minions: string[]
  total: number
  statusOf: Record<string, MinionStatus>
  muted?: boolean
}) {
  const [open, setOpen] = useState(false)
  const share = total ? Math.round((minions.length / total) * 100) : 0
  return (
    <li className="border-t first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/40 sm:px-6"
      >
        <ChevronRight className={cn('size-4 shrink-0 text-muted transition-transform', open && 'rotate-90')} aria-hidden />
        <span className="min-w-0 flex-1 truncate">
          {muted ? <span className="text-muted">{text}</span> : <Pill title={text}>{text}</Pill>}
        </span>
        <span className="hidden h-2 w-40 overflow-hidden rounded-full bg-surface-2 sm:block" aria-hidden>
          <span className={cn('block h-full rounded-full', muted ? 'bg-offline' : 'bg-accent')} style={{ width: `${share}%` }} />
        </span>
        <span className="w-24 shrink-0 text-right text-sm tabular-nums">
          {minions.length} <span className="text-muted">· {share}%</span>
        </span>
      </button>
      {open && (
        <div className="flex flex-wrap gap-2 px-4 pb-4 pl-11 sm:px-6 sm:pl-13">
          {minions.map((m) => (
            <MinionChip key={m} id={m} status={statusOf[m]} />
          ))}
        </div>
      )}
    </li>
  )
}

/** Pick any grain and see how its values are spread across the fleet. */
export function GrainsExplorer({
  statusOf,
  columnGrains,
  onAddColumn,
}: {
  statusOf: Record<string, MinionStatus>
  /** Grains already shown as Fleet columns. */
  columnGrains: string[]
  onAddColumn: (grain: string) => void
}) {
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState('')
  const keys = useGrainKeys(true)
  const grain = params.get('grain') ?? columnGrains[0] ?? 'osfinger'
  const dist = useGrainValues(grain)
  const select = (key: string) => {
    const next = new URLSearchParams(params)
    next.set('grain', key)
    setParams(next, { replace: true })
  }
  const needle = filter.trim().toLowerCase()
  const shownKeys = (keys.data ?? []).filter((k) => !needle || k.key.toLowerCase().includes(needle))

  return (
    <div className="grid border-t md:grid-cols-[16rem_1fr]">
      <div className="border-b md:border-r md:border-b-0">
        <label className="m-3 flex h-9 items-center gap-2 rounded-lg border bg-bg px-2.5">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find a grain…"
            aria-label="Find a grain"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
        <ul aria-label="Grains" className="max-h-64 overflow-y-auto pb-2 md:max-h-[32rem]">
          {shownKeys.map((k) => (
            <li key={k.key}>
              <button
                type="button"
                onClick={() => select(k.key)}
                aria-current={k.key === grain ? 'true' : undefined}
                className={cn(
                  'flex w-full items-center justify-between gap-2 px-4 py-1.5 text-left font-mono text-[13px] hover:bg-surface-2',
                  k.key === grain && 'bg-surface-2 text-accent',
                )}
              >
                <span className="truncate">{k.key}</span>
                <span className="text-xs text-muted tabular-nums">{k.minions}</span>
              </button>
            </li>
          ))}
          {keys.isSuccess && shownKeys.length === 0 && <li className="px-4 py-2 text-sm text-muted">No grains match.</li>}
        </ul>
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h2 className="truncate font-mono text-lg">{grain}</h2>
            {dist.data && (
              <p className="text-sm text-muted">
                {dist.data.values.length} distinct value{dist.data.values.length === 1 ? '' : 's'} across{' '}
                {dist.data.total - dist.data.missing.length} of {dist.data.total} minions
              </p>
            )}
          </div>
          {!columnGrains.includes(grain) && (
            <button
              type="button"
              onClick={() => onAddColumn(grain)}
              className="flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-surface-2"
            >
              <Columns3 className="size-4" aria-hidden />
              Add as a Fleet column
            </button>
          )}
        </div>
        {dist.isPending ? (
          <p className="px-6 py-10 text-center text-muted">Loading…</p>
        ) : dist.isError ? (
          <p className="px-6 py-10 text-center text-muted">Couldn't load {grain}: {dist.error.message}</p>
        ) : (
          <ul aria-label={`Values of ${grain}`}>
            {dist.data.values.map((v) => (
              <ValueRow key={v.text} text={v.text} minions={v.minions} total={dist.data.total} statusOf={statusOf} />
            ))}
            {dist.data.missing.length > 0 && (
              <ValueRow text="Not reported" minions={dist.data.missing} total={dist.data.total} statusOf={statusOf} muted />
            )}
          </ul>
        )}
      </div>
    </div>
  )
}
