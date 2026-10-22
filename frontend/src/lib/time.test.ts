import { afterAll, describe, expect, it, vi } from 'vitest'
import { formatAbsolute, formatAsOf, formatRelative, relativeRange } from '@/lib/time'

// A fixed time zone, half an hour off from UTC, before the formatters are made: 12:00 UTC is
// 17:30 here, whatever the machine's own zone.
vi.hoisted(() => {
  vi.stubEnv('TZ', 'Asia/Kolkata')
})
afterAll(() => {
  vi.unstubAllEnvs()
})

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

// The pieces are checked, not the whole string, so this holds in any locale; the hour as a 12-
// or 24-hour clock writes it.
describe('formatAbsolute', () => {
  it('shows the local date and time only, to the second', () => {
    const text = formatAbsolute('2026-10-20T12:00:00Z')
    expect(text).toMatch(/\b(5|17):30:00\b/)
    expect(text).toContain('2026')
    expect(text).toMatch(/\b20\b/)
    expect(text).not.toMatch(/UTC|12:00/)
    expect(formatAbsolute(null)).toBe('Never')
    expect(formatAbsolute('not a date')).toBe('Unknown')
  })
})

describe('formatAsOf', () => {
  it('says how old a value is, then when that was, to the minute', () => {
    const text = formatAsOf(ago(10 * 60), NOW)!
    expect(text).toMatch(/^As of 10m ago · /)
    expect(text).toMatch(/\b(5|17):20\b/)
    expect(text).not.toContain(':20:00')
    expect(text).toContain('2026')
    expect(formatAsOf(ago(2), NOW)).toMatch(/^As of just now · .*\b(5|17):29\b/)
  })

  it('gives just the date and time once it is a month old', () => {
    const text = formatAsOf(ago(90 * 86400), NOW)!
    expect(text).toMatch(/^As of [^·]*\b(5|17):30\b/)
    expect(text).not.toContain('ago')
    expect(text).toMatch(/\b22\b/) // July 22nd
    // A day short of a month still counts back.
    expect(formatAsOf(ago(29 * 86400), NOW)).toMatch(/^As of 29d ago · /)
  })

  it('is null when there is no time to go by', () => {
    expect(formatAsOf(null, NOW)).toBeNull()
    expect(formatAsOf('not a date', NOW)).toBeNull()
  })
})
