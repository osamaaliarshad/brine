import { RefreshCw } from 'lucide-react'
import { type ReactNode, useEffect } from 'react'
import { ApiError } from '@/api/client'
import type { AskResult } from '@/api/types'
import { cn } from '@/lib/cn'
import { describeSource } from '@/lib/inventoryKey'
import type { ReadNow } from '@/lib/useReadNow'

function Asked({ result, minion }: { result: AskResult; minion: string | null }) {
  const n = result.asked.length
  const reason = result.reason ? `: ${result.reason}` : ''
  return (
    <div role="status" className="border-t bg-accent/10 px-4 py-2.5 text-sm sm:px-6">
      <p>
        {n === 0
          ? `${minion ? 'Not asked' : 'Nobody was asked'}${reason}.`
          : `Reading ${minion ?? `${n} minion${n === 1 ? '' : 's'}`}; answers appear as they arrive.`}
      </p>
      {Object.entries(result.failed).map(([source, why]) => (
        <p key={source} className="text-danger">
          Couldn't ask for {describeSource(source)}: {why}
        </p>
      ))}
    </div>
  )
}

/** A Read now button beside `children`, and below it what happened, until an answer arrives. */
export function ReadNowBar({
  read,
  minion,
  watch,
  title,
  className,
  children,
}: {
  read: ReadNow
  /** Read this minion, or null for every online one. */
  minion: string | null
  /** Where the answers show: a name for it (a source, a minion) and its latest answer's time. */
  watch: { key: string; at: string | null }
  /** The button's tooltip. */
  title: string
  className?: string
  children: ReactNode
}) {
  const { ask, seen, setSeen } = read
  const known = watch.key in seen
  useEffect(() => {
    // Shown after Read now was clicked elsewhere (another source): wait for its next answer.
    if (ask.data && !known) setSeen((prev) => (watch.key in prev ? prev : { ...prev, [watch.key]: watch.at }))
  }, [ask.data, known, setSeen, watch.key, watch.at])
  const answered = known && seen[watch.key] !== watch.at
  const tooSoon = ask.error instanceof ApiError && ask.error.status === 429
  return (
    <>
      <div className={cn('flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm sm:px-6', className)}>
        {children}
        <button
          type="button"
          onClick={() => {
            setSeen({ [watch.key]: watch.at })
            ask.mutate(minion)
          }}
          disabled={ask.isPending}
          title={title}
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 hover:bg-surface-2 disabled:opacity-50"
        >
          <RefreshCw className={cn('size-3.5', ask.isPending && 'animate-spin')} aria-hidden />
          Read now
        </button>
      </div>
      {ask.data && !answered && <Asked result={ask.data} minion={minion} />}
      {ask.error && (
        // Too soon is a wait, not a failure.
        <p
          role={tooSoon ? 'status' : 'alert'}
          className={cn('border-t px-4 py-2.5 text-sm sm:px-6', tooSoon ? 'text-muted' : 'text-danger')}
        >
          {ask.error.message}
        </p>
      )}
    </>
  )
}
