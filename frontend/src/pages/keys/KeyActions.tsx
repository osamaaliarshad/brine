import { ChevronDown, MoreHorizontal } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import type { Key, KeyAction } from '@/api/types'
import type { KeyActionTarget } from '@/components/KeyActionDialog'
import { ACTIONS_FOR } from '@/pages/keys/rules'

const LABEL: Record<KeyAction, string> = { accept: 'Accept', reject: 'Reject…', delete: 'Delete…' }

type KeyLike = Pick<Key, 'id' | 'key_state' | 'fingerprint'>

/** Accept up front when it applies; reject and delete tucked into a menu. `labelled` shows the
 *  menu as a "Manage key" button (the minion page) instead of a bare icon (table rows). */
export function KeyActions({
  k,
  onPick,
  labelled = false,
}: {
  k: KeyLike
  onPick: (target: KeyActionTarget) => void
  labelled?: boolean
}) {
  const [open, setOpen] = useState(false)
  // The menu is placed against the window, so a table's scroll container can't clip it.
  const [place, setPlace] = useState<CSSProperties>({})
  const ref = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const actions = ACTIONS_FOR[k.key_state]
  const pick = (action: KeyAction) => {
    setOpen(false)
    onPick({ id: k.id, state: k.key_state, fingerprint: k.fingerprint, action })
  }

  const toggle = () => {
    const rect = button.current?.getBoundingClientRect()
    if (!open && rect) {
      const right = window.innerWidth - rect.right
      // Open upward when there isn't room for the menu below the button.
      setPlace(
        window.innerHeight - rect.bottom > 120 ? { top: rect.bottom + 4, right } : { bottom: window.innerHeight - rect.top + 4, right },
      )
    }
    setOpen((o) => !o)
  }

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent | KeyboardEvent) => {
      const outside =
        event instanceof KeyboardEvent ? event.key === 'Escape' : !ref.current?.contains(event.target as Node)
      if (outside) setOpen(false)
    }
    // A fixed menu would drift away from its button: close it instead.
    const closeNow = () => setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    window.addEventListener('scroll', closeNow, true)
    window.addEventListener('resize', closeNow)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
      window.removeEventListener('scroll', closeNow, true)
      window.removeEventListener('resize', closeNow)
    }
  }, [open])

  return (
    <div ref={ref} className="relative flex items-center justify-end gap-1">
      {actions.includes('accept') && (
        <button
          type="button"
          onClick={() => pick('accept')}
          aria-label={`Accept ${k.id}`}
          className="h-8 rounded-lg border border-accent/50 bg-accent/10 px-3 text-sm font-medium hover:bg-accent/20"
        >
          Accept
        </button>
      )}
      <button
        ref={button}
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={labelled ? undefined : `More actions for ${k.id}`}
        className={
          labelled
            ? 'flex h-10 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-surface-2'
            : 'flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg'
        }
      >
        {labelled ? (
          <>
            Manage key
            <ChevronDown className="size-4 text-muted" aria-hidden />
          </>
        ) : (
          <MoreHorizontal className="size-4" aria-hidden />
        )}
      </button>
      {open && (
        <div role="menu" style={place} className="fixed z-40 w-40 rounded-xl border bg-surface p-1.5 shadow-xl">
          {actions
            .filter((a) => a !== 'accept')
            .map((a) => (
              <button
                key={a}
                type="button"
                role="menuitem"
                onClick={() => pick(a)}
                className="flex w-full rounded-lg px-2.5 py-2 text-left text-sm text-danger hover:bg-surface-2"
              >
                {LABEL[a]}
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
