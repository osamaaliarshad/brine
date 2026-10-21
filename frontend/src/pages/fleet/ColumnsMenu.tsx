import { ArrowDown, ArrowUp, Columns3, Plus, X } from 'lucide-react'
import { type FormEvent, useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useGrainKeys } from '@/api/queries'
import type { Column } from '@/api/types'
import { cn } from '@/lib/cn'
import { keyDescription, keyKind, keyLabel } from '@/lib/inventoryKey'
import { addGrain, moveGrain } from '@/pages/fleet/columnPrefs'

const ICON_BTN =
  'flex size-7 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30 disabled:hover:bg-transparent'

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
  const [draft, setDraft] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const listId = useId()
  const keys = useGrainKeys(open)
  const grains = grainColumns.map((c) => c.grain)

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

  const add = (event: FormEvent) => {
    event.preventDefault()
    const next = addGrain(grains, draft)
    if (next !== grains) onChangeGrains(next)
    setDraft('')
  }

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
          role="dialog"
          aria-label="Choose columns"
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
            <p className="px-2 py-1 text-sm text-muted">None. Add a grain below.</p>
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

          <form onSubmit={add} className="mt-2 flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              list={listId}
              placeholder="Add a grain, e.g. osfinger or hw:model"
              aria-label="Grain to add"
              className="h-9 min-w-0 flex-1 rounded-lg border bg-bg px-2.5 font-mono text-sm outline-none placeholder:font-sans placeholder:text-muted focus:border-accent"
            />
            <datalist id={listId}>
              {keys.data
                ?.filter((k) => !grains.includes(k.key))
                .map((k) => (
                  <option key={k.key} value={k.key}>
                    {`${k.minions} minion${k.minions === 1 ? '' : 's'}`}
                  </option>
                ))}
            </datalist>
            <button
              type="submit"
              disabled={!draft.trim()}
              className="flex h-9 items-center gap-1 rounded-lg bg-accent px-3 text-sm font-medium text-accent-fg disabled:opacity-40"
            >
              <Plus className="size-4" aria-hidden />
              Add
            </button>
          </form>
          <p className="mt-2 px-2 text-xs text-muted">
            For a package or check, open{' '}
            <Link to="/?tab=grains" className="text-fg underline underline-offset-2 hover:text-accent">
              Grains & packages
            </Link>{' '}
            and pick Add as a Fleet column.
          </p>

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
