import { useEffect, useState } from 'react'

/** "just now", "20s ago", "4m ago", "2h ago", "3d ago", then a date. */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return 'never'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return 'unknown'
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(then).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

/**
 * Both ends of a span for "between 3h and 20m ago": the first loses its "ago" when both have one.
 * null when they'd read the same ("2h ago" and "2h ago").
 */
export function relativeRange(from: string, to: string, now: number = Date.now()): [string, string] | null {
  const start = formatRelative(from, now)
  const end = formatRelative(to, now)
  if (start === end) return null
  return [start.endsWith(' ago') && end.endsWith(' ago') ? start.slice(0, -' ago'.length) : start, end]
}

/** "Oct 3", with the year when it isn't this one. */
export function formatDay(iso: string, now: number = Date.now()): string {
  const date = new Date(iso)
  const year = date.getFullYear() === new Date(now).getFullYear() ? undefined : 'numeric'
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year })
}

/** Local time with UTC alongside, for tooltips. */
export function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return 'Never'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return 'Unknown'
  const local = date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' })
  const utc = date.toISOString().replace('T', ' ').slice(0, 19)
  return `${local} (${utc} UTC)`
}

/** Re-render every `intervalMs` so relative times keep ticking. */
export function useNow(intervalMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

/** "45s", "12m", "3h 20m", "2d 4h". */
export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return minutes % 60 ? `${hours}h ${minutes % 60}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  return hours % 24 ? `${days}d ${hours % 24}h` : `${days}d`
}
