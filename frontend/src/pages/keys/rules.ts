import type { KeyAction, KeyActionResult, KeyState } from '@/api/types'

/** Which actions apply to a key in each state (the server checks the same). */
export const ACTIONS_FOR: Record<KeyState, KeyAction[]> = {
  pending: ['accept', 'reject', 'delete'],
  accepted: ['reject', 'delete'],
  rejected: ['accept', 'delete'],
  denied: ['delete'],
}

/** Deleting, or cutting off an accepted minion, takes typing its name (the server checks too). */
export function needsTypedConfirmation(action: KeyAction, state: KeyState) {
  return action === 'delete' || (action === 'reject' && state === 'accepted')
}

const DONE: Record<KeyActionResult['key_state'], string> = {
  accepted: 'accepted',
  rejected: 'rejected',
  deleted: 'deleted',
  pending: 'deleted, and the minion sent it again (pending)',
  denied: 'denied',
}

/** "rover-04's key was accepted." */
export function describeResult(result: KeyActionResult) {
  return `${result.id}'s key was ${DONE[result.key_state]}.`
}
