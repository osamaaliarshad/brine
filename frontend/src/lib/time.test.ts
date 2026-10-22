import { describe, expect, it } from 'vitest'
import { formatAbsolute, formatAsOf, formatRelative, relativeRange } from '@/lib/time'

const NOW = Date.parse('2026-10-20T12:00:00Z')
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString()

describe('formatRelative', () => {
  it.each([
    [2, 'just now'],
    [20, '20s ago'],
    [4 * 60, '4m ago'],
    [2 * 3600, '2h ago'],
    [3 * 86400, '3d ago'],
  ])('%is ago -> %s', (seconds, expected) => {
    expect(formatRelative(ago(seconds), NOW)).toBe(expected)
  })

  it('handles missing and bad values', () => {
    expect(formatRelative(null, NOW)).toBe('never')
    expect(formatRelative('not a date', NOW)).toBe('unknown')
  })

  it('treats slight clock skew into the future as now', () => {
    expect(formatRelative(ago(-3), NOW)).toBe('just now')
  })

  it('switches to a date after a month', () => {
    expect(formatRelative(ago(90 * 86400), NOW)).toMatch(/2026/)
  })
})

describe('relativeRange', () => {
  it('reads as "between 3h and 20m ago"', () => {
    expect(relativeRange(ago(3 * 3600), ago(20 * 60), NOW)).toEqual(['3h', '20m ago'])
    expect(relativeRange(ago(3 * 3600), ago(1), NOW)).toEqual(['3h ago', 'just now'])
  })

  it('is null when both ends would read the same', () => {
    expect(relativeRange(ago(2 * 3600 + 600), ago(2 * 3600), NOW)).toBeNull()
  })
})

/** The local date and time, as this machine's locale writes it. */
const local = (iso: string, timeStyle: 'short' | 'medium') =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle })

describe('formatAbsolute', () => {
  it('shows the local date and time only', () => {
    const text = formatAbsolute('2026-10-20T12:00:00Z')
    expect(text).toBe(local('2026-10-20T12:00:00Z', 'medium'))
    expect(text).toContain('2026')
    expect(text).not.toContain('UTC')
    expect(formatAbsolute(null)).toBe('Never')
    expect(formatAbsolute('not a date')).toBe('Unknown')
  })
})

describe('formatAsOf', () => {
  it('says how old a value is, then when that was', () => {
    expect(formatAsOf(ago(10 * 60), NOW)).toBe(`As of 10m ago · ${local(ago(10 * 60), 'short')}`)
    expect(formatAsOf(ago(2), NOW)).toBe(`As of just now · ${local(ago(2), 'short')}`)
  })

  it('gives just the date and time once it is over a month old', () => {
    expect(formatAsOf(ago(90 * 86400), NOW)).toBe(`As of ${local(ago(90 * 86400), 'short')}`)
  })

  it('is null when there is no time to go by', () => {
    expect(formatAsOf(null, NOW)).toBeNull()
    expect(formatAsOf('not a date', NOW)).toBeNull()
  })
})
