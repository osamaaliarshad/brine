import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from 'vitest'
import { createLiveInvalidator } from '@/api/live'

describe('createLiveInvalidator', () => {
  let client: QueryClient
  let invalidate: MockInstance<QueryClient['invalidateQueries']>

  beforeEach(() => {
    vi.useFakeTimers()
    client = new QueryClient()
    invalidate = vi.spyOn(client, 'invalidateQueries')
  })
  afterEach(() => vi.useRealTimers())

  const keys = () => invalidate.mock.calls.map(([filters]) => (filters as { queryKey?: unknown })?.queryKey)

  it('coalesces bursts into one refetch per query', () => {
    const handle = createLiveInvalidator(client, 100)
    handle({ type: 'fleet' })
    handle({ type: 'fleet' })
    handle({ type: 'minion', id: 'rover-01' })
    handle({ type: 'job', jid: '1' })
    handle({ type: 'job', jid: '2' })
    expect(invalidate).not.toHaveBeenCalled()

    vi.advanceTimersByTime(100)
    expect(keys()).toEqual([['fleet'], ['keys'], ['issues'], ['inventory'], ['minion', 'rover-01'], ['jobs']])
  })

  it('status changes refresh the fleet too (stale/online depends on them)', () => {
    const handle = createLiveInvalidator(client, 100)
    handle({ type: 'status' })
    vi.advanceTimersByTime(100)
    expect(keys()).toEqual([['status'], ['fleet'], ['issues']])
  })

  it('reconnecting refreshes brine data, but never re-runs Salt work', () => {
    const handle = createLiveInvalidator(client, 100)
    handle({ type: 'hello' })
    expect(invalidate).not.toHaveBeenCalled() // the page just loaded
    handle({ type: 'hello' })
    expect(invalidate).toHaveBeenCalledTimes(1)
    const { predicate } = invalidate.mock.calls[0]![0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }
    expect(predicate({ queryKey: ['fleet'] })).toBe(true)
    expect(predicate({ queryKey: ['minion-live', 'm1', 'pillar'] })).toBe(false)
    expect(predicate({ queryKey: ['states', 'top'] })).toBe(false)
    handle({ type: 'resync' })
    expect(invalidate).toHaveBeenCalledTimes(2)
  })
})
