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

/** A run that may still bring the minion's answer, and how it's getting on. */
export const STILL_CATCHING_UP: Partial<Record<CatchUpRun['state'], string>> = {
  waiting: "runs when it's back",
  sending: 'sending now',
  sent: 'sent, no answer yet',
}

export type Missing = {
  /** May still catch up, with the run that will. */
  catchingUp: [string, CatchUpRun][]
  /** No return, and none to come from a catch-up run; with the run that came to nothing, if any. */
  noReturn: [string, CatchUpRun | undefined][]
}

/** A job's missing minions: those still catching up, and the rest. */
export function splitMissing(job: JobDetail): Missing {
  const runOf = new Map(job.catch_up.map((run) => [run.minion_id, run]))
  const missing: Missing = { catchingUp: [], noReturn: [] }
  for (const mid of job.missing) {
    const run = runOf.get(mid)
    if (run && run.state in STILL_CATCHING_UP) missing.catchingUp.push([mid, run])
    else missing.noReturn.push([mid, run])
  }
  return missing
}
