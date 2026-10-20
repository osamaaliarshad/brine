import { CircleCheck, CircleDashed, CircleX } from 'lucide-react'
import type { JobSummary, StateDot, StateResult } from '@/api/types'
import { Pill } from '@/components/ui'
import { cn } from '@/lib/cn'

export function Target({ job }: { job: Pick<JobSummary, 'kind' | 'target' | 'target_type'> }) {
  if (job.kind === 'runner') return <span className="text-muted">master</span>
  if (!job.target) return <span className="text-muted">—</span>
  return (
    <span className="inline-flex items-center gap-1.5">
      <Pill title={job.target}>{job.target}</Pill>
      {job.target_type && job.target_type !== 'glob' && (
        <span className="text-xs text-muted">{job.target_type}</span>
      )}
    </span>
  )
}

/** "4/4 ✓", "3/4 · 1 failed", "0/2 waiting". */
export function JobOutcome({ job }: { job: JobSummary }) {
  const pending = job.expected > 0 ? job.expected - job.returned : 0
  if (job.failed > 0)
    return (
      <span className="inline-flex items-center gap-1.5 text-danger">
        <CircleX className="size-4" aria-hidden />
        {job.failed} failed
        {job.expected > 0 && <span className="text-muted">· {job.returned}/{job.expected}</span>}
      </span>
    )
  if (job.returned === 0)
    return (
      <span className="inline-flex items-center gap-1.5 text-muted">
        <CircleDashed className="size-4" aria-hidden />
        {job.expected > 0 ? `0/${job.expected} returned` : 'No return'}
      </span>
    )
  return (
    <span className={cn('inline-flex items-center gap-1.5', pending ? 'text-warn' : 'text-online')}>
      <CircleCheck className="size-4" aria-hidden />
      {job.expected > 0 ? `${job.returned}/${job.expected}` : 'Done'}
      {pending > 0 && <span className="text-muted">· {pending} missing</span>}
    </span>
  )
}

function dotClass(state: Pick<StateDot, 'result' | 'changed'>): string {
  if (state.result === false) return 'bg-danger'
  if (state.result === null) return 'bg-warn'
  return state.changed ? 'bg-online' : 'bg-online/35'
}

function dotLabel(state: Pick<StateDot, 'result' | 'changed'>): string {
  if (state.result === false) return 'failed'
  if (state.result === null) return 'would change (test)'
  return state.changed ? 'changed' : 'ok, no change'
}

/** One square per state, like SaltGUI's highstate view. Long runs show counts instead. */
export function StateDots({ states, max = 60 }: { states: StateDot[]; max?: number }) {
  if (states.length > max) return null
  return (
    <div className="flex max-w-md flex-wrap gap-1" role="list" aria-label="States">
      {states.map((s, i) => (
        <span
          key={`${s.id}-${i}`}
          role="listitem"
          title={`${s.function} ${s.id}: ${dotLabel(s)}`}
          aria-label={`${s.id}: ${dotLabel(s)}`}
          className={cn('size-3 rounded-[3px]', dotClass(s))}
        />
      ))}
    </div>
  )
}

export function StateLegend() {
  const items: [string, Pick<StateDot, 'result' | 'changed'>][] = [
    ['ok', { result: true, changed: false }],
    ['changed', { result: true, changed: true }],
    ['would change', { result: null, changed: false }],
    ['failed', { result: false, changed: false }],
  ]
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {items.map(([label, s]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <span className={cn('size-2.5 rounded-[3px]', dotClass(s))} aria-hidden />
          {label}
        </span>
      ))}
    </div>
  )
}

export function StateTable({ states }: { states: StateResult[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="text-left text-xs uppercase tracking-wider text-muted">
          <tr>
            <th className="w-8 py-2 pr-2 font-medium" aria-label="Result" />
            <th className="py-2 pr-4 font-medium">State</th>
            <th className="py-2 pr-4 font-medium">Comment</th>
            <th className="py-2 text-right font-medium">Time</th>
          </tr>
        </thead>
        <tbody>
          {states.map((s, i) => (
            <tr key={`${s.id}-${i}`} className="border-t align-top">
              <td className="py-2 pr-2">
                <span className={cn('mt-1 block size-3 rounded-[3px]', dotClass(s))} title={dotLabel(s)} />
              </td>
              <td className="py-2 pr-4">
                <div className="font-mono">{s.id}</div>
                <div className="text-xs text-muted">
                  {s.function}
                  {s.sls && ` · ${s.sls}`}
                  {s.changed && <span className="ml-1.5 rounded bg-online/15 px-1 text-online">changed</span>}
                </div>
              </td>
              <td className="py-2 pr-4 whitespace-pre-wrap text-muted">{s.comment || '—'}</td>
              <td className="py-2 text-right whitespace-nowrap text-muted tabular-nums">
                {s.duration_ms === null ? '—' : `${s.duration_ms < 1000 ? Math.round(s.duration_ms) + ' ms' : (s.duration_ms / 1000).toFixed(1) + ' s'}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
