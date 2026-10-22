import { ArrowDown, ArrowUp, Columns3, Plus, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { INVENTORY_KEYS_LIMIT, inventoryKeysQuery, useGrainKeys, useInventoryKeys } from '@/api/queries'
import type { Column, GrainKey, InventoryKey } from '@/api/types'
import { Combobox, type ComboboxOption } from '@/components/Listbox'
import { cn } from '@/lib/cn'
import { keyDescription, keyKind, keyLabel } from '@/lib/inventoryKey'
import { useDebounced } from '@/lib/useDebounced'
import { visibleArea } from '@/lib/visibleArea'
import { addGrain, moveGrain } from '@/pages/fleet/columnPrefs'

const ICON_BTN =
  'flex size-7 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30 disabled:hover:bg-transparent'

// As in the explorer: packages are only searched from this many letters (one would match most
// of them), once typing pauses.
const MIN_SEARCH = 2
const SEARCH_DELAY_MS = 250
// More grains than this make a wall to scroll through: typing narrows them instead.
const MAX_GRAINS = 50
// The menu keeps this far inside what can show it: the screen (as its max-w does: 100vw less
// 2rem), or the card it's in.
const GUTTER = 16

const minions = (n: number) => `${n} minion${n === 1 ? '' : 's'}`

/** Like the server's search: a package by its name, a check's entry by its name or the check's. */
function matches(k: InventoryKey, needle: string): boolean {
  return k.name.toLowerCase().includes(needle) || (k.kind === 'check' && k.source.toLowerCase().includes(needle))
}

/** The grains on offer for what's typed: not columns yet, with it anywhere in the key. */
function offeredGrains(keys: GrainKey[], columns: string[], needle: string): GrainKey[] {
  return keys.filter((k) => !columns.includes(k.key) && k.key.toLowerCase().includes(needle))
}

/** The packages and checks on offer from a search's answer (maybe the last one, for less than
 * what's typed now, kept while the next is on its way). */
function offeredInventory(keys: InventoryKey[], columns: string[], needle: string): InventoryKey[] {
  return keys.filter((k) => !columns.includes(k.key) && (!needle || matches(k, needle)))
}

/**
 * What adding `typed` adds when no option is picked: the grain, package or check that is what's
 * typed (a grain by its key first, then a package or check by its name), else the only one on
 * offer, else what's typed, as a grain path.
 */
function typedKey(typed: string, grainKeys: GrainKey[], inventoryKeys: InventoryKey[], columns: string[]): string {
  const needle = typed.toLowerCase()
  const exact =
    grainKeys.find((k) => k.key.toLowerCase() === needle) ??
    inventoryKeys.find((k) => keyLabel(k.key).toLowerCase() === needle)
  if (exact) return exact.key
  const offered = [
    ...offeredGrains(grainKeys, columns, needle).slice(0, MAX_GRAINS),
    ...offeredInventory(inventoryKeys, columns, needle),
  ]
  return offered.length === 1 ? offered[0]!.key : typed
}

function option(key: string, count: number, tag?: string): ComboboxOption {
  return { value: key, label: keyLabel(key), tag, hint: minions(count), title: keyDescription(key) }
}

/** Add any grain, package or check as a column: suggested as you type, or a grain path typed out. */
function AddColumn({ columns, onAdd }: { columns: string[]; onAdd: (key: string) => void }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  // Bumped by every edit and add: an answer awaited for an earlier Enter is then dropped.
  const asked = useRef(0)
  const typed = draft.trim()
  const needle = typed.toLowerCase()
  const grainKeys = useGrainKeys(true)
  const settled = useDebounced(typed, SEARCH_DELAY_MS)
  const short = typed.length < MIN_SEARCH
  // Back to the checks and the packages that differ as soon as the search is cleared, not after
  // the pause.
  const inventory = useInventoryKeys(short || settled.length < MIN_SEARCH ? '' : settled)
  // What's typed hasn't been searched for yet (still typing, or the answer is on its way).
  const searching = !short && (settled !== typed || inventory.isPlaceholderData || inventory.isPending)

  const grains = offeredGrains(grainKeys.data ?? [], columns, needle)
  const found = offeredInventory(inventory.data ?? [], columns, needle)
  // Not searching: the checks, then the packages that differ across the fleet.
  const items = short ? [...found.filter((k) => k.kind === 'check'), ...found.filter((k) => k.kind === 'package')] : found
  // Under the packages and checks: why there are none yet, or how to find others.
  const inventoryNote = () => {
    if (inventory.isError) return `Couldn't load packages and checks: ${inventory.error.message}`
    if (searching) return 'Searching…'
    if (!inventory.isSuccess) return undefined
    if (short) return 'Type 2 or more letters to find any package'
    return inventory.data.length >= INVENTORY_KEYS_LIMIT ? 'Type to narrow…' : undefined
  }

  const add = (key: string) => {
    asked.current++
    onAdd(key)
    setDraft('')
  }

  // Enter (or Add) with no option picked. The packages are looked up for what's typed first (or
  // the answer already in is taken), so a package named in full isn't added as a grain path no
  // minion has just because its search was still on its way.
  const submit = async () => {
    if (!typed) return
    const ask = ++asked.current
    const inventoryKeys = short
      ? (inventory.data ?? [])
      : await queryClient.fetchQuery(inventoryKeysQuery(typed)).catch((): InventoryKey[] => [])
    if (ask === asked.current) add(typedKey(typed, grainKeys.data ?? [], inventoryKeys, columns))
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}
      className="mt-2"
    >
      <Combobox
        label="Add a grain, package or check"
        placeholder="Add a grain, package or check"
        value={draft}
        onChange={(text) => {
          asked.current++
          setDraft(text)
        }}
        onPick={add}
        groups={[
          {
            label: 'Grains',
            options: grains.slice(0, MAX_GRAINS).map((k) => option(k.key, k.minions)),
            note: grains.length > MAX_GRAINS ? 'Type to narrow…' : undefined,
          },
          {
            label: 'Packages and checks',
            options: items.map((k) => option(k.key, k.minions, k.kind)),
            note: inventoryNote(),
          },
        ]}
      >
        <button
          type="submit"
          disabled={!typed}
          className="flex h-9 items-center gap-1 rounded-lg bg-accent px-3 text-sm font-medium text-accent-fg disabled:opacity-40"
        >
          <Plus className="size-4" aria-hidden />
          Add
        </button>
      </Combobox>
    </form>
  )
}

