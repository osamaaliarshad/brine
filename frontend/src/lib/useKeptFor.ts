import { useSettings } from '@/api/queries'
import type { Settings } from '@/api/types'

/**
 * How long brine keeps one kind of history, as a sentence for under a list of it: "Kept for 90
 * days (retention in brine's config)." null until the settings are in.
 */
export function useKeptFor(kind: keyof Settings['retention']): string | null {
  const days = useSettings().data?.retention[kind]
  if (days === undefined) return null
  const kept = days ? `Kept for ${days} day${days === 1 ? '' : 's'}` : 'Kept forever'
  return `${kept} (retention in brine's config).`
}
