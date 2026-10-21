import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/setup'
import { ago, DEFAULT_COLUMNS, fleet, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const FLEET = fleet([
  minion('rover-01', { ip: '10.0.0.11' }),
  minion('rover-02', {
    status: 'offline',
    connected: false,
    last_seen_at: ago(2 * 3600),
    columns: { site: 'site-b', app_version: '2.3.0' },
  }),
  minion('dock-01', { grains_source: 'master_cache', grains_at: null, columns: { site: 'site-b' } }),
])

function rows() {
  return screen
    .getAllByRole('row')
    .slice(1) // header
    .map((row) => within(row).getAllByRole('cell')[0]!.textContent)
}

describe('FleetPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => {
    vi.useRealTimers()
    // @ts-expect-error -- jsdom doesn't define it; remove the phone stub if a test added one.
    delete window.matchMedia
  })

  it('shows summary cards, freshness, and every minion', async () => {
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')

    await screen.findByText('rover-01')
    expect(screen.getByText('Total minions').previousSibling).toHaveTextContent('3')
    expect(screen.getByText('Presence checked 20s ago')).toBeInTheDocument()
    expect(screen.getByText('4m ago')).toBeInTheDocument() // grains updated
    expect(rows()).toEqual(['dock-0110.0.0.1', 'rover-0110.0.0.11', 'rover-0210.0.0.1'])
  })

  it('marks offline and cache-sourced rows as cached', async () => {
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')

    const offline = (await screen.findByText('rover-02')).closest('tr')!
    expect(within(offline).getByText('Last seen 2h ago')).toBeInTheDocument()
    expect(within(offline).getByText('Cached')).toBeInTheDocument()

    const cachedGrains = screen.getByText('dock-01').closest('tr')!
    expect(within(cachedGrains).getByText('Online')).toBeInTheDocument()
    expect(within(cachedGrains).getByText('Cached')).toBeInTheDocument()

    const live = screen.getByText('rover-01').closest('tr')!
    expect(within(live).queryByText('Cached')).toBeNull()
  })

  it('filters by status tab, search, and site', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    const { router } = renderApp('/')
    await screen.findByText('rover-01')

    await user.click(screen.getByRole('tab', { name: /Offline/ }))
    expect(rows()).toEqual(['rover-0210.0.0.1'])
    expect(router.state.location.search).toBe('?status=offline')

    await user.click(screen.getByRole('tab', { name: /All minions/ }))
    await user.type(screen.getByRole('searchbox', { name: 'Search minions' }), '10.0.0.11')
    expect(rows()).toEqual(['rover-0110.0.0.11'])

    // Grain values are searchable too (there's no separate filter per grain).
    await user.clear(screen.getByRole('searchbox', { name: 'Search minions' }))
    await user.type(screen.getByRole('searchbox', { name: 'Search minions' }), 'site-b')
    expect(rows()).toEqual(['dock-0110.0.0.1', 'rover-0210.0.0.1'])
    expect(screen.getByText('Showing 1–2 of 2 minions')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('restores filters from the URL', async () => {
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/?q=rover&sort=id&dir=desc')
    await screen.findByText('rover-01')
    expect(rows()).toEqual(['rover-0210.0.0.1', 'rover-0110.0.0.11'])
  })

  it('sorts when a header is clicked, toggling direction', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    await screen.findByText('rover-01')

    await user.click(screen.getByRole('button', { name: /Connection/ }))
    expect(rows()[2]).toContain('rover-02') // offline last
    await user.click(screen.getByRole('button', { name: /Connection/ }))
    expect(rows()[0]).toContain('rover-02')
  })

  it('hides built-in columns and remembers the choice', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    await screen.findByText('rover-01')

    await user.click(screen.getByRole('button', { name: 'Columns' }))
    await user.click(screen.getByRole('checkbox', { name: 'OS / Salt' }))
    expect(screen.queryByRole('columnheader', { name: /OS \/ Salt/ })).toBeNull()
    expect(JSON.parse(localStorage.getItem('brine-fleet-columns')!)).toEqual({ grains: null, hidden: ['os'] })
  })

  it('lets you add, reorder, remove, and reset grain columns', async () => {
    const user = userEvent.setup()
    // The server answers with whatever columns were asked for.
    const api = mockApi({
      '/api/fleet': (url: URL) => {
        const asked = url.searchParams.getAll('column').filter(Boolean)
        if (!url.searchParams.has('column')) return FLEET
        return {
          ...FLEET,
          // Like the backend: configured grains keep their configured labels.
          columns: asked.map((g) => DEFAULT_COLUMNS.find((c) => c.grain === g) ?? { grain: g, label: g }),
          minions: FLEET.minions.map((m) => ({
            ...m,
            columns: Object.fromEntries(asked.map((g) => [g, g === 'osfinger' ? 'Debian-12' : m.columns[g] ?? null])),
          })),
        }
      },
      '/api/status': systemStatus(),
      '/api/grains/keys': [{ key: 'osfinger', minions: 3 }],
    })
    renderApp('/')
    await screen.findByText('rover-01')
    await user.click(screen.getByRole('button', { name: 'Columns' }))
    const menu = screen.getByRole('dialog', { name: 'Choose columns' })

    await user.type(within(menu).getByRole('combobox', { name: 'Grain to add' }), 'osfinger{Enter}')
    expect(await screen.findByRole('columnheader', { name: /osfinger/ })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/api/fleet?column=site&column=app_version&column=osfinger', expect.anything())

    await user.click(within(menu).getByRole('button', { name: 'Move osfinger left' }))
    await waitFor(() =>
      expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
        'Minion', 'Connection', 'OS / Salt', 'Site', 'osfinger', 'App version',
      ]),
    )

    await user.click(within(menu).getByRole('button', { name: 'Remove Site' }))
    await waitFor(() => expect(screen.queryByRole('columnheader', { name: /Site/ })).toBeNull())
    expect(JSON.parse(localStorage.getItem('brine-fleet-columns')!).grains).toEqual(['osfinger', 'app_version'])

    await user.click(within(menu).getByRole('button', { name: 'Reset to team default' }))
    expect(await screen.findByRole('columnheader', { name: /Site/ })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: /osfinger/ })).toBeNull()
  })

  it('shows package and check columns: the value, — when it is not there, ? when unknown', async () => {
    const user = userEvent.setup()
    const columns = [
      { grain: '@packages:rover-agent', label: 'rover-agent' },
      { grain: '@containers:web', label: 'web' },
    ]
    mockApi({
      '/api/fleet': fleet(
        [
          minion('rover-01', { columns: { '@packages:rover-agent': '2.4.1', '@containers:web': 'ghcr.io/acme/web:1.4' } }),
          minion('rover-02', { columns: { '@packages:rover-agent': null, '@containers:web': null } }),
          minion('rover-03', { columns: {} }), // no answer yet
        ],
        { columns },
      ),
      '/api/status': systemStatus(),
    })
    renderApp('/')
    await screen.findByText('rover-01')
    const cells = (id: string) => within(screen.getByText(id).closest('tr')!).getAllByRole('cell').slice(3)

    const [agent1, web1] = cells('rover-01')
    expect(agent1).toHaveTextContent('2.4.1')
    expect(web1).toHaveTextContent('ghcr.io/acme/web:1.4')
    const [agent2, web2] = cells('rover-02')
    expect(within(agent2!).getByText('—')).toHaveAttribute('title', 'Not installed')
    expect(within(web2!).getByText('—')).toHaveAttribute('title', 'Nothing reported')
    for (const cell of cells('rover-03'))
      expect(within(cell).getByText('?')).toHaveAttribute(
        'title',
        'No answer from this minion yet, or its last answer was cut short',
      )

    // Named in plain words, never by their @ keys.
    const header = screen.getByRole('columnheader', { name: /web/ })
    expect(within(header).getByRole('button')).toHaveAttribute('title', 'web, from the containers check')
    await user.click(screen.getByRole('button', { name: 'Columns' }))
    const menu = screen.getByRole('dialog', { name: 'Choose columns' })
    expect(within(menu).getByText('package')).toBeInTheDocument()
    expect(within(menu).getByText('check')).toBeInTheDocument()
    expect(within(menu).queryByText(/@packages|@containers/)).toBeNull()
    expect(within(menu).getByRole('link', { name: 'Grains & packages' })).toHaveAttribute('href', '/?tab=grains')
  })

  it('warns when brine has lost salt-api', async () => {
    mockApi({
      '/api/fleet': FLEET,
      '/api/status': systemStatus({ connected: false, since: ago(300), error: 'connection refused' }),
    })
    renderApp('/')
    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent("brine can't reach salt-api")
    expect(banner).toHaveTextContent('since 5m ago')
    expect(banner).toHaveTextContent('connection refused')
  })

  it('refetches when the live stream says the fleet changed', async () => {
    const api = mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    await screen.findByText('rover-01')
    const fleetCalls = () => api.mock.calls.filter(([url]) => url === '/api/fleet').length
    const before = fleetCalls()

    FakeEventSource.instances[0]!.emit({ type: 'fleet' })
    await waitFor(() => expect(fleetCalls()).toBe(before + 1))
  })

  it('shows cards instead of a table on phone-width screens', async () => {
    // jsdom has no matchMedia; pretend to be a phone for this test only.
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    const cards = await screen.findByRole('list', { name: 'Minions' })
    expect(screen.queryByRole('table')).toBeNull()
    const offline = within(cards).getByText('rover-02').closest('a')!
    expect(offline).toHaveAttribute('href', '/minions/rover-02')
    expect(within(offline).getByText('Last seen 2h ago')).toBeInTheDocument()
    expect(within(offline).getByText('site-b')).toBeInTheDocument()
  })

    it('shows an error with a retry button', async () => {
    mockApi({ '/api/status': systemStatus() }) // /api/fleet 404s
    renderApp('/')
    expect(await screen.findByText(/Couldn't load the fleet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('explains an empty fleet', async () => {
    mockApi({ '/api/fleet': fleet([]), '/api/status': systemStatus() })
    renderApp('/')
    expect(await screen.findByText(/No minions yet/)).toBeInTheDocument()
  })
})
