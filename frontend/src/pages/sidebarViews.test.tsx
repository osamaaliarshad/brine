import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { beaconRows, describeWhen, scheduleRows } from '@/pages/automation/schedule'
import { slsToPath } from '@/pages/states/sls'
import { fleet, minion, mockApi, renderApp, systemStatus } from '@/test/render'

const FLEET = fleet([minion('rover-01'), minion('rover-02'), minion('dock-01', { status: 'offline' })])

describe('schedule and beacon parsing', () => {
  it.each([
    [{ minutes: 30 }, 'every 30 minutes'],
    [{ hours: 1, minutes: 15 }, 'every 15 minutes 1 hour'],
    [{ seconds: 1 }, 'every 1 second'],
    [{ cron: '0 3 * * *' }, 'cron 0 3 * * *'],
    [{ when: ['Monday 5pm', 'Friday 5pm'] }, 'at Monday 5pm, Friday 5pm'],
    [{}, '—'],
  ])('%j -> %s', (job, expected) => {
    expect(describeWhen(job)).toBe(expected)
  })

  it('flattens schedules, honouring a disabled scheduler', () => {
    const rows = scheduleRows({
      'rover-01': { refresh: { function: 'saltutil.refresh_grains', minutes: 30, args: ['x'], kwargs: { y: 1 } } },
      'dock-01': { enabled: false, nightly: { function: 'state.apply', cron: '0 3 * * *' } },
    })
    expect(rows).toEqual([
      { minion: 'dock-01', name: 'nightly', fun: 'state.apply', args: '', when: 'cron 0 3 * * *', enabled: false },
      { minion: 'rover-01', name: 'refresh', fun: 'saltutil.refresh_grains', args: 'x y=1', when: 'every 30 minutes', enabled: true },
    ])
  })

  it('merges beacon config lists', () => {
    const rows = beaconRows({
      'rover-01': { load: [{ averages: { '1m': [0, 2] } }, { interval: 60 }], enabled: true },
      'dock-01': { diskusage: [{ '/': '90%' }, { enabled: false }] },
    })
    expect(rows).toEqual([
      { minion: 'dock-01', name: 'diskusage', config: '/=90%', enabled: false },
      { minion: 'rover-01', name: 'load', config: 'averages={"1m":[0,2]} interval=60', enabled: true },
    ])
  })
})

describe('slsToPath', () => {
  const files = [{ root: '/srv/salt', path: 'motd.sls' }, { root: '/srv/salt', path: 'web/nginx/init.sls' }]
  it('resolves like Salt', () => {
    expect(slsToPath('motd', files)).toBe('motd.sls')
    expect(slsToPath('web.nginx', files)).toBe('web/nginx/init.sls')
    expect(slsToPath('nope', files)).toBeNull()
  })
})

describe('Fleet › Grains', () => {
  it('shows how a grain is spread and adds it as a column', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/fleet': FLEET,
      '/api/status': systemStatus(),
      '/api/grains/keys': [{ key: 'app_version', minions: 3 }, { key: 'osfinger', minions: 3 }],
      '/api/grains/values': (url: URL) =>
        url.searchParams.get('grain') === 'osfinger'
          ? { grain: 'osfinger', total: 3, values: [{ value: 'Debian-12', text: 'Debian-12', minions: ['dock-01', 'rover-01', 'rover-02'] }], missing: [] }
          : { grain: 'app_version', total: 3, values: [{ value: '2.4.1', text: '2.4.1', minions: ['rover-01', 'rover-02'] }], missing: ['dock-01'] },
    })
    renderApp('/?tab=grains')
    // Starts on the first Fleet column.
    expect(await screen.findByRole('heading', { name: 'site' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /osfinger/ }))
    const values = await screen.findByRole('list', { name: 'Values of osfinger' })
    expect(within(values).getByText('Debian-12')).toBeInTheDocument()
    expect(within(values).getByText(/100%/)).toBeInTheDocument()

    await user.click(within(values).getByRole('button', { name: /Debian-12/ }))
    expect(within(values).getByRole('link', { name: 'dock-01' })).toHaveAttribute('href', '/minions/dock-01')

    await user.click(screen.getByRole('button', { name: 'Add as a Fleet column' }))
    expect(JSON.parse(localStorage.getItem('brine-fleet-columns')!).grains).toEqual(['site', 'app_version', 'osfinger'])
  })
})

