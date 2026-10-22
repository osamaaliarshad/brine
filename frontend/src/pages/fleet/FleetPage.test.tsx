import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest'
import type { InventoryKey } from '@/api/types'
import { keyLabel } from '@/lib/inventoryKey'
import { formatAsOf } from '@/lib/time'
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

// A package column and two check columns: a value, answered without it, no answer yet, empty.
// Each source was read at its own time.
const READ_AT = { packages: ago(3600), containers: ago(600), 'rover-cli': ago(600) }
const PACKAGE_FLEET = fleet(
  [
    minion('rover-01', {
      columns: { '@packages:rover-agent': '2.4.1', '@containers:web': 'ghcr.io/acme/web:1.4', '@rover-cli': '1.2.0' },
      read_at: READ_AT,
    }),
    minion('rover-02', {
      columns: { '@packages:rover-agent': null, '@containers:web': null, '@rover-cli': null },
      read_at: READ_AT,
    }),
    minion('rover-03', { columns: {}, read_at: { packages: null, containers: null, 'rover-cli': null } }),
    minion('rover-04', {
      columns: { '@packages:rover-agent': '2.4.1', '@containers:web': '', '@rover-cli': '' },
      read_at: READ_AT,
    }),
  ],
  {
    columns: [
      { grain: '@packages:rover-agent', label: 'rover-agent' },
      { grain: '@containers:web', label: 'web' },
      { grain: '@rover-cli', label: 'rover-cli' },
    ],
  },
)
/** The fleet as the server answers a request for columns: whatever was asked for, labelled like
 * the backend labels them (configured grains keep their configured labels). */
function withAskedColumns(url: URL) {
  const asked = url.searchParams.getAll('column').filter(Boolean)
  if (!url.searchParams.has('column')) return FLEET
  return {
    ...FLEET,
    columns: asked.map((g) => DEFAULT_COLUMNS.find((c) => c.grain === g) ?? { grain: g, label: keyLabel(g) }),
    minions: FLEET.minions.map((m) => ({
      ...m,
      columns: Object.fromEntries(asked.map((g) => [g, g === 'osfinger' ? 'Debian-12' : m.columns[g] ?? null])),
    })),
  }
}

const GRAIN_KEYS = [
  { key: 'osfinger', minions: 3 },
  { key: 'osrelease', minions: 3 },
  { key: 'hw:model', minions: 2 },
  { key: 'kernel', minions: 1 },
  { key: 'site', minions: 3 }, // already a column
]

const pkg = (name: string, minions: number): InventoryKey => ({
  key: `@packages:${name}`,
  source: 'packages',
  name,
  kind: 'package',
  minions,
})
const PACKAGES = [pkg('bash', 3), pkg('nginx', 2), pkg('nginx-common', 1), pkg('rover-agent', 2)]
const ROVER_CLI: InventoryKey = { key: '@rover-cli', source: 'rover-cli', name: '', kind: 'check', minions: 3 }

/** Like the server: no search gives the checks and the packages that differ; a search, any package
 * by its name, or a check by its own. */
function inventoryKeys(url: URL): InventoryKey[] {
  const q = url.searchParams.get('q')!.toLowerCase()
  if (!q) return [pkg('rover-agent', 2), ROVER_CLI]
  return [...PACKAGES, ROVER_CLI].filter((k) => k.name.includes(q) || (k.kind === 'check' && k.source.includes(q)))
}

/** The Fleet page with the Columns menu open, and its box for adding a column. */
async function openColumns(user: ReturnType<typeof userEvent.setup>, grainKeys: unknown = GRAIN_KEYS) {
  const api = mockApi({
    '/api/fleet': withAskedColumns,
    '/api/status': systemStatus(),
    '/api/grains/keys': grainKeys,
    '/api/inventory/keys': inventoryKeys,
  })
  renderApp('/')
  await screen.findByText('rover-01')
  await user.click(screen.getByRole('button', { name: 'Columns' }))
  const menu = screen.getByRole('dialog', { name: 'Choose columns' })
  const box = within(menu).getByRole('combobox', { name: 'Add a grain, package or check' })
  return { api, menu, box }
}

/** What a group of the list offers, as read out: "osfinger 3 minions". */
function offered(group: string): string[] {
  return within(screen.getByRole('group', { name: group }))
    .queryAllByRole('option')
    .map((o) => o.textContent!)
}

