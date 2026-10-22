import { act, screen, within } from '@testing-library/react'
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
    caught_up: 0,
    catching_up: 0,
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

  it('counts minions that caught up later or are waiting to, apart from those missing', async () => {
    mockApi({
      '/api/jobs': {
        jobs: [
          job('1', { fun: 'test.version', returned: 3, caught_up: 1 }),
          job('2', { fun: 'test.ping', returned: 2, caught_up: 1, catching_up: 1 }),
          job('3', { fun: 'test.echo', returned: 2, catching_up: 1 }),
          job('4', { fun: 'test.true', returned: 0, succeeded: 0, catching_up: 4 }),
        ],
        next_before: null,
      },
      '/api/status': systemStatus(),
    })
    renderApp('/jobs')
    const outcome = (fun: string) => screen.getByRole('link', { name: fun }).closest('tr')!.lastElementChild
    await screen.findByRole('link', { name: 'test.version' })
    expect(outcome('test.version')).toHaveTextContent(/^3\/4· 1 caught up$/)
    expect(outcome('test.ping')).toHaveTextContent(/^2\/4· 1 caught up· 1 waiting to catch up$/)
    expect(outcome('test.echo')).toHaveTextContent(/^2\/4· 1 waiting to catch up· 1 missing$/)
    expect(outcome('test.true')).toHaveTextContent(/^0\/4 returned· 4 waiting to catch up$/)
  })

  it('searches, filters by kind, and loads older pages', async () => {
    const user = userEvent.setup()
    const api = mockApi({
      '/api/jobs': (url: URL) =>
        url.searchParams.get('before')
          ? { jobs: [job('old', { fun: 'test.ping' })], next_before: null }
          : { jobs: [job('new')], next_before: 'new' },
      '/api/status': systemStatus(),
      '/api/settings': { retention: { jobs_days: 30, history_days: 90, audit_days: 365 } },
    })
    const { router } = renderApp('/jobs')
    await screen.findByRole('link', { name: 'state.apply' })

    await user.click(screen.getByRole('button', { name: 'Load older jobs' }))
    expect(await screen.findByRole('link', { name: 'test.ping' })).toBeInTheDocument()
    // How far back that can go.
    expect(await screen.findByText("Kept for 30 days (retention in brine's config).")).toBeInTheDocument()

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
  catch_up: [],
  catch_up_of: null,
  results: [
    {
      minion_id: 'rover-01', returned_at: ago(595), success: true, retcode: 0, data: {}, caught_up: null,
      states: [{ id: '/etc/motd', name: '/etc/motd', function: 'file.managed', sls: 'motd', result: true, changed: true, comment: 'File updated', duration_ms: 11.1 }],
    },
    {
      minion_id: 'rover-02', returned_at: ago(594), success: false, retcode: 2, data: {}, caught_up: null,
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

  it('waits for answers while the job is young, not saying anyone failed to return', async () => {
    const fresh: JobDetail = {
      ...DETAIL,
      started_at: ago(5),
      finished_at: null,
      returned: 1,
      succeeded: 1,
      failed: 0,
      missing: ['rover-02', 'rover-03'],
      results: DETAIL.results.slice(0, 1),
    }
    mockApi({ '/api/jobs/20261020120000000001': fresh, '/api/status': systemStatus() })
    renderApp('/jobs/20261020120000000001')
    // A screen reader hears the count; the names are on screen beside it.
    const waiting = await screen.findByRole('status')
    expect(waiting).toHaveTextContent(/^Waiting for 2 of 3 minions$/)
    expect(screen.getByText('rover-02, rover-03')).toBeInTheDocument()
    expect(screen.queryByText(/No return from/)).toBeNull()
  })

  it('names the first few minions it waits for, and counts the rest', async () => {
    const minions = Array.from({ length: 10 }, (_, i) => `rover-${String(i + 1).padStart(2, '0')}`)
    const fresh: JobDetail = { ...DETAIL, started_at: ago(5), finished_at: null, returned: 2, minions, missing: minions.slice(2) }
    mockApi({ '/api/jobs/20261020120000000001': fresh, '/api/status': systemStatus() })
    renderApp('/jobs/20261020120000000001')
    expect(await screen.findByRole('status')).toHaveTextContent(/^Waiting for 8 of 10 minions$/)
    expect(screen.getByText('rover-03, rover-04, rover-05, rover-06, rover-07 and 3 more')).toBeInTheDocument()
  })

  it('waits for the first answer before saying there are no results', async () => {
    const fresh: JobDetail = {
      ...DETAIL,
      started_at: ago(2),
      finished_at: null,
      returned: 0,
      succeeded: 0,
      failed: 0,
      missing: ['rover-01', 'rover-02', 'rover-03'],
      results: [],
    }
    mockApi({ '/api/jobs/20261020120000000001': fresh, '/api/status': systemStatus() })
    renderApp('/jobs/20261020120000000001')
    expect(await screen.findByRole('status')).toHaveTextContent(/^Waiting for 3 of 3 minions$/)
    expect(screen.queryByText('No results recorded yet.')).toBeNull()
  })

  describe('a minute on', () => {
    const settle = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))
    const open = async (startedAt: string) => {
      vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
      vi.setSystemTime(NOW)
      const fresh: JobDetail = { ...DETAIL, started_at: startedAt, finished_at: null, missing: ['rover-03'] }
      mockApi({ '/api/jobs/20261020120000000001': fresh, '/api/status': systemStatus() })
      renderApp('/jobs/20261020120000000001')
      await settle(50)
    }

    it('says who never answered once the job is a minute old', async () => {
      await open(ago(20))
      expect(screen.getByRole('status')).toHaveTextContent('Waiting for 1 of 3 minions')
      await settle(39_900) // just short of a minute since it started
      expect(screen.getByRole('status')).toBeInTheDocument()
      await settle(100)
      expect(screen.queryByRole('status')).toBeNull()
      expect(screen.getByText(/^No return from rover-03\./)).toBeInTheDocument()
    })

    it('waits no more than a minute from opening, even with this clock behind the master', async () => {
      await open(new Date(NOW + 5 * 60_000).toISOString()) // "started" 5 minutes from now
      expect(screen.getByRole('status')).toBeInTheDocument()
      await settle(60_000)
      expect(screen.queryByRole('status')).toBeNull()
      expect(screen.getByText(/^No return from rover-03\./)).toBeInTheDocument()
    })

    it('waits for a young job opened from another job, with its own clock', async () => {
      vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
      vi.setSystemTime(NOW)
      const job = (jid: string, startedAt: string): JobDetail => ({
        ...DETAIL,
        jid,
        started_at: startedAt,
        finished_at: null,
        returned: 0,
        results: [],
        missing: DETAIL.minions,
      })
      mockApi({
        '/api/jobs/1': job('1', ago(600)),
        // Starts two minutes after the first job's page was opened, and is opened 5 s later.
        '/api/jobs/2': job('2', new Date(NOW + 115_000).toISOString()),
        '/api/status': systemStatus(),
      })
      const { router } = renderApp('/jobs/1')
      await settle(50)
      expect(screen.getByText(/^No return from rover-01/)).toBeInTheDocument()

      await settle(120_000 - 50)
      await act(() => router.navigate('/jobs/2'))
      await settle(50)
      expect(screen.getByText('2', { selector: 'p' })).toBeInTheDocument() // the second job's ID
      expect(screen.getByRole('status')).toHaveTextContent('Waiting for 3 of 3 minions')
    })
  })

  it('says who never answered once the job is no longer young', async () => {
    const old: JobDetail = { ...DETAIL, started_at: ago(5 * 60), finished_at: null, results: [], returned: 0, missing: DETAIL.minions }
    mockApi({ '/api/jobs/20261020120000000001': old, '/api/status': systemStatus() })
    renderApp('/jobs/20261020120000000001')
    expect(
      await screen.findByText(
        'No return from rover-01, rover-02, rover-03. They may have been offline, or are still running it.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('No results recorded yet.')).toBeInTheDocument()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('shows plain returns as a tree', async () => {
    mockApi({
      '/api/jobs/9': { ...DETAIL, jid: '9', fun: 'grains.item', args: ['os'], missing: [], results: [
        { minion_id: 'rover-01', returned_at: ago(1), success: true, retcode: 0, data: { os: 'Debian' }, states: null, caught_up: null },
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