/** Beside a column's label: a grain's path when the label differs, or whether it's a package or check. */
function ColumnNote({ column }: { column: Column }) {
  const kind = keyKind(column.grain)
  if (kind === 'grain')
    return column.label === column.grain ? null : (
      <span className="ml-1.5 font-mono text-xs text-muted">{column.grain}</span>
    )
  const name = keyLabel(column.grain)
  return <span className="ml-1.5 text-xs text-muted">{column.label === name ? kind : `${name} · ${kind}`}</span>
}

export function ColumnsMenu({
  grainColumns,
  builtins,
  hidden,
  customized,
  onToggleBuiltin,
  onChangeGrains,
  onReset,
  buttonClassName,
}: {
  grainColumns: Column[]
  builtins: { key: string; label: string }[]
  hidden: Set<string>
  customized: boolean
  onToggleBuiltin: (key: string) => void
  onChangeGrains: (grains: string[]) => void
  onReset: () => void
  buttonClassName?: string
}) {
  const [open, setOpen] = useState(false)
  // How far right of its usual place (right edge under the button's) the menu goes; left if less
  // than 0.
  const [shift, setShift] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLDivElement>(null)
  const grains = grainColumns.map((c) => c.grain)

  // The button can be at the left of its row (on a phone, or beside the sidebar when the toolbar
  // wraps), where a menu hanging left from it would be cut off by the card or the screen: move it
  // right, as far as it takes to be seen whole.
  useLayoutEffect(() => {
    const width = dialog.current?.offsetWidth
    if (!open || !width || !ref.current) return
    const button = ref.current.getBoundingClientRect()
    const area = visibleArea(ref.current)
    const [lo, hi] = [area.left + GUTTER, area.right - GUTTER]
    const left = button.right - width
    setShift(left < lo ? Math.min(lo - left, hi - button.right) : Math.min(0, hi - button.right))
  }, [open])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent | KeyboardEvent) => {
      const outside =
        event instanceof KeyboardEvent
          ? event.key === 'Escape'
          : !ref.current?.contains(event.target as Node)
      if (outside) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className={buttonClassName}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
      >
        <Columns3 className="size-4" aria-hidden />
        Columns
      </button>
      {open && (
        <div
          ref={dialog}
          role="dialog"
          aria-label="Choose columns"
          style={{ right: -shift }}
          className="absolute right-0 z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border bg-surface p-3 shadow-xl"
        >
          {builtins.map((col) => (
            <label
              key={col.key}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-surface-2"
            >
              <input
                type="checkbox"
                className="accent-[var(--accent)]"
                checked={!hidden.has(col.key)}
                onChange={() => onToggleBuiltin(col.key)}
              />
              {col.label}
            </label>
          ))}

          <div className="mt-3 mb-1 px-2 text-xs font-medium uppercase tracking-wider text-muted">
            Grains & packages
          </div>
          {grainColumns.length === 0 && (
            <p className="px-2 py-1 text-sm text-muted">None. Add a grain, package or check below.</p>
          )}
          <ul>
            {grainColumns.map((col, i) => (
              <li key={col.grain} className="flex items-center gap-1 rounded-lg py-0.5 pr-1 pl-2 hover:bg-surface-2">
                <span className="min-w-0 flex-1 truncate text-sm" title={keyDescription(col.grain)}>
                  {col.label}
                  <ColumnNote column={col} />
                </span>
                <button
                  type="button"
                  className={ICON_BTN}
                  disabled={i === 0}
                  aria-label={`Move ${col.label} left`}
                  onClick={() => onChangeGrains(moveGrain(grains, col.grain, -1))}
                >
                  <ArrowUp className="size-3.5" />
                </button>
                <button
                  type="button"
                  className={ICON_BTN}
                  disabled={i === grainColumns.length - 1}
                  aria-label={`Move ${col.label} right`}
                  onClick={() => onChangeGrains(moveGrain(grains, col.grain, 1))}
                >
                  <ArrowDown className="size-3.5" />
                </button>
                <button
                  type="button"
                  className={ICON_BTN}
                  aria-label={`Remove ${col.label}`}
                  onClick={() => onChangeGrains(grains.filter((g) => g !== col.grain))}
                >
                  <X className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>

          <AddColumn
            columns={grains}
            onAdd={(key) => {
              const next = addGrain(grains, key)
              if (next !== grains) onChangeGrains(next)
            }}
          />

          <div className="mt-3 flex items-center justify-between border-t px-2 pt-2 text-xs text-muted">
            <span>Saved in this browser</span>
            <button
              type="button"
              onClick={onReset}
              disabled={!customized}
              className={cn('hover:text-fg', !customized && 'invisible')}
            >
              Reset to team default
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
