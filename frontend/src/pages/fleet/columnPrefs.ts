/**
 * Per-browser column choices for the Fleet table.
 *
 * `grains: null` means "use the team default" (fleet.columns in the server config), so a
 * changed default reaches everyone who hasn't customised their view.
 */
export type ColumnPrefs = {
  grains: string[] | null
  /** Built-in columns switched off, e.g. "os". */
  hidden: string[]
}

const KEY = 'brine-fleet-columns'

export const DEFAULT_PREFS: ColumnPrefs = { grains: null, hidden: [] }

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string')
}

export function loadPrefs(): ColumnPrefs {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<ColumnPrefs> | null
    return {
      grains: isStringArray(saved?.grains) ? saved.grains : null,
      hidden: isStringArray(saved?.hidden) ? saved.hidden : [],
    }
  } catch {
    return DEFAULT_PREFS
  }
}

export function savePrefs(prefs: ColumnPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    // storage unavailable: the choice lasts for this page load only
  }
}

export function addGrain(current: string[], grain: string): string[] {
  const g = grain.trim()
  return !g || current.includes(g) ? current : [...current, g]
}

export function moveGrain(current: string[], grain: string, delta: -1 | 1): string[] {
  const i = current.indexOf(grain)
  const j = i + delta
  if (i < 0 || j < 0 || j >= current.length) return current
  const next = [...current]
  ;[next[i], next[j]] = [next[j]!, next[i]!]
  return next
}
