import type { MinionSummary } from '@/api/types'
import { parseInventoryKey } from '@/lib/inventoryKey'
import { formatAsOf } from '@/lib/time'

/** How fresh a minion's grains (and what comes from them) are, for a hover; null if unknown. */
export function grainsAsOf(minion: Pick<MinionSummary, 'grains_at' | 'grains_source'>, now: number): string | null {
  if (minion.grains_source === 'master_cache') return "From the master's cache; age unknown"
  return formatAsOf(minion.grains_at, now)
}

/** How fresh a column's value is: the grains', or the last read of a package's or check's source. */
export function cellAsOf(minion: MinionSummary, key: string, now: number): string | null {
  const parsed = parseInventoryKey(key)
  return parsed ? formatAsOf(minion.read_at[parsed.source], now) : grainsAsOf(minion, now)
}
