/**
 * Explorer and column keys: a grain path (`app_version`, `os:family`), or `@source:name` for a
 * package or a check's entry (`@packages:rover-agent`, `@containers:web`), or `@source` for a
 * check that prints a single value (`@rover-cli`). Grain paths never start with `@`.
 */

export type KeyKind = 'grain' | 'package' | 'check'

/** `{source, name}` from a package's or check's key (name "" for a single value); null for a grain. */
export function parseInventoryKey(key: string): { source: string; name: string } | null {
  if (!key.startsWith('@')) return null
  // Source names have no colon, so the first one ends it (package names may have more).
  const rest = key.slice(1)
  const i = rest.indexOf(':')
  const source = i < 0 ? rest : rest.slice(0, i)
  return source ? { source, name: i < 0 ? '' : rest.slice(i + 1) } : null
}

export function isInventoryKey(key: string): boolean {
  return parseInventoryKey(key) !== null
}

/** What to call it: the package's or entry's name, a single-value check's name, or the grain path. */
export function keyLabel(key: string): string {
  const parsed = parseInventoryKey(key)
  return parsed ? parsed.name || parsed.source : key
}

export function keyKind(key: string): KeyKind {
  const parsed = parseInventoryKey(key)
  if (!parsed) return 'grain'
  return parsed.source === 'packages' ? 'package' : 'check'
}

/** A minion that answered without it: a package isn't installed; a check didn't print it. */
export function missingLabel(key: string): string {
  return keyKind(key) === 'package' ? 'Not installed' : 'Nothing reported'
}

/** A source in a sentence: "brine can't read packages", "… the containers check". */
export function describeSource(source: string): string {
  return source === 'packages' ? 'packages' : `the ${source} check`
}

/** A short sentence for tooltips: which package, check or grain it is. */
export function keyDescription(key: string): string {
  const parsed = parseInventoryKey(key)
  if (!parsed) return `The ${key} grain`
  if (parsed.source === 'packages') return `The ${parsed.name} package`
  return parsed.name ? `${parsed.name}, from the ${parsed.source} check` : `The ${parsed.source} check`
}
