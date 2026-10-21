import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from 'react'
import { useAskInventory } from '@/api/queries'

// As brine's sweep asks (backend app/inventory_sweep.py): this many minions every this often.
const BATCH = 200
const SWEEP_MS = 15_000
// And then a while for the answers to come in.
const ANSWER_MS = 60_000

/** How long a read of `n` minions should take, after which its note has done its job anyway. */
export function readTime(n: number): number {
  return Math.ceil(n / BATCH) * SWEEP_MS + ANSWER_MS
}

export type ReadNow = {
  ask: ReturnType<typeof useAskInventory>
  /** Read now for `minion` (null: every online one), watching `key`, whose last answer is `at`. */
  start: (minion: string | null, key: string, at: string | null) => void
  /**
   * What each watched thing (a source, a minion) last answered when Read now was clicked, or
   * when it was first shown after. A newer answer than that means the read is answered. Only
   * brine's own times are compared, never the browser's clock.
   */
  seen: Record<string, string | null>
  setSeen: Dispatch<SetStateAction<Record<string, string | null>>>
  /**
   * An answer came in since the click, or the read has had time to: the note about it has
   * done its job, everywhere.
   */
  answered: boolean
  setAnswered: Dispatch<SetStateAction<boolean>>
}

/** Read now for packages and checks, and what the answers looked like when it was clicked. */
export function useReadNow(): ReadNow {
  const ask = useAskInventory()
  const [seen, setSeen] = useState<Record<string, string | null>>({})
  const [answered, setAnswered] = useState(false)
  // When Read now was clicked, by the browser's own clock: only time passed here is measured.
  const clicked = useRef(0)
  const result = ask.data
  useEffect(() => {
    if (!result) return
    const left = readTime(result.asked.length) - (performance.now() - clicked.current)
    const timer = setTimeout(() => setAnswered(true), Math.max(0, left))
    return () => clearTimeout(timer)
  }, [result])
  const start = (minion: string | null, key: string, at: string | null) => {
    clicked.current = performance.now()
    setSeen({ [key]: at })
    setAnswered(false)
    ask.mutate(minion)
  }
  return { ask, start, seen, setSeen, answered, setAnswered }
}