describe('Fleet › Nodegroups', () => {
  it('lists groups with members and online counts', async () => {
    mockApi({
      '/api/fleet': FLEET,
      '/api/status': systemStatus(),
      '/api/nodegroups': {
        groups: [
          { name: 'rovers', expression: 'G@role:rover', members: ['rover-01', 'rover-02'] },
          { name: 'docks', expression: 'L@dock-01', members: ['dock-01'] },
        ],
        ungrouped: ['lonely'],
      },
    })
    renderApp('/?tab=nodegroups')
    expect(await screen.findByText('G@role:rover')).toBeInTheDocument()
    expect(screen.getByText('2 minions · 2 online')).toBeInTheDocument()
    expect(screen.getAllByText('1 minion · 0 online')).toHaveLength(2) // docks (offline) and the ungrouped bucket
    expect(screen.getByText('Not in any nodegroup')).toBeInTheDocument()
  })
})

describe('States page', () => {
  it('maps states to minions and opens their files', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/fleet': FLEET,
      '/api/status': systemStatus(),
      '/api/states/top': {
        fetched_at: '2026-10-20T12:00:00Z',
        minions: { 'rover-01': { base: ['motd'] }, 'dock-01': { base: ['motd', 'dock'] } },
        missing: ['rover-02'],
        skipped: ['rover-03'],
      },
      '/api/states/files': [{ root: '/srv/salt', path: 'dock.sls' }, { root: '/srv/salt', path: 'motd.sls' }, { root: '/srv/salt', path: 'top.sls' }],
      '/api/states/file': (url: URL) => ({
        path: url.searchParams.get('path'),
        full_path: `/srv/salt/${url.searchParams.get('path')}`,
        content: '/etc/motd:\n  file.managed',
        truncated: false,
      }),
    })
    renderApp('/states')
    const motd = (await screen.findByRole('link', { name: 'motd' })).closest('tr')!
    expect(within(motd).getAllByRole('link').map((l) => l.textContent)).toEqual(['motd', 'dock-01', 'rover-01'])
    expect(screen.getByText("Didn't answer: rover-02")).toBeInTheDocument()
    expect(screen.getByText('Offline, not asked: rover-03')).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'motd' }))
    expect(await screen.findByText('/srv/salt/motd.sls')).toBeInTheDocument()
    expect(screen.getByText('file.managed', { exact: false })).toBeInTheDocument()
  })

  it('groups states by folder, with who each group reaches', async () => {
    const user = userEvent.setup()
    const web = ['web.nginx', 'web.certs', 'web.logs', 'web.app', 'web.cache', 'web.cdn', 'web.waf', 'web.php']
    const common = ['common.users', 'common.ssh', 'common.ntp', 'common.motd', 'common.audit']
    mockApi({
      '/api/fleet': FLEET,
      '/api/status': systemStatus(),
      '/api/states/top': {
        fetched_at: '2026-10-20T12:00:00Z',
        minions: {
          'rover-01': { base: ['motd', ...common] },
          'dock-01': { base: ['motd', ...common, ...web] },
        },
        missing: [],
        skipped: [],
      },
      '/api/states/files': [],
    })
    renderApp('/states')
    // 14 states: groups start folded, as an overview.
    const group = await screen.findByRole('button', { name: /^web/ })
    expect(group).toHaveAttribute('aria-expanded', 'false')
    expect(group).toHaveTextContent('web8 states')
    expect(within(group.closest('tr')!).getAllByRole('link').map((l) => l.textContent)).toEqual(['dock-01'])
    expect(screen.getByText('motd')).toBeInTheDocument() // no folder: always shown
    expect(screen.queryByText('nginx')).toBeNull()

    await user.click(group)
    expect(screen.getByText('nginx')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getByText('ntp')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect(screen.queryByText('nginx')).toBeNull()
  })
})

describe('Automation page', () => {
  it('lists schedules across the fleet and who did not answer', async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/fleet': FLEET,
      '/api/status': systemStatus(),
      '/api/automation/schedules': {
        kind: 'schedules', function: 'schedule.list', fetched_at: '2026-10-20T12:00:00Z',
        results: { 'rover-01': { 'refresh-grains': { function: 'saltutil.refresh_grains', minutes: 30 } } },
        missing: ['dock-01'],
        skipped: [],
      },
      '/api/automation/beacons': {
        kind: 'beacons', function: 'beacons.list', fetched_at: '2026-10-20T12:00:00Z',
        results: { 'rover-01': { load: [{ interval: 60 }] } },
        missing: [],
        skipped: [],
      },
    })
    renderApp('/automation')
    expect(await screen.findByText('refresh-grains')).toBeInTheDocument()
    expect(screen.getByText('every 30 minutes')).toBeInTheDocument()
    expect(screen.getByText("Didn't answer: dock-01")).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Beacons' }))
    expect(await screen.findByText('interval=60')).toBeInTheDocument()
  })
})

describe('sidebar', () => {
  it('groups configuration pages', () => {
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0]!
    expect(within(nav).getByText('Configuration')).toBeInTheDocument()
    for (const name of ['States', 'Automation', 'Keys']) {
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
    }
  })
})
