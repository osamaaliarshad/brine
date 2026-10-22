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
  /** Waiting to catch up, with the run that may still bring the answer. */
  catchingUp: [string, CatchUpRun][]
  /** No return, and none to come from a catch-up run; with the run that came to nothing, if any. */
  noReturn: [string, CatchUpRun | undefined][]
}

/** A job's minions without a result: those waiting to catch up, and those missing. */
export function splitMissing(job: JobDetail): Missing {
  const answered = new Set(job.results.map((r) => r.minion_id))
  const runOf = new Map(job.catch_up.map((run) => [run.minion_id, run]))
  return {
    catchingUp: job.catch_up
      .filter((run) => run.state in STILL_CATCHING_UP && !answered.has(run.minion_id))
      .map((run) => [run.minion_id, run]),
    noReturn: job.missing.map((mid) => [mid, runOf.get(mid)]),
  }
}
