import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobDetail, JobSummary, StateRuns } from '@/api/types'
import { formatArgs } from '@/pages/jobs/format'
import { ago, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

function job(jid: string, patch: Partial<JobSummary> = {}): JobSummary {
  return {
    jid,
    kind: 'local',
    fun: 'state.apply',
    target: '*',
    target_type: 'glob',
    user: 'root',
    started_at: ago(600),
    finished_at: ago(590),
    expected: 4,
    returned: 4,
    succeeded: 4,
    failed: 0,
    ...patch,
  }
}

const STATE_RUNS: StateRuns = {
  runs: [
    {
      minion_id: 'rover-01', jid: '1', fun: 'state.apply', started_at: ago(600), returned_at: ago(590),
      success: true, total: 2, succeeded: 2, failed: 0, changed: 1,
      states: [
        { id: '/etc/motd', function: 'file.managed', result: true, changed: true },
        { id: 'curl', function: 'pkg.installed', result: true, changed: false },
      ],
    },
    {
      minion_id: 'dock-01', jid: '2', fun: 'state.apply', started_at: ago(600), returned_at: ago(590),
      success: false, total: 1, succeeded: 0, failed: 1, changed: 0,
      states: [{ id: 'calibrate', function: 'cmd.run', result: false, changed: false }],
    },
  ],
  never: ['rover-04'],
}

describe('JobsPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('lists jobs with target, user, and outcome', async () => {
    mockApi({
      '/api/jobs': {
        jobs: [
          job('1', { fun: 'cmd.run', target: 'rover-*', failed: 1, succeeded: 2, returned: 3 }),
          job('2', { kind: 'runner', fun: 'manage.up', target: null, expected: 0, returned: 1 }),
        ],
        next_before: null,
      },
      '/api/status': systemStatus(),
    })
    renderApp('/jobs')
    const row = (await screen.findByRole('link', { name: 'cmd.run' })).closest('tr')!
    expect(within(row).getByText('rover-*')).toBeInTheDocument()
    expect(within(row).getByText('1 failed')).toBeInTheDocument()
    const runner = screen.getByRole('link', { name: 'manage.up' }).closest('tr')!
    expect(within(runner).getByText('master')).toBeInTheDocument()
    expect(within(runner).getByText('Done')).toBeInTheDocument()
  })

  it('searches, filters by kind, and loads older pages', async () => {
    const user = userEvent.setup()
    const api = mockApi({
      '/api/jobs': (url: URL) =>
        url.searchParams.get('before')
          ? { jobs: [job('old', { fun: 'test.ping' })], next_before: null }
          : { jobs: [job('new')], next_before: 'new' },
      '/api/status': systemStatus(),
    })
    const { router } = renderApp('/jobs')
    await screen.findByRole('link', { name: 'state.apply' })

    await user.click(screen.getByRole('button', { name: 'Load older jobs' }))
    expect(await screen.findByRole('link', { name: 'test.ping' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Runners' }))
    await user.type(screen.getByRole('searchbox', { name: 'Search jobs' }), 'ping')
    expect(router.state.location.search).toContain('kind=runner')
    const urls = api.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('kind=runner') && u.includes('q=ping'))).toBe(true)
  })

  it('shows each minion’s latest state run as dots', async () => {
    mockApi({ '/api/jobs/state-runs': STATE_RUNS, '/api/status': systemStatus() })
    renderApp('/jobs?tab=states')
    const dock = (await screen.findByRole('link', { name: 'dock-01' })).closest('tr')!
    expect(within(dock).getByText('1 failed')).toBeInTheDocument()
    expect(within(dock).getByRole('listitem', { name: 'calibrate: failed' })).toBeInTheDocument()
    const rover = screen.getByRole('link', { name: 'rover-01' }).closest('tr')!
    expect(within(rover).getByText('2/2 ok')).toBeInTheDocument()
    expect(screen.getByText(/No state run recorded for: rover-04/)).toBeInTheDocument()
  })
})

const DETAIL: JobDetail = {
  ...job('20261020120000000001', { failed: 1, succeeded: 1, returned: 2, expected: 3 }),
  args: ['motd', { __kwarg__: true, test: true }],
  minions: ['rover-01', 'rover-02', 'rover-03'],
  missing: ['rover-03'],
  results: [
    {
      minion_id: 'rover-01', returned_at: ago(595), success: true, retcode: 0, data: {},
      states: [{ id: '/etc/motd', name: '/etc/motd', function: 'file.managed', sls: 'motd', result: true, changed: true, comment: 'File updated', duration_ms: 11.1 }],
    },
    {
      minion_id: 'rover-02', returned_at: ago(594), success: false, retcode: 2, data: {},
      states: [{ id: 'calibrate', name: 'calibrate', function: 'cmd.run', sls: 'dock', result: false, changed: false, comment: 'Command failed', duration_ms: 1500 }],
    },
  ],
}

describe('JobPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('shows the command, facts, missing minions, and state results', async () => {
    mockApi({ '/api/jobs/20261020120000000001': DETAIL, '/api/status': systemStatus() })
    renderApp('/jobs/20261020120000000001')
    expect(await screen.findByRole('heading', { name: 'state.apply motd test=true' })).toBeInTheDocument()
    expect(screen.getByText('Took').nextSibling).toHaveTextContent('10s')
    expect(screen.getByText(/No return from rover-03/)).toBeInTheDocument()
    expect(screen.getByText('File updated')).toBeInTheDocument()
    expect(screen.getByText('Command failed')).toBeInTheDocument()
    expect(screen.getByText('1.5 s')).toBeInTheDocument()
  })

  it('shows plain returns as a tree', async () => {
    mockApi({
      '/api/jobs/9': { ...DETAIL, jid: '9', fun: 'grains.item', args: ['os'], missing: [], results: [
        { minion_id: 'rover-01', returned_at: ago(1), success: true, retcode: 0, data: { os: 'Debian' }, states: null },
      ] },
      '/api/status': systemStatus(),
    })
    renderApp('/jobs/9')
    expect(await screen.findByText('Debian')).toBeInTheDocument()
  })

  it('explains a job brine never saw', async () => {
    mockApi({ '/api/status': systemStatus() })
    renderApp('/jobs/nope')
    expect(await screen.findByText(/brine has no job nope/)).toBeInTheDocument()
  })
})

describe('formatArgs', () => {
  it('renders like the salt CLI', () => {
    expect(formatArgs(['curl', { __kwarg__: true, refresh: true, version: '8.0' }])).toBe(
      'curl refresh=true version=8.0',
    )
    expect(formatArgs([1, ['a']])).toBe('1 ["a"]')
  })
})
