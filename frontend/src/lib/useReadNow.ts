import { type Dispatch, type SetStateAction, useState } from 'react'
import { useAskInventory } from '@/api/queries'

export type ReadNow = {
  ask: ReturnType<typeof useAskInventory>
  /**
   * What each watched thing (a source, a minion) last answered when Read now was clicked, or
   * when it was first shown after. A newer answer than that means the read is answered. Only
   * brine's own times are compared, never the browser's clock.
   */
  seen: Record<string, string | null>
  setSeen: Dispatch<SetStateAction<Record<string, string | null>>>
  /** An answer came in since the click, so the note about it has done its job, everywhere. */
  answered: boolean
  setAnswered: Dispatch<SetStateAction<boolean>>
}

/** Read now for packages and checks, and what the answers looked like when it was clicked. */
export function useReadNow(): ReadNow {
  const ask = useAskInventory()
  const [seen, setSeen] = useState<Record<string, string | null>>({})
  const [answered, setAnswered] = useState(false)
  return { ask, seen, setSeen, answered, setAnswered }
}
