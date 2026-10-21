import { Columns3, Search } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { useSearchParams } from 'react-router'
import { INVENTORY_KEYS_LIMIT, useGrainKeys, useGrainValues, useInventoryKeys } from '@/api/queries'
import type { InventoryKey, MinionStatus } from '@/api/types'
import { cn } from '@/lib/cn'
import { isInventoryKey, keyDescription, keyLabel } from '@/lib/inventoryKey'
import { useDebounced } from '@/lib/useDebounced'
import { InventoryValues } from '@/pages/fleet/InventoryValues'
import { ValueRow, ValuesHeader } from '@/pages/fleet/ValueRow'

// Packages are only searched from this many letters: one letter would match most of them.
const MIN_SEARCH = 2
const SEARCH_DELAY_MS = 250

const HEADING = 'px-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted'
const NOTE = 'px-4 py-2 text-sm text-muted'

function pickClass(selected: boolean) {
  return cn(
    'flex w-full items-center justify-between gap-2 px-4 py-1.5 text-left font-mono text-[13px] hover:bg-surface-2',
    selected && 'bg-surface-2 text-accent',
  )
}

/** Like the server's search: a package by its name, a check's entry by its name or the check's. */
function matches(k: InventoryKey, needle: string): boolean {
  return k.name.toLowerCase().includes(needle) || (k.kind === 'check' && k.source.toLowerCase().includes(needle))
}

function PackagePicker({ filter, selected, onSelect }: { filter: string; selected: string; onSelect: (key: string) => void }) {
  const typed = filter.trim()
  const settled = useDebounced(typed, SEARCH_DELAY_MS)
  const keys = useInventoryKeys(settled.length >= MIN_SEARCH ? settled : '')
  const needle = typed.toLowerCase()
  const shown = (keys.data ?? []).filter((k) => !needle || matches(k, needle))
  const short = typed.length < MIN_SEARCH
  // What's typed hasn't been searched for yet (still typing, or the answer is on its way).
  const searching = !short && (settled !== typed || keys.isPlaceholderData)

  return (
    <div className="border-t pt-3">
      <div className={HEADING}>Packages and checks</div>
      <ul aria-label="Packages and checks" className="max-h-56 overflow-y-auto pb-2 md:max-h-72">
        {shown.map((k) => (
          <li key={k.key}>
            <button
              type="button"
              onClick={() => onSelect(k.key)}
              aria-current={k.key === selected ? 'true' : undefined}
              title={`${keyDescription(k.key)}, on ${k.minions} minion${k.minions === 1 ? '' : 's'}`}
              className={pickClass(k.key === selected)}
            >
              <span className="min-w-0 flex-1 truncate">{keyLabel(k.key)}</span>
              <span className="font-sans text-xs text-muted">{k.kind}</span>
              <span className="min-w-5 text-right text-xs text-muted tabular-nums">{k.minions}</span>
            </button>
          </li>
        ))}
        {keys.isError ? (
          <li className={NOTE}>Couldn't load packages and checks: {keys.error.message}</li>
        ) : shown.length === 0 && searching ? (
          <li className={NOTE}>Searching…</li>
        ) : shown.length === 0 && keys.isSuccess && !short ? (
          <li className={NOTE}>No packages or checks match.</li>
        ) : null}
        {keys.isSuccess && short && <li className={NOTE}>Type 2 or more letters to find a package.</li>}
        {keys.isSuccess && !searching && keys.data.length >= INVENTORY_KEYS_LIMIT && (
          <li className={NOTE}>Showing the first {INVENTORY_KEYS_LIMIT}. Type more to narrow them down.</li>
        )}
      </ul>
    </div>
  )
}

function GrainValues({
  grain,
  statusOf,
  action,
}: {
  grain: string
  statusOf: Record<string, MinionStatus>
  action?: ReactNode
}) {
  const dist = useGrainValues(grain)
  const summary =
    dist.data &&
    `${dist.data.values.length} distinct value${dist.data.values.length === 1 ? '' : 's'} across ` +
      `${dist.data.total - dist.data.missing.length} of ${dist.data.total} minions`
  return (
    <>
      <ValuesHeader itemKey={grain} summary={summary} action={action} />
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
    </>
  )
}

/** Pick any grain, package or check and see how its values are spread across the fleet. */
export function GrainsExplorer({
  statusOf,
  columnGrains,
  onAddColumn,
  now,
  canRun,
}: {
  statusOf: Record<string, MinionStatus>
  /** Grains, packages and checks already shown as Fleet columns. */
  columnGrains: string[]
  onAddColumn: (grain: string) => void
  now: number
  /** The signed-in person may run commands. */
  canRun: boolean
}) {
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState('')
  const keys = useGrainKeys(true)
  const grain = params.get('grain') ?? columnGrains[0] ?? 'osfinger'
  const select = (key: string) => {
    const next = new URLSearchParams(params)
    next.set('grain', key)
    setParams(next, { replace: true })
  }
  const needle = filter.trim().toLowerCase()
  const shownKeys = (keys.data ?? []).filter((k) => !needle || k.key.toLowerCase().includes(needle))
  const addColumn = !columnGrains.includes(grain) && (
    <button
      type="button"
      onClick={() => onAddColumn(grain)}
      className="flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-surface-2"
    >
      <Columns3 className="size-4" aria-hidden />
      Add as a Fleet column
    </button>
  )

  return (
    <div className="grid border-t md:grid-cols-[16rem_1fr]">
      <div className="border-b md:border-r md:border-b-0">
        <label className="m-3 flex h-9 items-center gap-2 rounded-lg border bg-bg px-2.5">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find a grain or package…"
            aria-label="Find a grain or package"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
        <div className={HEADING}>Grains</div>
        <ul aria-label="Grains" className="max-h-56 overflow-y-auto pb-2 md:max-h-72">
          {shownKeys.map((k) => (
            <li key={k.key}>
              <button
                type="button"
                onClick={() => select(k.key)}
                aria-current={k.key === grain ? 'true' : undefined}
                className={pickClass(k.key === grain)}
              >
                <span className="truncate">{k.key}</span>
                <span className="text-xs text-muted tabular-nums">{k.minions}</span>
              </button>
            </li>
          ))}
          {keys.isSuccess && shownKeys.length === 0 && <li className={NOTE}>No grains match.</li>}
        </ul>
        <PackagePicker filter={filter} selected={grain} onSelect={select} />
      </div>

      <div className="min-w-0">
        {isInventoryKey(grain) ? (
          <InventoryValues key={grain} itemKey={grain} statusOf={statusOf} now={now} canRun={canRun} action={addColumn} />
        ) : (
          <GrainValues grain={grain} statusOf={statusOf} action={addColumn} />
        )}
      </div>
    </div>
  )
}
