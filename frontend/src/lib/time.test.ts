import { describe, expect, it } from 'vitest'
import { formatAbsolute, formatRelative } from '@/lib/time'

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

describe('formatAbsolute', () => {
  it('shows UTC alongside local time', () => {
    expect(formatAbsolute('2026-10-20T12:00:00Z')).toContain('2026-10-20 12:00:00 UTC')
    expect(formatAbsolute(null)).toBe('Never')
  })
})
