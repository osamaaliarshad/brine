import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MinionDetail } from '@/api/types'
import { ago, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const DETAIL: MinionDetail = {
  ...minion('rover-01', { ip: '10.0.0.11' }),
  first_seen_at: ago(7 * 86400),
  grains: { os: 'Debian', app_version: '2.4.1', hw: { model: 'R2', serial: 'X1' }, ipv4: ['10.0.0.11'] },
  presence_history: [
    { at: ago(3600), connected: true },
    { at: ago(5400), connected: false },
  ],
  waiting_runs: [],
  recent_jobs: [
    { jid: '20261020110000000001', fun: 'state.apply', started_at: ago(600), returned_at: ago(590), success: true, retcode: 0 },
    { jid: '20261020100000000001', fun: 'cmd.run', started_at: ago(7200), returned_at: ago(7190), success: false, retcode: 1 },
  ],
}

function api(extra: Record<string, unknown> = {}) {
  return mockApi({ '/api/minions/rover-01': DETAIL, '/api/status': systemStatus(), ...extra })
}

describe('MinionPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('shows the header, facts, and grains by default', async () => {
    api()
    renderApp('/minions/rover-01')
    expect(await screen.findByText('10.0.0.11 · Debian 12 · Salt 3006.28')).toBeInTheDocument()
    expect(screen.getByText('Online since').nextSibling).toHaveTextContent('1h ago')
    expect(screen.getByText('As of 4m ago, from the minion')).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: 'app_version' })).toBeInTheDocument()
  })

  it('filters grains by name or value', async () => {
    const user = userEvent.setup()
    api()
    renderApp('/minions/rover-01')
    await user.type(await screen.findByRole('searchbox', { name: 'Filter grains' }), 'R2')
    expect(screen.getAllByRole('rowheader').map((r) => r.textContent)).toEqual(['hw'])
  })

  it('shows grains history as diffs', async () => {
    api({
      '/api/minions/rover-01/grains/history': [
        { collected_at: ago(60), added: { new: 1 }, removed: {}, changed: { app_version: { from: '2.4.0', to: '2.4.1' } } },
        { collected_at: ago(86400), added: { os: 'Debian', app_version: '2.4.0' }, removed: {}, changed: {} },
      ],
    })
    renderApp('/minions/rover-01?tab=history')
    expect(await screen.findByText('1 changed · 1 added')).toBeInTheDocument()
    expect(screen.getByText('"2.4.0"')).toHaveClass('line-through')
    expect(screen.getByText('First collection · 2 grains')).toBeInTheDocument()
  })

  it('lists recent jobs with results and links', async () => {
    api()
    renderApp('/minions/rover-01?tab=jobs')
    const link = await screen.findByRole('link', { name: 'state.apply' })
    expect(link).toHaveAttribute('href', '/jobs/20261020110000000001')
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(screen.getByText('Failed (1)')).toBeInTheDocument()
  })

  it('shows the presence timeline with durations', async () => {
    api()
    renderApp('/minions/rover-01?tab=timeline')
    const items = await screen.findAllByRole('listitem')
    expect(within(items[0]!).getByText('Came online')).toBeInTheDocument()
    expect(items[0]).toHaveTextContent('1h ago · for 1h so far')
    expect(items[1]).toHaveTextContent('Went offline')
    expect(items[1]).toHaveTextContent('lasted 30m')
  })

  it('fetches live views on demand and handles no answer', async () => {
    const user = userEvent.setup()
    const fetchMock = api({
      '/api/minions/rover-01/live/pillar': {
        kind: 'pillar', function: 'pillar.obfuscate', fetched_at: ago(1), answered: true,
        data: { app: { channel: '<str>' } },
      },
      '/api/minions/rover-01/live/beacons': {
        kind: 'beacons', function: 'beacons.list', fetched_at: ago(1), answered: false, data: null,
      },
    })
    renderApp('/minions/rover-01')
    await screen.findByText('10.0.0.11 · Debian 12 · Salt 3006.28')
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/live/'))).toBe(false)

    await user.click(screen.getByRole('tab', { name: 'Pillar' }))
    expect(await screen.findByText('<str>')).toBeInTheDocument()
    expect(screen.getByText(/masked/)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Beacons' }))
    expect(await screen.findByText(/didn't answer within 10 seconds/)).toBeInTheDocument()
  })

  it('says when a live view was skipped because the minion is offline', async () => {
    api({
      '/api/minions/rover-01/live/mine': {
        kind: 'mine', function: 'mine.valid', fetched_at: ago(1), answered: false, offline: true, data: null,
      },
    })
    renderApp('/minions/rover-01?tab=mine')
    expect(await screen.findByText(/is offline, so brine didn't ask it/)).toBeInTheDocument()
  })

  it('explains an unknown minion', async () => {
    mockApi({ '/api/status': systemStatus() })
    renderApp('/minions/ghost')
    expect(await screen.findByText(/doesn't know a minion called/)).toBeInTheDocument()
  })
})
