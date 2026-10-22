import { Check, ChevronDown } from 'lucide-react'
import { type KeyboardEvent, type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'

/*
 * brine's own dropdown lists, in place of the browser's (a <select>'s, a <datalist>'s), which look
 * like the operating system's rather than part of the app. Select picks one of a few values;
 * Combobox suggests values for a text box as you type. Both follow the WAI-ARIA patterns, and
 * share the popup and its options so they look the same.
 */

// Under its control (or over it, see Popup), like the app's other popovers.
const POPUP = 'absolute z-30 flex flex-col overflow-hidden rounded-xl border bg-surface shadow-xl'
// Scrolls inside the popup, shrinking with it. `relative` makes it the options' offsetParent,
// for keepInView.
const LIST = 'relative max-h-64 min-h-0 overflow-y-auto p-1 outline-none'
const HEADING = 'px-2 pt-2 pb-1 text-xs font-medium uppercase tracking-wider text-muted'
const NOTE = 'px-2 py-1.5 text-xs text-muted'

// The popup at its tallest (max-h-64 and the borders); the least it's worth shrinking to below
// its control before it opens above instead; and the least it ever shrinks to (three options).
const TALLEST = 258
const ENOUGH = 160
const SHORTEST = 96
// Between the control and the popup, and between the popup and the edge of the room.
const GAP = 12

/** Scroll the list just enough to show `option`, and its group's heading when it's the first under
 * it. (scrollIntoView would scroll the page, and a card the list is clipped by, too.) */
function keepInView(option: HTMLElement) {
  const list = option.closest<HTMLElement>('[role="listbox"]')
  if (!list) return
  const group = option.closest<HTMLElement>('[role="group"]')
  const first = group?.querySelector('[role="option"]') === option
  const top = first && group ? group.offsetTop : option.offsetTop
  const bottom = option.offsetTop + option.offsetHeight
  if (top < list.scrollTop) list.scrollTop = top
  else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight
}

/** Where a key moves the highlight among `count` options (-1 is none), or null for other keys. */
function step(key: string, current: number, count: number, wrap: boolean): number | null {
  if (count === 0) return null
  switch (key) {
    case 'ArrowDown':
      return current < count - 1 ? current + 1 : wrap ? 0 : current
    case 'ArrowUp':
      return current > 0 ? current - 1 : wrap || current < 0 ? count - 1 : current
    case 'Home':
      return 0
    case 'End':
      return count - 1
    default:
      return null
  }
}

/** The room above and below `anchor`: to the window's edges, or to those of an ancestor that cuts
 * off what overflows it (the Fleet card has overflow-hidden). */
function roomAround(anchor: HTMLElement): { above: number; below: number } {
  let top = 0
  let bottom = window.innerHeight
  for (let el = anchor.parentElement; el; el = el.parentElement) {
    if (getComputedStyle(el).overflowY === 'visible') continue
    const rect = el.getBoundingClientRect()
    top = Math.max(top, rect.top)
    bottom = Math.min(bottom, rect.bottom)
  }
  const rect = anchor.getBoundingClientRect()
  return { above: rect.top - top - GAP, below: bottom - rect.bottom - GAP }
}

/**
 * The popup, as wide as its control's wrapper (its parent). It opens below, shorter if it must;
 * above when there's little room below and more above. That's decided as it opens, so it doesn't
 * jump about as the options change.
 *
 * A press inside it leaves focus where it was (the text box, or the list), so a click on an
 * option, or on the scrollbar, doesn't blur it and close the list first.
 */
function Popup({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<{ up: boolean; height?: number }>({ up: false })
  useLayoutEffect(() => {
    const anchor = ref.current?.parentElement
    if (!anchor) return
    const { above, below } = roomAround(anchor)
    if (below >= TALLEST) return
    const up = below < ENOUGH && above > below
    setPlace({ up, height: Math.max(up ? above : below, SHORTEST) })
  }, [])
  return (
    <div
      ref={ref}
      onMouseDown={(event) => event.preventDefault()}
      style={{ maxHeight: place.height }}
      className={cn(POPUP, place.up ? 'bottom-full mb-1' : 'top-full mt-1', className)}
    >
      {children}
    </div>
  )
}

/** One choice, highlighted while it's the active one (by the arrow keys or the mouse). */
function Option({
  id,
  active,
  selected,
  title,
  onHover,
  onPick,
  className,
  children,
}: {
  id: string
  active: boolean
  selected: boolean
  title?: string
  onHover: () => void
  onPick: () => void
  className?: string
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (active && ref.current) keepInView(ref.current)
  }, [active])
  return (
    <div
      ref={ref}
      id={id}
      role="option"
      aria-selected={selected}
      title={title}
      // On a move, not on entering: a list scrolled by the keyboard under a still mouse keeps
      // its highlight.
      onMouseMove={active ? undefined : onHover}
      onClick={onPick}
      className={cn(
        'flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm',
        active && 'bg-surface-2',
        className,
      )}
    >
      {children}
    </div>
  )
}

export type SelectOption<V extends string> = { value: V; label: string }

/**
 * A button that opens a list to pick one value from, like a <select>. Its name is `label` and the
 * choice ("Target type Glob"). A value no option has shows `placeholder`, and the name is then
 * just `label`.
 */
export function Select<V extends string>({
  label,
  value,
  options,
  onChange,
  placeholder,
  disabled = false,
  className,
  buttonClassName,
}: {
  /** What it picks, for screen readers: on screen, the choice or the placeholder says it. */
  label: string
  value: V
  options: readonly SelectOption<V>[]
  onChange: (value: V) => void
  placeholder?: string
  disabled?: boolean
  /** On the wrapper, whose width the list takes at least: size and place it with this. */
  className?: string
  buttonClassName?: string
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const typed = useRef({ text: '', at: 0 })
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const id = useId()
  const [labelId, valueId, listId] = [`${id}-label`, `${id}-value`, `${id}-list`]
  const chosen = options.findIndex((o) => o.value === value)
  const current = Math.min(active, options.length - 1)
  // Opened before there's anything to choose from (still loading), it shows once there is.
  const shown = open && !disabled && options.length > 0

  useEffect(() => {
    if (shown) list.current?.focus()
  }, [shown])

  const show = () => {
    setActive(Math.max(chosen, 0))
    typed.current.text = ''
    setOpen(true)
  }
  const hide = () => {
    setOpen(false)
    button.current?.focus()
  }
  const pick = (i: number) => {
    hide()
    const option = options[i]
    if (option && option.value !== value) onChange(option.value)
  }

  // Letters typed in quick succession spell the start of an option; the same letter again steps
  // to the next option starting with it.
  const typeAhead = (letter: string, at: number) => {
    const char = letter.toLowerCase()
    const text = at - typed.current.at < 500 ? typed.current.text + char : char
    typed.current = { text, at }
    const again = [...text].every((c) => c === char)
    const start = again ? char : text
    const from = again ? current + 1 : current
    for (let n = 0; n < options.length; n++) {
      const i = (from + n) % options.length
      if (options[i]!.label.toLowerCase().startsWith(start)) {
        setActive(i)
        break
      }
    }
  }

  const onListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next = step(event.key, current, options.length, false)
    if (next !== null) {
      event.preventDefault()
      setActive(next)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      pick(current)
    } else if (event.key === 'Escape') {
      // Only the list closes, not a popover it may be in.
      event.preventDefault()
      event.stopPropagation()
      hide()
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      typeAhead(event.key, event.timeStamp)
    }
  }

  return (
    <div className={cn('relative', className)}>
      <span id={labelId} hidden>
        {label}
      </span>
      <button
        ref={button}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={shown}
        aria-controls={shown ? listId : undefined}
        aria-labelledby={chosen >= 0 ? `${labelId} ${valueId}` : labelId}
        // Enter and Space click it; the arrows open it too, as they do a <select>.
        onClick={() => (open ? hide() : show())}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
          event.preventDefault()
          show()
        }}
        // While it's open, the list keeps focus (its blur would close it before this click does).
        onMouseDown={(event) => {
          if (shown) event.preventDefault()
        }}
        onBlur={() => {
          if (!shown) setOpen(false)
        }}
        className={cn(
          'flex h-9 w-full items-center gap-2 rounded-lg border bg-bg px-2.5 text-left text-sm hover:bg-surface-2 disabled:pointer-events-none',
          buttonClassName,
        )}
      >
        <span id={valueId} className={cn('min-w-0 flex-1 truncate', chosen < 0 && 'text-muted')}>
          {chosen >= 0 ? options[chosen]!.label : placeholder}
        </span>
        <ChevronDown
          className={cn('size-4 shrink-0 text-muted transition-transform', shown && 'rotate-180')}
          aria-hidden
        />
      </button>
      {shown && (
        <Popup className="left-0 w-max min-w-full max-w-[calc(100vw-2rem)]">
          <div
            ref={list}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-labelledby={labelId}
            aria-activedescendant={`${id}-${current}`}
            onKeyDown={onListKeyDown}
            onBlur={() => setOpen(false)}
            className={LIST}
          >
            {options.map((o, i) => (
              <Option
                key={o.value}
                id={`${id}-${i}`}
                active={i === current}
                selected={i === chosen}
                onHover={() => setActive(i)}
                onPick={() => pick(i)}
              >
                <Check className={cn('size-4 shrink-0 text-accent', i !== chosen && 'invisible')} aria-hidden />
                <span className="min-w-0 wrap-anywhere">{o.label}</span>
              </Option>
            ))}
          </div>
        </Popup>
      )}
    </div>
  )
}