/** A minion's cell in the column with this heading. */
function cellOf(id: string, column: string): HTMLElement {
  const index = screen.getAllByRole('columnheader').findIndex((h) => h.textContent === column)
  expect(index, `no ${column} column`).toBeGreaterThanOrEqual(0)
  return within(screen.getByText(id).closest('tr')!).getAllByRole('cell')[index]!
}

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

  it("says how fresh each grain is on hover, and names what a minion doesn't report", async () => {
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    await screen.findByText('rover-01')
    const asOf = formatAsOf(ago(240), NOW)
    expect(within(cellOf('rover-01', 'Site')).getByText('site-a')).toHaveAttribute('title', `site-a\n${asOf}`)
    expect(within(cellOf('rover-01', 'App version')).getByText('2.4.1')).toHaveAttribute('title', `2.4.1\n${asOf}`)
    // OS and Salt come from grains too.
    expect(cellOf('rover-01', 'OS / Salt').firstElementChild).toHaveAttribute('title', asOf)
    // From the master's cache: when they were collected is unknown.
    expect(within(cellOf('dock-01', 'App version')).getByText('—')).toHaveAttribute(
      'title',
      "dock-01 doesn't report app_version\nFrom the master's cache; age unknown",
    )
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
    const { api, menu, box } = await openColumns(user)

    await user.type(box, 'osfinger{Enter}')
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

  it('offers grains, packages and checks in a list of its own, narrowed as you type', async () => {
    const user = userEvent.setup()
    const { menu, box } = await openColumns(user)
    expect(box).toHaveAttribute('aria-expanded', 'false')

    await user.click(box)
    const list = await screen.findByRole('listbox', { name: 'Add a grain, package or check' })
    expect(box).toHaveAttribute('aria-expanded', 'true')
    expect(box).toHaveAttribute('aria-controls', list.id)
    // What's already a column (site) isn't offered.
    expect(offered('Grains')).toEqual(['osfinger 3 minions', 'osrelease 3 minions', 'hw:model 2 minions', 'kernel 1 minion'])
    // Before a search: the checks, then the packages that differ across the fleet.
    await waitFor(() => expect(offered('Packages and checks')).toEqual(['rover-cli check 3 minions', 'rover-agent package 2 minions']))
    expect(within(list).getByText('Type 2 or more letters to find any package')).toBeInTheDocument()
    // The notes under the options are read out as they change.
    const status = within(menu).getByRole('status')
    expect(status).toHaveTextContent('Packages and checks: Type 2 or more letters to find any package')

    // Anywhere in the key, whatever the case.
    await user.type(box, 'MODEL')
    expect(offered('Grains')).toEqual(['hw:model 2 minions'])

    // Packages are searched once you pause.
    await user.clear(box)
    await user.type(box, 'nginx')
    expect(screen.queryByRole('group', { name: 'Grains' })).toBeNull()
    expect(within(screen.getByRole('group', { name: 'Packages and checks' })).getByText('Searching…')).toBeInTheDocument()
    expect(status).toHaveTextContent('Packages and checks: Searching…')
    await waitFor(() => expect(offered('Packages and checks')).toEqual(['nginx package 2 minions', 'nginx-common package 1 minion']))
    expect(screen.queryByText(/Searching…/)).toBeNull()
    expect(status).toHaveTextContent(/^$/)

    // Nothing matches: no list at all.
    await user.type(box, 'zzz')
    await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull())
    expect(box).toHaveAttribute('aria-expanded', 'false')
  })

  it('adds the highlighted option on Enter, in one step', async () => {
    const user = userEvent.setup()
    const { api, menu, box } = await openColumns(user)
    await user.click(box)
    await screen.findByRole('listbox')

    await user.keyboard('{ArrowDown}{ArrowDown}')
    const osrelease = screen.getByRole('option', { name: 'osrelease 3 minions' })
    expect(osrelease).toHaveAttribute('aria-selected', 'true')
    expect(box).toHaveAttribute('aria-activedescendant', osrelease.id)
    await user.keyboard('{ArrowUp}')
    expect(box).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: 'osfinger 3 minions' }).id)

    await user.keyboard('{Enter}')
    expect(await screen.findByRole('columnheader', { name: /osfinger/ })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/api/fleet?column=site&column=app_version&column=osfinger', expect.anything())
    expect(box).toHaveValue('')
    expect(box).toHaveAttribute('aria-expanded', 'false')
    expect(box).not.toHaveAttribute('aria-activedescendant')
    expect(menu).toBeInTheDocument()

    // Down opens the list again, on its first option; what was just added isn't offered.
    await user.keyboard('{ArrowDown}')
    expect(offered('Grains')).toEqual(['osrelease 3 minions', 'hw:model 2 minions', 'kernel 1 minion'])
    expect(screen.getByRole('option', { name: 'osrelease 3 minions' })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps the highlighted option scrolled into view', async () => {
    const user = userEvent.setup()
    const { box } = await openColumns(
      user,
      ['a', 'b', 'c', 'd', 'e', 'f'].map((g) => ({ key: `grain_${g}`, minions: 1 })),
    )
    // jsdom lays nothing out: options 30px tall, one under the other, in a list three high
    // (anything else at the top).
    const options = (el: Element) => [...(el.closest('[role="listbox"]')?.querySelectorAll('[role="option"]') ?? [])]
    const spies = [
      vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(function (this: HTMLElement) {
        return Math.max(options(this).indexOf(this), 0) * 30
      }),
      vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(30),
      vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(90),
    ]
    onTestFinished(() => spies.forEach((s) => s.mockRestore()))

    await user.click(box)
    const list = await screen.findByRole('listbox')
    // Six grains, then a check and a package.
    await waitFor(() => expect(offered('Packages and checks')).toHaveLength(2))
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
    expect(list.scrollTop).toBe(0)
    await user.keyboard('{ArrowDown}{ArrowDown}') // the fifth: 120 to 150
    expect(list.scrollTop).toBe(60)
    await user.keyboard('{ArrowUp}{ArrowUp}{ArrowUp}{ArrowUp}')
    expect(list.scrollTop).toBe(0)
    await user.keyboard('{ArrowUp}') // round to the last
    expect(screen.getByRole('option', { name: 'rover-agent package 2 minions' })).toHaveAttribute('aria-selected', 'true')
    expect(list.scrollTop).toBe(150)
  })

  it('adds an option when it is clicked, and stays ready for another', async () => {
    const user = userEvent.setup()
    const { box } = await openColumns(user)
    await user.click(box)
    await user.click(await screen.findByRole('option', { name: 'kernel 1 minion' }))
    expect(await screen.findByRole('columnheader', { name: /kernel/ })).toBeInTheDocument()
    expect(box).toHaveFocus()
    expect(box).toHaveValue('')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('adds what was typed on Enter when nothing is highlighted and nothing listed is it', async () => {
    const user = userEvent.setup()
    const { api, box } = await openColumns(user)
    // A path nothing listed is: once the packages are searched (none is it either), it's a grain path.
    await user.type(box, 'hw:serial{Enter}')
    expect(await screen.findByRole('columnheader', { name: /hw:serial/ })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/api/fleet?column=site&column=app_version&column=hw%3Aserial', expect.anything())
    expect(box).toHaveValue('')
  })

  it('adds the package or check whose name is typed, on Enter or Add', async () => {
    const user = userEvent.setup()
    const { api, menu, box } = await openColumns(user)
    // Enter before the packages are even searched: it waits for them, rather than adding "nginx"
    // as a grain path no minion has.
    await user.type(box, 'nginx{Enter}')
    expect(await screen.findByRole('columnheader', { name: /nginx/ })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith(
      '/api/fleet?column=site&column=app_version&column=%40packages%3Anginx',
      expect.anything(),
    )
    expect(api).not.toHaveBeenCalledWith('/api/fleet?column=site&column=app_version&column=nginx', expect.anything())
    expect(box).toHaveValue('')

    // A check by its name, whatever the case, with the results already in; the Add button too.
    await user.type(box, 'ROVER-CLI')
    await screen.findByRole('option', { name: 'rover-cli check 3 minions' })
    await user.click(within(menu).getByRole('button', { name: 'Add' }))
    expect(await screen.findByRole('columnheader', { name: /rover-cli/ })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('brine-fleet-columns')!).grains).toEqual([
      'site',
      'app_version',
      '@packages:nginx',
      '@rover-cli',
    ])
  })

  it('adds the grain whose name is typed, before a package of the same name', async () => {
    const user = userEvent.setup()
    const { api, box } = await openColumns(user, [...GRAIN_KEYS, { key: 'bash', minions: 3 }])
    await user.click(box)
    await screen.findByRole('option', { name: 'bash 3 minions' })
    await user.type(box, 'Bash{Enter}')
    expect(await screen.findByRole('columnheader', { name: /bash/ })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/api/fleet?column=site&column=app_version&column=bash', expect.anything())
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining('%40packages%3Abash'), expect.anything())
  })

  it('adds the only option listed on Enter', async () => {
    const user = userEvent.setup()
    const { api, box } = await openColumns(user)
    // Only the kernel grain has "kern" in it (no package does, once they're searched).
    await user.type(box, 'kern{Enter}')
    expect(await screen.findByRole('columnheader', { name: /kernel/ })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/api/fleet?column=site&column=app_version&column=kernel', expect.anything())
  })

  it('finds a package by typing and adds it as a column', async () => {
    const user = userEvent.setup()
    const { api, menu, box } = await openColumns(user)
    await user.type(box, 'ngin')
    await user.click(await screen.findByRole('option', { name: 'nginx package 2 minions' }))
    expect(api).toHaveBeenCalledWith('/api/inventory/keys?q=ngin&limit=50', expect.anything())

    // Shown just as "Add as a Fleet column" in the explorer shows it: by name, never its @ key.
    const header = await screen.findByRole('columnheader', { name: /nginx/ })
    expect(within(header).getByRole('button')).toHaveAttribute('title', 'The nginx package')
    expect(api).toHaveBeenCalledWith(
      '/api/fleet?column=site&column=app_version&column=%40packages%3Anginx',
      expect.anything(),
    )
    expect(within(menu).getByRole('button', { name: 'Remove nginx' })).toBeInTheDocument()
    expect(within(menu).getByText('package')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('brine-fleet-columns')!).grains).toEqual([
      'site',
      'app_version',
      '@packages:nginx',
    ])
  })

  it('closes only the list on the first Escape, and the menu on the next', async () => {
    const user = userEvent.setup()
    const { menu, box } = await openColumns(user)
    await user.click(box)
    await screen.findByRole('listbox')

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box).toHaveAttribute('aria-expanded', 'false')
    expect(menu).toBeInTheDocument()
    expect(box).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Choose columns' })).toBeNull()
  })

  it('closes the list on a click elsewhere, and opens it again on typing', async () => {
    const user = userEvent.setup()
    const { menu, box } = await openColumns(user)
    await user.click(box)
    await screen.findByRole('listbox')

    await user.click(within(menu).getByText('Saved in this browser'))
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(menu).toBeInTheDocument()

    await user.click(box)
    await user.keyboard('{Escape}')
    await user.keyboard('os')
    expect(offered('Grains')).toEqual(['osfinger 3 minions', 'osrelease 3 minions'])
  })

  it('keeps the menu on screen when, on a phone, its button is at the left of its row', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    await screen.findByText('rover-01')
    // jsdom lays nothing out: a 375px screen, the button's right edge 136px in, the menu 320px wide.
    const screenWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 })
    const spies = [
      vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(320),
      vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ right: 136 } as DOMRect),
    ]
    onTestFinished(() => {
      spies.forEach((s) => s.mockRestore())
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: screenWidth })
    })

    await user.click(screen.getByRole('button', { name: 'Columns' }))
    // Hanging left from the button, it would start at 136 - 320 = -184: it moves right to 16px in.
    expect(screen.getByRole('dialog', { name: 'Choose columns' })).toHaveStyle({ right: '-200px' })
  })

  it('keeps the menu inside the card it is in, when its button is at the left beside the sidebar', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/fleet': FLEET, '/api/status': systemStatus() })
    renderApp('/')
    await screen.findByText('rover-01')
    // The Fleet card cuts off what overflows it: on a 1024px screen, beside the sidebar, it runs
    // from 290 to 1004. The button's right edge is at 412, the menu 320px wide.
    const button = screen.getByRole('button', { name: 'Columns' })
    const card = button.closest<HTMLElement>('.rounded-2xl')!
    // As a browser computes overflow-hidden (jsdom doesn't expand the shorthand).
    card.style.overflowX = 'hidden'
    card.style.overflowY = 'hidden'
    const spies = [
      vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(320),
      vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
        return (this === card ? { top: 0, bottom: 900, left: 290, right: 1004 } : { right: 412 }) as DOMRect
      }),
    ]
    onTestFinished(() => spies.forEach((s) => s.mockRestore()))

    await user.click(button)
    // Hanging left from the button, it would start at 412 - 320 = 92, under the sidebar: it moves
    // right to 16px inside the card.
    expect(screen.getByRole('dialog', { name: 'Choose columns' })).toHaveStyle({ right: '-214px' })
  })

  it('shows at most 50 grains, and says to type to narrow them', async () => {
    const user = userEvent.setup()
    const many = Array.from({ length: 60 }, (_, i) => ({ key: `grain_${String(i).padStart(2, '0')}`, minions: 1 }))
    const { menu, box } = await openColumns(user, many)
    await user.click(box)
    await screen.findByRole('listbox')
    expect(offered('Grains')).toHaveLength(50)
    expect(within(screen.getByRole('group', { name: 'Grains' })).getByText('Type to narrow…')).toBeInTheDocument()
    expect(within(menu).getByRole('status')).toHaveTextContent('Grains: Type to narrow…')

    await user.type(box, 'grain_5')
    expect(offered('Grains')).toHaveLength(10)
    expect(screen.queryByText('Type to narrow…')).toBeNull()
  })

  it('shows package and check columns: the value, — when it is not there, ? when unknown', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/fleet': PACKAGE_FLEET, '/api/status': systemStatus() })
    renderApp('/?dir=desc')
    await screen.findByText('rover-01')

    // Each hover says how fresh it is: when that minion's packages, or that check, were read.
    const packagesRead = formatAsOf(ago(3600), NOW)
    const checkRead = formatAsOf(ago(600), NOW)
    expect(within(cellOf('rover-01', 'rover-agent')).getByText('2.4.1')).toHaveAttribute(
      'title',
      `2.4.1\n${packagesRead}`,
    )
    expect(within(cellOf('rover-01', 'web')).getByText('ghcr.io/acme/web:1.4')).toHaveAttribute(
      'title',
      `ghcr.io/acme/web:1.4\n${checkRead}`,
    )
    // What's missing, or empty, is said in full: which minion, which package or check.
    expect(within(cellOf('rover-02', 'rover-agent')).getByText('—')).toHaveAttribute(
      'title',
      `rover-02 doesn't have rover-agent installed\n${packagesRead}`,
    )
    expect(within(cellOf('rover-02', 'web')).getByText('—')).toHaveAttribute(
      'title',
      `rover-02's containers check doesn't list web\n${checkRead}`,
    )
    expect(within(cellOf('rover-02', 'rover-cli')).getByText('—')).toHaveAttribute(
      'title',
      `rover-02's rover-cli check reported nothing\n${checkRead}`,
    )
    for (const column of ['rover-agent', 'web', 'rover-cli'])
      expect(within(cellOf('rover-03', column)).getByText('?')).toHaveAttribute(
        'title',
        "No answer from rover-03 yet, couldn't read it, or its last answer was cut short",
      )
    expect(within(cellOf('rover-04', 'web')).getByText('(empty)')).toHaveAttribute(
      'title',
      `rover-04's containers check lists web, with an empty value\n${checkRead}`,
    )
    expect(within(cellOf('rover-04', 'rover-cli')).getByText('(empty)')).toHaveAttribute(
      'title',
      `rover-04's rover-cli check printed an empty value\n${checkRead}`,
    )

    // Named in plain words, never by their @ keys.
    const header = screen.getByRole('columnheader', { name: /web/ })
    expect(within(header).getByRole('button')).toHaveAttribute('title', 'web, from the containers check')
    await user.click(screen.getByRole('button', { name: 'Columns' }))
    const menu = screen.getByRole('dialog', { name: 'Choose columns' })
    expect(within(menu).getByText('package')).toBeInTheDocument()
    expect(within(menu).getAllByText('check')).toHaveLength(2)
    expect(within(menu).queryByText(/@packages|@containers/)).toBeNull()
  })

  it('names package and check values on phone cards, and shows what is missing or unknown', async () => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia
    mockApi({ '/api/fleet': PACKAGE_FLEET, '/api/status': systemStatus() })
    renderApp('/')
    const cards = await screen.findByRole('list', { name: 'Minions' })
    const card = (id: string) => within(cards).getByText(id).closest('a')!

    expect(card('rover-01')).toHaveTextContent('rover-agent 2.4.1')
    expect(card('rover-01')).toHaveTextContent('web ghcr.io/acme/web:1.4')
    expect(card('rover-02')).toHaveTextContent('rover-agent: not installed')
    expect(card('rover-02')).toHaveTextContent('web: not reported')
    // The label stays short; its hover is the table's.
    expect(within(card('rover-03')).getByText('rover-agent: ?')).toHaveAttribute(
      'title',
      "No answer from rover-03 yet, couldn't read it, or its last answer was cut short",
    )
    expect(card('rover-04')).toHaveTextContent('web: (empty)')
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
