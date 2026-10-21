import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { SaltEventEntry } from '@/api/types'
import { summarize } from '@/pages/events/eventModel'
import { FakeEventSource } from '@/test/setup'
import { mockApi, renderApp, systemStatus } from '@/test/render'

let seq = 0
const ev = (tag: string, data: Record<string, unknown> = {}): SaltEventEntry => ({
  seq: ++seq,
  received_at: '2026-10-20T12:00:00Z',
  tag,
  data,
})

function stream() {
  const source = FakeEventSource.instances.find((s) => s.url === '/api/events/stream')
  if (!source) throw new Error('no event stream opened')
  return source
}

async function emit(...events: SaltEventEntry[]) {
  await act(async () => {
    for (const e of events) stream().emit(e)
    await new Promise((r) => setTimeout(r, 150)) // the hook batches renders
  })
}

describe('summarize', () => {
  it.each([
    [ev('salt/job/1/new', { fun: 'test.ping', tgt: 'rover-*', minions: ['a', 'b'] }), 'test.ping → rover-* (2 minions)'],
    [ev('salt/job/1/ret/rover-01', { id: 'rover-01', fun: 'test.ping', success: true }), 'rover-01: test.ping ok'],
    [ev('salt/job/1/ret/dock-01', { id: 'dock-01', fun: 'state.apply', success: false }), 'dock-01: state.apply failed'],
    [ev('salt/run/1/new', { fun: 'runner.manage.up' }), 'runner.manage.up started'],
    [ev('salt/presence/present', { present: ['a', 'b', 'c'] }), '3 minions present'],
    [ev('salt/presence/change', { new: ['a'], lost: ['b'] }), '+a −b'],
    [ev('salt/auth', { id: 'rover-04', act: 'pend' }), 'rover-04 authenticating (pend)'],
    [ev('salt/minion/rover-01/start'), 'rover-01 started'],
    [ev('salt/beacon/rover-01/load/'), 'load beacon on rover-01'],
  ])('%#', (event, expected) => {
    expect(summarize(event)).toBe(expected)
  })
})

describe('EventsPage', () => {
  it('streams events newest first, hiding presence by default', async () => {
    mockApi({ '/api/status': systemStatus() })
    renderApp('/events')
    await emit(
      ev('salt/presence/present', { present: ['a'] }),
      ev('salt/job/9/new', { fun: 'test.ping', tgt: '*', minions: ['a'] }),
      ev('salt/job/9/ret/a', { id: 'a', fun: 'test.ping', success: true }),
    )
    const rows = within(screen.getByRole('list', { name: 'Events' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('salt/job/9/ret/a'),
      expect.stringContaining('salt/job/9/new'),
    ])
    await userEvent.click(screen.getByRole('checkbox', { name: 'Presence' }))
    expect(screen.getByText('1 minions present')).toBeInTheDocument()
  })

  it('pauses, counts what arrives, and resumes', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/status': systemStatus() })
    renderApp('/events')
    await user.click(screen.getByRole('button', { name: 'Pause' }))
    await emit(ev('salt/key', { id: 'x', act: 'accept' }))
    expect(screen.queryByText('salt/key')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Resume (1 new)' }))
    expect(screen.getByText('salt/key')).toBeInTheDocument()
  })

  it('drops duplicates re-sent after a reconnect, and filters', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/status': systemStatus() })
    renderApp('/events')
    const once = ev('salt/minion/rover-01/start')
    await emit(once, once, ev('salt/key', { id: 'x', act: 'delete' }))
    expect(screen.getByText('Showing 2 of 2 (last 500 kept)')).toBeInTheDocument()
    await user.type(screen.getByRole('searchbox', { name: 'Filter events' }), 'rover-01')
    expect(screen.getByText('Showing 1 of 2 (last 500 kept)')).toBeInTheDocument()
  })

  it('starts over when brine restarts and numbers events from 1 again', async () => {
    mockApi({ '/api/status': systemStatus() })
    renderApp('/events')
    act(() => stream().open())
    await emit(ev('salt/key', { id: 'old-1', act: 'pend' }), ev('salt/key', { id: 'old-2', act: 'pend' }))
    expect(screen.getByText('Showing 2 of 2 (last 500 kept)')).toBeInTheDocument()
    act(() => stream().open()) // brine came back with an empty backlog
    await emit({ ...ev('salt/key', { id: 'fresh', act: 'pend' }), seq: 1 })
    expect(screen.getByText('Showing 1 of 1 (last 500 kept)')).toBeInTheDocument()
    expect(screen.getByText(/fresh/)).toBeInTheDocument()
  })

  it('expands an event to show its data', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/status': systemStatus() })
    renderApp('/events')
    await emit(ev('salt/job/1/ret/a', { id: 'a', fun: 'grains.item', return: { os: 'Debian' } }))
    await user.click(screen.getByRole('button', { name: /salt\/job\/1\/ret\/a/ }))
    expect(screen.getByText('Debian')).toBeInTheDocument()
  })

  it('lists reactors', async () => {
    mockApi({
      '/api/status': systemStatus(),
      '/api/reactors': [{ tag: 'salt/minion/*/start', sls: ['/srv/reactor/minion-start.sls'] }],
    })
    renderApp('/events?tab=reactors')
    expect(await screen.findByText('salt/minion/*/start')).toBeInTheDocument()
    expect(screen.getByText('/srv/reactor/minion-start.sls')).toBeInTheDocument()
  })
})