export type ComboboxOption = {
  value: string
  /** Shown in mono; the value itself when left out. */
  label?: string
  /** Muted after it: what it is ("package"). */
  tag?: string
  /** Muted at the end: "3 minions". */
  hint?: string
  title?: string
}

export type ComboboxGroup = {
  label: string
  options: readonly ComboboxOption[]
  /** A muted line under its options: "Searching…", "Type to narrow…". */
  note?: string
}

/**
 * A text box that suggests values as you type, under headings. Enter on a highlighted one, or a
 * click, picks it; Enter with none highlighted is left to the form, for what's typed. The caller
 * narrows the groups to what's typed; a group with no options and no note isn't shown.
 * `children` sit beside the box (an Add button), and the list spans them too.
 */
export function Combobox({
  label,
  placeholder,
  value,
  onChange,
  groups,
  onPick,
  className,
  children,
}: {
  label: string
  placeholder?: string
  value: string
  onChange: (value: string) => void
  groups: readonly ComboboxGroup[]
  onPick: (value: string) => void
  className?: string
  children?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  // By value, not position: options that arrive later (a search's answer) don't move it.
  const [activeValue, setActiveValue] = useState<string | null>(null)
  const id = useId()
  const listId = `${id}-list`
  const shownGroups = groups.filter((g) => g.options.length > 0 || g.note)
  const options = shownGroups.flatMap((g) => g.options)
  const expanded = open && shownGroups.length > 0
  const active = expanded ? options.findIndex((o) => o.value === activeValue) : -1

  const close = () => {
    setOpen(false)
    setActiveValue(null)
  }
  const pick = (picked: string) => {
    close()
    onPick(picked)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        event.preventDefault()
        setOpen(true)
        const next = step(event.key, active, options.length, true)
        if (next !== null) setActiveValue(options[next]!.value)
        break
      }
      case 'Enter':
        if (active >= 0) {
          event.preventDefault()
          pick(options[active]!.value)
        } else close() // and the form takes what's typed
        break
      case 'Escape':
        if (!expanded) break
        // Only the list closes, not the popover it may be in.
        event.preventDefault()
        event.stopPropagation()
        close()
        break
    }
  }

  let index = 0 // each option's place in `options`, across the groups
  return (
    <div className={cn('relative flex gap-2', className)}>
      <input
        role="combobox"
        aria-label={label}
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={active >= 0 ? `${id}-${active}` : undefined}
        aria-autocomplete="list"
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={placeholder}
        onChange={(event) => {
          onChange(event.target.value)
          setOpen(true)
          setActiveValue(null)
        }}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onBlur={close}
        onKeyDown={onKeyDown}
        className="h-9 min-w-0 flex-1 rounded-lg border bg-bg px-2.5 font-mono text-sm outline-none placeholder:font-sans placeholder:text-muted focus:border-accent"
      />
      {children}
      {expanded && (
        <Popup className="inset-x-0">
          <div id={listId} role="listbox" aria-label={label} className={LIST}>
            {shownGroups.map((group, g) => (
              <div key={group.label} role="group" aria-labelledby={`${id}-group-${g}`}>
                <div id={`${id}-group-${g}`} className={HEADING}>
                  {group.label}
                </div>
                {group.options.map((option) => {
                  const i = index++
                  return (
                    <Option
                      key={option.value}
                      id={`${id}-${i}`}
                      active={i === active}
                      selected={i === active}
                      title={option.title}
                      onHover={() => setActiveValue(option.value)}
                      onPick={() => pick(option.value)}
                      className="items-baseline"
                    >
                      <span className="min-w-0 flex-1 font-mono text-[13px] break-all">
                        {option.label ?? option.value}
                      </span>
                      {option.tag && (
                        <>
                          {' '}
                          <span className="text-xs text-muted">{option.tag}</span>
                        </>
                      )}
                      {option.hint && (
                        <>
                          {' '}
                          <span className="shrink-0 text-xs text-muted tabular-nums">{option.hint}</span>
                        </>
                      )}
                    </Option>
                  )
                })}
                {group.note && <div className={NOTE}>{group.note}</div>}
              </div>
            ))}
          </div>
        </Popup>
      )}
    </div>
  )
}
