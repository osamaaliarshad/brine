import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from 'vitest'
import { createLiveInvalidator } from '@/api/live'
import { MARK_ISSUES } from '@/api/queries'

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

  it("the fleet compared with a minion is redone only when that minion's packages or checks move", () => {
    const handle = createLiveInvalidator(client, 100)
    // Heavy: not on fleet updates, nor on every job or grains refresh on the minion.
    handle({ type: 'fleet' })
    handle({ type: 'minion', id: 'rover-03' })
    vi.advanceTimersByTime(100)
    expect(keys()).not.toContainEqual(expect.arrayContaining(['inventory-compare']))

    invalidate.mockClear()
    handle({ type: 'inventory', id: 'rover-03' })
    vi.advanceTimersByTime(100)
    expect(keys()).toEqual([['inventory-compare', 'rover-03']])
  })

  it('status changes refresh the fleet too (stale/online depends on them)', () => {
    const handle = createLiveInvalidator(client, 100)
    handle({ type: 'status' })
    vi.advanceTimersByTime(100)
    expect(keys()).toEqual([['status'], ['fleet'], ['issues']])
  })

  it('holds off refreshing issues while a mark is on its way (it refreshes them when done)', () => {
    const handle = createLiveInvalidator(client, 100)
    const mark = client.getMutationCache().build(client, { mutationKey: MARK_ISSUES, mutationFn: () => new Promise(() => {}) })
    void mark.execute(undefined)
    handle({ type: 'fleet' })
    vi.advanceTimersByTime(100)
    expect(keys()).toEqual([['fleet'], ['keys'], ['inventory']])

    handle({ type: 'resync' })
    const { predicate } = invalidate.mock.calls.at(-1)![0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }
    expect(predicate({ queryKey: ['issues'] })).toBe(false)
    expect(predicate({ queryKey: ['fleet'] })).toBe(true)
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
