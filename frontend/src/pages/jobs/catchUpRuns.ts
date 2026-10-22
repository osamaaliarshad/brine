import type { CatchUpRun, JobDetail } from '@/api/types'

export const STATE_LABEL: Record<CatchUpRun['state'], string> = {
  waiting: 'Waiting',
  sending: 'Sending',
  failed: 'Failed',
  sent: 'Caught up',
  expired: 'Expired',
  cancelled: 'Cancelled',
  replaced: 'Replaced',
  refused: 'Not sent',
}

/** Sent, and the minion hasn't answered yet: on its way, not caught up. */
export function unanswered(run: CatchUpRun): boolean {
  return run.state === 'sent' && !run.answered_at
}

/** How a run that may still bring the minion's answer is getting on. */
const STILL_CATCHING_UP: Partial<Record<CatchUpRun['state'], string>> = {
  waiting: "runs when it's back",
  sending: 'sending now',
  sent: 'sent, no answer yet',
}

/** How a minion waiting to catch up is getting on: "runs when it's back". */
export function catchingUpAs(run: CatchUpRun): string {
  return STILL_CATCHING_UP[run.state] ?? STATE_LABEL[run.state].toLowerCase()
}

/** What became of a missing minion's catch-up: "cancelled", "not sent", "sent, no answer". */
export function cameToNothing(run: CatchUpRun): string {
  return unanswered(run) ? 'sent, no answer' : STATE_LABEL[run.state].toLowerCase()
}

export type Missing = {
  /** Waiting to catch up, with the run that may still bring the answer. */
  catchingUp: [string, CatchUpRun][]
  /** No return, and none to come from a catch-up run; with the run that came to nothing, if any. */
  noReturn: [string, CatchUpRun | undefined][]
}

/**
 * A job's minions without a result, as the server sees them: missing, or (with a catch-up run,
 * in neither its results nor missing) waiting to catch up.
 */
export function splitMissing(job: JobDetail): Missing {
  const runOf = new Map(job.catch_up.map((run) => [run.minion_id, run]))
  const settled = new Set([...job.results.map((r) => r.minion_id), ...job.missing])
  return {
    catchingUp: [...runOf].filter(([mid]) => !settled.has(mid)),
    noReturn: job.missing.map((mid) => [mid, runOf.get(mid)]),
  }
}
