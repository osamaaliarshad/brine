import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useKeyAction } from '@/api/queries'
import type { KeyAction, KeyActionResult, KeyState } from '@/api/types'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { needsTypedConfirmation } from '@/pages/keys/rules'

export type KeyActionTarget = { id: string; state: KeyState; fingerprint: string | null; action: KeyAction }

const VERB: Record<KeyAction, string> = { accept: 'Accept', reject: 'Reject', delete: 'Delete' }

const Code = ({ children }: { children: ReactNode }) => <code className="font-mono text-[13px]">{children}</code>

function Explanation({ id, state, action }: { id: string; state: KeyState; action: KeyAction }) {
  const minion = <span className="font-medium text-fg">{id}</span>
  if (action === 'accept')
    return (
      <p>
        The master will trust {minion} and send it jobs and states. Check the fingerprint below matches what the
        minion reports: <Code>salt-call --local key.finger</Code>
      </p>
    )
  if (action === 'reject')
    return state === 'accepted' ? (
      <p>
        {minion} is accepted now. Rejecting cuts it off straight away: it stops getting jobs, and salt-minion on it
        exits. You can accept it again later from the Rejected list.
      </p>
    ) : (
      <p>
        The master will refuse {minion}, and salt-minion on it exits. You can accept it later from the Rejected list.
      </p>
    )
  return state === 'accepted' ? (
    <>
      <p>
        The master forgets {minion} and stops sending it jobs. brine keeps its job history.
      </p>
      <p className="mt-2">
        If salt-minion is still running there, it asks to be accepted again (as pending) the next time it restarts.
        To retire the machine, stop salt-minion on it first.
      </p>
    </>
  ) : (
    <p>
      The master forgets this key. If salt-minion is still running on {minion}, it sends its key again (as pending)
      the next time it starts.
    </p>
  )
}

export function KeyActionDialog({
  target,
  onClose,
  onDone,
}: {
  target: KeyActionTarget
  onClose: () => void
  onDone?: (result: KeyActionResult) => void
}) {
  const { id, state, fingerprint, action } = target
  const mutation = useKeyAction()
  const [typed, setTyped] = useState('')
  const titleId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)
  const typing = needsTypedConfirmation(action, state)
  const ready = (!typing || typed === id) && (action !== 'accept' || !!fingerprint) && !mutation.isPending
  const danger = action !== 'accept'

  // Typed confirmations focus the input (autoFocus); otherwise the safe choice, Cancel. `typing`
  // is fixed for the dialog's life, so a live update re-rendering the page doesn't move focus.
  useEffect(() => {
    if (!typing) cancelRef.current?.focus()
  }, [typing])

  const busy = mutation.isPending
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, busy])

  const submit = () => {
    if (!ready) return
    mutation.mutate(
      { id, action, state, fingerprint: action === 'accept' ? fingerprint : undefined, confirm: typing ? typed : undefined },
      {
        onSuccess: (result) => {
          onDone?.(result)
          onClose()
        },
      },
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !mutation.isPending) onClose()
      }}
    >
      <Card className="w-full max-w-md p-6 shadow-2xl">
        <div role="dialog" aria-modal="true" aria-labelledby={titleId}>
          <h2 id={titleId} className="text-lg font-semibold">
            {VERB[action]} {id}'s key?
          </h2>
          <div className="mt-3 text-sm text-muted">
            <Explanation id={id} state={state} action={action} />
          </div>

          {action === 'accept' && (
            <div className="mt-4 rounded-lg border bg-surface-2/50 px-3 py-2">
              <div className="text-xs text-muted">Fingerprint</div>
              <code className="font-mono text-sm break-all">{fingerprint ?? 'Not known yet'}</code>
            </div>
          )}

          <form
            className="mt-5"
            onSubmit={(event) => {
              event.preventDefault()
              submit()
            }}
          >
            {typing && (
              <label className="block text-sm">
                Type <span className="font-mono font-medium">{id}</span> to confirm
                <input
                  autoFocus
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  className="mt-1.5 h-10 w-full rounded-lg border bg-bg px-3 font-mono text-sm outline-none focus:border-accent"
                />
              </label>
            )}
            {mutation.isError && (
              <p role="alert" className="mt-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm">
                {mutation.error.message}
              </p>
            )}
            <p className="mt-4 text-xs text-muted">Recorded in the audit log.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                ref={cancelRef}
                type="button"
                onClick={onClose}
                disabled={mutation.isPending}
                className="h-10 rounded-lg border px-4 text-sm hover:bg-surface-2 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!ready}
                className={cn(
                  'h-10 rounded-lg px-4 text-sm font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-40',
                  danger ? 'bg-danger text-white' : 'bg-accent text-accent-fg',
                )}
              >
                {mutation.isPending ? `${VERB[action].replace(/e$/, '')}ing…` : `${VERB[action]} key`}
              </button>
            </div>
          </form>
        </div>
      </Card>
    </div>
  )
}
