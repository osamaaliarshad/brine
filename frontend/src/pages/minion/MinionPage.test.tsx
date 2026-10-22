import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GRAINS_HISTORY_LIMIT, MINION_CHANGES_LIMIT } from '@/api/queries'
import type { InventoryChange, InventorySource, MinionComparison, MinionDetail, MinionInventory } from '@/api/types'
import { formatAbsolute, formatAsOf } from '@/lib/time'
import { FakeEventSource } from '@/test/setup'
import { ago, fleet, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

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

const DAY = 86400

const source = (patch: Partial<InventorySource> & Pick<InventorySource, 'source'>): InventorySource => ({
  kind: patch.source === 'packages' ? 'package' : 'check',
  read_at: ago(3600),
  first_read_at: ago(DAY),
  answered_at: ago(3600),
  error: null,
  truncated: false,
  refused: null,
  entries: [],
  ...patch,
})

const INVENTORY: MinionInventory = {
  sources: [
    source({
      source: 'packages',
      read_at: ago(2 * 3600),
      first_read_at: ago(17 * DAY),
      answered_at: ago(2 * 3600),
      entries: [
        { name: 'bash', value: '5.2', since: ago(17 * DAY) },
        { name: 'rover-agent', value: '2.4.1', since: ago(5 * 3600) },
        { name: 'vim', value: '9.0', since: ago(3 * DAY) },
      ],
    }),
    // The last answer failed: the entries are the last good read's.
    source({
      source: 'rover-cli',
      answered_at: ago(600),
      error: 'exit 127: sh: rover-cli: not found',
      entries: [{ name: '', value: 'rover-cli 1.2.0', since: ago(3600) }], // changed at its last good read
    }),
    source({
      source: 'containers',
      truncated: true,
      entries: [
        { name: 'db', value: '', since: ago(DAY) },
        { name: 'web', value: 'ghcr.io/acme/web:1.4', since: ago(3600) },
      ],
    }),
    source({ source: 'ports' }), // read, and printed nothing
    source({ source: 'gpu', read_at: null, first_read_at: null, answered_at: null }),
  ],
}

/** "Oct 3" (in the test machine's locale), as "first read" shows a day. */
const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

const region = (name: string) => screen.getByRole('region', { name })

/** The Packages tab with a fleet to compare with. */
function renderWith(extra: Record<string, unknown>, path = '/minions/rover-01?tab=packages') {
  const fetchMock = api({
    '/api/minions/rover-01/inventory': INVENTORY,
    '/api/fleet': fleet(['dock-01', 'rover-01', 'rover-02', 'rover-03'].map((id) => minion(id))),
    ...extra,
  })
  return { fetchMock, ...renderApp(path) }
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
    // Each grain's value, and what the header takes from grains, say how fresh they are.
    const value = within(screen.getByRole('rowheader', { name: 'app_version' }).closest('tr')!).getByRole('cell')
    expect(value).toHaveAttribute('title', formatAsOf(ago(240), NOW))
    expect(screen.getByText('10.0.0.11 · Debian 12 · Salt 3006.28')).toHaveAttribute('title', formatAsOf(ago(240), NOW))
  })

  it("says when grains come from the master's cache, age unknown", async () => {
    mockApi({
      '/api/minions/rover-01': { ...DETAIL, grains_source: 'master_cache', grains_at: null },
      '/api/status': systemStatus(),
    })
    renderApp('/minions/rover-01')
    const key = await screen.findByRole('rowheader', { name: 'app_version' })
    expect(within(key.closest('tr')!).getByRole('cell')).toHaveAttribute('title', "From the master's cache; age unknown")
  })

  it('filters grains by name or value', async () => {
    const user = userEvent.setup()
    api()
    renderApp('/minions/rover-01')
    await user.type(await screen.findByRole('searchbox', { name: 'Filter grains' }), 'R2')
    expect(screen.getAllByRole('rowheader').map((r) => r.textContent)).toEqual(['hw'])
  })

  it('lists packages and each check, with when each was read', async () => {
    api({ '/api/minions/rover-01/inventory': INVENTORY })
    renderApp('/minions/rover-01?tab=packages')
    const tabs = await screen.findAllByRole('tab')
    expect(tabs.slice(0, 3).map((t) => t.textContent)).toEqual(['Grains', 'Packages', 'History'])

    const packages = await screen.findByRole('region', { name: 'Packages' })
    expect(packages).toHaveTextContent(`Read 2h ago · first read ${day(ago(17 * DAY))}`)
    expect(within(packages).getByText('Read 2h ago')).toHaveAttribute('title', formatAbsolute(ago(2 * 3600)))
    expect(within(packages).getByRole('columnheader', { name: 'Version' })).toBeInTheDocument()
    // Only what appeared or changed since brine first looked has a time, so it stands out; the
    // rest is blank but for screen readers.
    const rows = within(packages).getAllByRole('row').slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      "bash5.2Already there at brine's first read",
      'rover-agent2.4.15h ago',
      'vim9.03d ago',
    ])
    const [, , since] = within(rows[0]!).getAllByRole('cell')
    expect(within(since!).getByText("Already there at brine's first read")).toHaveClass('sr-only')
    expect(since).toHaveAttribute('title', `Already there when brine first read rover-01 on ${day(ago(17 * DAY))}`)
    // A version says how fresh it is: as of that read.
    expect(within(rows[1]!).getAllByRole('cell')[1]).toHaveAttribute('title', formatAsOf(ago(2 * 3600), NOW))
    expect(within(packages).getByText('5h ago')).toHaveAttribute('title', formatAbsolute(ago(5 * 3600)))
    // One click to who else has it.
    expect(within(packages).getByRole('link', { name: 'rover-agent' })).toHaveAttribute(
      'href',
      '/?tab=grains&grain=%40packages%3Arover-agent',
    )

    // The last answer failed: the entries kept are the last good read's, and it says so.
    const cli = region('rover-cli')
    expect(cli).toHaveTextContent('check')
    expect(cli).toHaveTextContent(`Last good read 1h ago · first read ${day(ago(DAY))}`)
    expect(within(cli).getByText("Couldn't read: exit 127: sh: rover-cli: not found")).toBeInTheDocument()
    // A check's single value is shown as it is, with when it changed.
    expect(within(cli).queryByRole('table')).toBeNull()
    const value = within(cli).getByRole('link', { name: 'rover-cli 1.2.0' })
    expect(value).toHaveAttribute('href', '/?tab=grains&grain=%40rover-cli')
    // How fresh it is, like a version in a table: as of the last good read.
    expect(value).toHaveAttribute('title', `See rover-cli across the fleet\n${formatAsOf(ago(3600), NOW)}`)
    expect(within(cli).getByText('since 1h ago')).toHaveAttribute('title', formatAbsolute(ago(3600)))

    const containers = region('containers')
    expect(containers).toHaveTextContent('The last answer was cut short; some entries may be missing.')
    expect(within(containers).getByRole('columnheader', { name: 'Value' })).toBeInTheDocument()
    const db = within(containers).getByRole('row', { name: /^db/ })
    expect(db).toHaveTextContent("db(empty)Already there at brine's first read")
    expect(within(db).getByText('(empty)')).toBeInTheDocument()

    expect(region('ports')).toHaveTextContent('Not reported')
    expect(region('gpu')).toHaveTextContent('No answer yet. brine reads every online minion within a few minutes.')
  })

  it('on a phone, puts since under the value, and only where something changed', async () => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia
    try {
      api({ '/api/minions/rover-01/inventory': INVENTORY })
      renderApp('/minions/rover-01?tab=packages')
      const packages = await screen.findByRole('region', { name: 'Packages' })
      expect(within(packages).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Name', 'Version'])
      expect(within(packages).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual([
        'bash5.2',
        'rover-agent2.4.1since 5h ago',
        'vim9.0since 3d ago',
      ])
    } finally {
      // @ts-expect-error -- jsdom doesn't define it; take the phone stub away again.
      delete window.matchMedia
    }
  })

  it("says when Salt won't let brine read a source, and where to fix it", async () => {
    const why = "brine's Salt account isn't allowed to run cmd.run_all"
    api({
      '/api/minions/rover-01/inventory': {
        sources: INVENTORY.sources.map((s) => (s.source === 'gpu' ? { ...s, refused: why } : s)),
      },
    })
    renderApp('/minions/rover-01?tab=packages')
    const gpu = await screen.findByRole('region', { name: 'gpu' })
    // In the explorer's words.
    expect(gpu).toHaveTextContent(
      `brine can't read the gpu check: ${why}. Settings › Packages and checks has the lines to add to brine's Salt account.`,
    )
    expect(within(gpu).getByRole('link', { name: 'Settings › Packages and checks' })).toHaveAttribute(
      'href',
      '/settings#packages-and-checks',
    )
    expect(gpu).not.toHaveTextContent('No answer yet')
  })

  it('filters every package and check with one search box', async () => {
    const user = userEvent.setup()
    api({ '/api/minions/rover-01/inventory': INVENTORY })
    renderApp('/minions/rover-01?tab=packages')
    const search = await screen.findByRole('searchbox', { name: 'Filter packages and checks' })
    const rows = (name: string) => within(region(name)).getAllByRole('row').slice(1).map((r) => r.textContent)

    await user.type(search, 'agent')
    expect(rows('Packages')).toEqual(['rover-agent2.4.15h ago'])
    expect(region('Packages')).toHaveTextContent('1 of 3')
    expect(screen.queryByRole('region', { name: 'containers' })).toBeNull()

    // Values too.
    await user.clear(search)
    await user.type(search, 'GHCR')
    expect(rows('containers')).toEqual(['webghcr.io/acme/web:1.41h ago'])
    expect(screen.queryByRole('region', { name: 'Packages' })).toBeNull()

    // A check by its name, whatever it has.
    await user.clear(search)
    await user.type(search, 'gpu')
    expect(screen.getAllByRole('region')).toEqual([region('gpu')])

    await user.clear(search)
    await user.type(search, 'zzz')
    expect(screen.getByText('No packages or checks match “zzz”.')).toBeInTheDocument()
  })

  it('reads this minion now, and says so until its answers arrive', async () => {
    const user = userEvent.setup()
    const bodies: unknown[] = []
    let inventory = INVENTORY
    const answers: unknown[] = [
      { asked: ['rover-01'], queued: false, failed: {}, reason: null },
      new Response(JSON.stringify({ detail: 'Already reading; try again in a few seconds.' }), { status: 429 }),
      { asked: [], queued: false, failed: {}, reason: "rover-01 isn't online" },
    ]
    api({
      '/api/minions/rover-01/inventory': () => inventory,
      '/api/inventory/ask': (_url: URL, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body)))
        return answers.shift()
      },
    })
    renderApp('/minions/rover-01?tab=packages')
    const read = await screen.findByRole('button', { name: 'Read now' })
    await user.click(read)
    expect(await screen.findByRole('status')).toHaveTextContent('Reading rover-01; answers appear as they arrive.')
    expect(bodies).toEqual([{ minion: 'rover-01' }])

    // An answer comes in, stamped before the click by this browser's clock: the note goes.
    inventory = {
      sources: INVENTORY.sources.map((s) =>
        s.source === 'gpu' ? { ...s, read_at: ago(5), first_read_at: ago(5), answered_at: ago(5) } : s,
      ),
    }
    FakeEventSource.instances[0]!.emit({ type: 'minion', id: 'rover-01' })
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())

    await user.click(read)
    expect(await screen.findByRole('status')).toHaveTextContent('Already reading; try again in a few seconds.')
    await user.click(read)
    expect(await screen.findByRole('status')).toHaveTextContent("Not asked: rover-01 isn't online.")
  })

  it('compares with another minion, picked or from the link', async () => {
    const user = userEvent.setup()
    const comparison = (minion: string, patch: Partial<MinionComparison> = {}): MinionComparison => ({
      reference: 'rover-01',
      minion,
      sources_compared: ['packages', 'rover-cli'],
      differences: [],
      ...patch,
    })
    const { router } = renderWith(
      {
        '/api/inventory/compare/rover-03': comparison('rover-03', {
          differences: [
            { source: 'packages', name: 'rover-agent', reference: '2.4.1', minion: '2.3.0' },
            { source: 'packages', name: 'vim', reference: null, minion: '9.0' },
            { source: 'rover-cli', name: '', reference: 'rover-cli 1.2.0', minion: '' },
            { source: 'rover-cli', name: 'channel', reference: 'stable', minion: null },
          ],
        }),
        '/api/inventory/compare/dock-01': comparison('dock-01'),
      },
      '/minions/rover-01?tab=packages&compare=rover-03',
    )
    const table = await screen.findByRole('table', { name: 'Where rover-01 and rover-03 differ' })
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Package or check',
      'rover-01',
      'rover-03',
    ])
    // Not there reads as it does in the explorer: a package isn't installed, a check's entry isn't reported.
    expect(within(table).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual([
      'rover-agentpackage2.4.12.3.0',
      'vimpackageNot installed9.0',
      'rover-clicheckrover-cli 1.2.0(empty)',
      'channelcheckstableNot reported',
    ])
    expect(within(table).getByRole('link', { name: 'vim' })).toHaveAttribute('href', '/?tab=grains&grain=%40packages%3Avim')
    expect(screen.getByText('4 differences')).toBeInTheDocument()
    // Sources only one of them has read in full aren't compared, and it says which.
    expect(screen.getByText(/Not compared: the containers, ports and gpu checks/)).toBeInTheDocument()
    const pick = screen.getByRole('combobox', { name: 'Compare with' })
    expect(pick).toHaveValue('rover-03')
    expect(within(pick).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Compare with…',
      'dock-01',
      'rover-02',
      'rover-03',
    ])

    await user.click(screen.getByRole('button', { name: 'Stop comparing' }))
    expect(screen.queryByRole('table', { name: /differ/ })).toBeNull()
    expect(Object.fromEntries(new URLSearchParams(router.state.location.search))).toEqual({ tab: 'packages' })

    await user.selectOptions(pick, 'dock-01')
    expect(Object.fromEntries(new URLSearchParams(router.state.location.search))).toEqual({
      tab: 'packages',
      compare: 'dock-01',
    })
    expect(await screen.findByText('rover-01 and dock-01 have the same packages and checks.')).toBeInTheDocument()
  })

  it('ignores a comparison with itself', async () => {
    const fetchMock = renderWith({}, '/minions/rover-01?tab=packages&compare=rover-01').fetchMock
    const pick = await screen.findByRole('combobox', { name: 'Compare with' })
    await waitFor(() => expect(within(pick).getAllByRole('option')).toHaveLength(4))
    expect(pick).toHaveValue('')
    expect(within(pick).queryByRole('option', { name: 'rover-01' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Stop comparing' })).toBeNull()
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/inventory/compare'))).toBe(false)
  })

  it('shows how the fleet differs from this minion, most different first', async () => {
    const user = userEvent.setup()
    const compares = () => fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/inventory/compare?')).length
    const fleets = () => fetchMock.mock.calls.filter(([u]) => String(u).startsWith('/api/fleet')).length
    const minions = () => fetchMock.mock.calls.filter(([u]) => String(u).startsWith('/api/minions/rover-01')).length
    const row = (id: string, read: boolean, sources: string[], counts: number[]) => ({
      minion_id: id,
      read,
      sources_compared: sources,
      different: counts[0],
      only_reference: counts[1],
      only_minion: counts[2],
    })
    const fetchMock = renderWith({
      '/api/inventory/compare': (url: URL) => ({
        reference: url.searchParams.get('reference'),
        reference_sources: ['packages', 'rover-cli'],
        minions: [
          row('dock-01', true, ['packages'], [0, 1, 0]),
          row('rover-02', true, ['rover-cli'], [0, 0, 0]),
          row('rover-03', true, ['packages', 'rover-cli'], [3, 1, 2]),
          row('rover-05', false, [], [0, 0, 0]),
        ],
      }),
      '/api/inventory/compare/rover-03': {
        reference: 'rover-01',
        minion: 'rover-03',
        sources_compared: ['packages'],
        differences: [{ source: 'packages', name: 'vim', reference: null, minion: '9.0' }],
      },
    }).fetchMock
    const open = await screen.findByRole('button', { name: 'How the fleet differs from rover-01' })
    expect(compares()).toBe(0)

    await user.click(open)
    expect(open).toHaveAttribute('aria-expanded', 'true')
    const list = await screen.findByRole('list', { name: 'How the fleet differs from rover-01' })
    // What one of them hasn't read in full isn't compared, and the row says so.
    expect(within(list).getAllByRole('listitem').map((r) => r.textContent)).toEqual([
      'rover-033 different · 1 missing · 2 extraCompare',
      'dock-011 missing · the rover-cli check not comparedCompare',
      'rover-02Same as rover-01 · packages not comparedCompare',
      'rover-05Nothing to compare yet',
    ])
    expect(screen.getByText("Missing: rover-01 has it, they don't. Extra: they have it, rover-01 doesn't.")).toBeInTheDocument()

    // Heavy across a big fleet: kept for a minute, not redone on every live update (nor on every
    // job on the reference), and redone on Compare again.
    expect(screen.getByText('Compared just now')).toBeInTheDocument()
    const before = fleets()
    FakeEventSource.instances[0]!.emit({ type: 'fleet' })
    await waitFor(() => expect(fleets()).toBeGreaterThan(before))
    const minionBefore = minions()
    FakeEventSource.instances[0]!.emit({ type: 'minion', id: 'rover-01' })
    await waitFor(() => expect(minions()).toBeGreaterThan(minionBefore))
    expect(compares()).toBe(1)
    await user.click(screen.getByRole('button', { name: 'Compare again' }))
    await waitFor(() => expect(compares()).toBe(2))
    // Redone, too, when the reference's packages or checks move (its new read lands).
    FakeEventSource.instances[0]!.emit({ type: 'inventory', id: 'rover-01' })
    await waitFor(() => expect(compares()).toBe(3))

    await user.click(within(list).getByRole('link', { name: 'Compare with rover-03' }))
    expect(await screen.findByRole('table', { name: 'Where rover-01 and rover-03 differ' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Compare with' })).toHaveValue('rover-03')
  })

  it('says there is nothing to compare until this minion is read in full', async () => {
    const user = userEvent.setup()
    renderWith({
      '/api/inventory/compare': {
        reference: 'rover-01',
        reference_sources: [],
        minions: [
          { minion_id: 'rover-02', read: false, sources_compared: [], different: 0, only_reference: 0, only_minion: 0 },
        ],
      },
    })
    await user.click(await screen.findByRole('button', { name: 'How the fleet differs from rover-01' }))
    expect(await screen.findByText('Nothing to compare until rover-01 has been read in full.')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'How the fleet differs from rover-01' })).toBeNull()
  })

  it('says how long history is kept', async () => {
    const retention = (history_days: number) => ({ retention: { jobs_days: 30, history_days, audit_days: 365 } })
    api({
      '/api/minions/rover-01/grains/history': [{ collected_at: ago(60), added: { os: 'Debian' }, removed: {}, changed: {} }],
      '/api/inventory/changes': [],
      '/api/settings': retention(90),
    })
    renderApp('/minions/rover-01?tab=history')
    expect(await screen.findByText("Kept for 90 days (retention in brine's config).")).toBeInTheDocument()
  })

  it('says when history is kept forever', async () => {
    api({
      '/api/minions/rover-01/grains/history': [],
      '/api/inventory/changes': [],
      '/api/settings': { retention: { jobs_days: 30, history_days: 0, audit_days: 365 } },
    })
    renderApp('/minions/rover-01?tab=history')
    expect(await screen.findByText("Kept forever (retention in brine's config).")).toBeInTheDocument()
  })

  it('shows grains, package and check changes in one history, newest first', async () => {
    const change = (patch: Partial<InventoryChange>): InventoryChange => ({
      minion_id: 'rover-01',
      source: 'packages',
      name: 'rover-agent',
      old: '2.3.0',
      new: '2.4.1',
      at: ago(600),
      since: ago(6 * 3600),
      jid: '20261020114000000001',
      user: 'alice@example.com',
      ...patch,
    })
    api({
      '/api/minions/rover-01/grains/history': [
        { collected_at: ago(60), added: { new: 1 }, removed: {}, changed: { app_version: { from: '2.4.0', to: '2.4.1' } } },
        { collected_at: ago(DAY), added: { os: 'Debian', app_version: '2.4.0' }, removed: {}, changed: {} },
      ],
      '/api/inventory/changes': (url: URL) =>
        url.searchParams.get('minion') === 'rover-01'
          ? [
              change({}),
              change({ name: 'vim', old: null, new: '9.0' }),
              change({ source: 'rover-cli', name: '', old: '1.1.0', new: '1.2.0', at: ago(2 * 3600), since: ago(8 * 3600), jid: null, user: null }),
            ]
          : [],
    })
    renderApp('/minions/rover-01?tab=history')
    expect(screen.queryByRole('tab', { name: 'Grains history' })).toBeNull()
    const history = await screen.findByRole('list', { name: 'History' })
    const [grains, packages, cli, first] = Array.from(history.children) as HTMLElement[]
    expect(history.children).toHaveLength(4)

    expect(grains).toHaveTextContent('1m ago')
    expect(within(grains!).getByText('Grains: 1 changed · 1 new')).toBeInTheDocument()
    expect(within(grains!).getByText('"2.4.0"')).toHaveClass('line-through')

    expect(packages).toHaveTextContent('10m ago')
    // "new", as its row says "(new)".
    expect(packages).toHaveTextContent('Packages: 1 changed · 1 new')
    expect(packages).toHaveTextContent('found after job 20261020114000000001 by alice@example.com')
    expect(within(packages!).getByRole('link', { name: '20261020114000000001' })).toHaveAttribute(
      'href',
      '/jobs/20261020114000000001',
    )
    expect(within(packages!).getAllByRole('listitem').map((r) => r.textContent)).toEqual([
      'rover-agent 2.3.0 → 2.4.1',
      'vim 9.0 (new)',
    ])

    expect(cli).toHaveTextContent('2h ago')
    expect(cli).toHaveTextContent('rover-cli check: changed')
    expect(cli).toHaveTextContent('sometime between 8h and 2h ago')
    expect(within(cli!).getAllByRole('listitem').map((r) => r.textContent)).toEqual(['rover-cli 1.1.0 → 1.2.0'])

    expect(first).toHaveTextContent('First collection · 2 grains')
  })

  describe('at the limit', () => {
    const base = { minion_id: 'rover-01', since: ago(7200), jid: null, user: null }
    const cli: InventoryChange = { ...base, source: 'rover-cli', name: '', old: '1.1', new: '1.2', at: ago(600) }
    /** A big upgrade of `count` packages, an hour ago: newest first, it comes after the check. */
    const upgrade = (count: number): InventoryChange[] =>
      Array.from({ length: count }, (_, i) => ({
        ...base,
        source: 'packages',
        name: `lib-${i}`,
        old: i % 2 ? null : '1.0',
        new: '1.1',
        at: ago(3600),
      }))
    const GRAINS = [
      { collected_at: ago(60), added: { new: 1 }, removed: {}, changed: {} },
      // Older than the oldest change listed: if that list was cut, changes may be missing around it.
      { collected_at: ago(DAY), added: { os: 'Debian' }, removed: {}, changed: {} },
    ]
    /** Grains history `count` long, a minute apart; the oldest is the first collection when it's all there. */
    const grainsHistory = (count: number) =>
      Array.from({ length: count }, (_, i) => ({
        collected_at: ago(60 * (i + 1)),
        added: i === count - 1 ? { os: 'Debian' } : {},
        removed: {},
        changed: i === count - 1 ? {} : { app_version: { from: `2.${i}`, to: `2.${i + 1}` } },
      }))
    const asked = (fetchMock: ReturnType<typeof api>, path: string) =>
      fetchMock.mock.calls
        .map(([url]) => new URL(String(url), 'http://brine.test'))
        .filter((url) => url.pathname === path)
        .map((url) => url.searchParams.get('limit'))

    it('asks for one more than it shows, to tell whether there are more', async () => {
      const fetchMock = api({ '/api/minions/rover-01/grains/history': GRAINS, '/api/inventory/changes': [] })
      renderApp('/minions/rover-01?tab=history')
      await screen.findByRole('list', { name: 'History' })
      expect(asked(fetchMock, '/api/minions/rover-01/grains/history')).toEqual([String(GRAINS_HISTORY_LIMIT + 1)])
      expect(asked(fetchMock, '/api/inventory/changes')).toEqual([String(MINION_CHANGES_LIMIT + 1)])
    })

    it('shows everything when the changes are exactly the limit', async () => {
      api({
        '/api/minions/rover-01/grains/history': GRAINS,
        '/api/inventory/changes': [cli, ...upgrade(MINION_CHANGES_LIMIT - 1)],
      })
      renderApp('/minions/rover-01?tab=history')
      const history = await screen.findByRole('list', { name: 'History' })
      expect(Array.from(history.children).map((e) => e.firstElementChild?.textContent)).toEqual([
        '1m ago',
        '10m ago',
        '1h ago',
        '1d ago',
      ])
      // 250 changed and 249 new: the whole upgrade.
      expect(history.children[2]).toHaveTextContent('Packages: 250 changed · 249 new')
      expect(history.children[3]).toHaveTextContent('First collection · 1 grains')
      expect(screen.queryByText("Older history isn't shown.")).toBeNull()
    })

    it('stops the history where the changes were cut short, and says the read at the cut may have more', async () => {
      api({
        '/api/minions/rover-01/grains/history': GRAINS,
        // One more than the limit: the last one is the same read's, so it stops partway through it.
        '/api/inventory/changes': [cli, ...upgrade(MINION_CHANGES_LIMIT)],
      })
      renderApp('/minions/rover-01?tab=history')
      const history = await screen.findByRole('list', { name: 'History' })
      expect(Array.from(history.children).map((e) => e.firstElementChild?.textContent)).toEqual([
        '1m ago',
        '10m ago',
        '1h ago',
      ])
      expect(history.children[1]).toHaveTextContent('rover-cli check: changed')
      expect(history.children[2]).toHaveTextContent(`Packages: ${MINION_CHANGES_LIMIT - 1} or more changed`)
      expect(within(history.children[2] as HTMLElement).getAllByRole('listitem')).toHaveLength(MINION_CHANGES_LIMIT - 1)
      expect(screen.getByText("Older history isn't shown.")).toBeInTheDocument()
    })

    it('says a read at the cut is whole when the change left out is an older read', async () => {
      const older: InventoryChange = { ...cli, at: ago(2 * 3600), since: ago(3 * 3600) }
      api({
        '/api/minions/rover-01/grains/history': GRAINS,
        '/api/inventory/changes': [cli, ...upgrade(MINION_CHANGES_LIMIT - 1), older],
      })
      renderApp('/minions/rover-01?tab=history')
      const history = await screen.findByRole('list', { name: 'History' })
      expect(history.children).toHaveLength(3)
      expect(history.children[2]).toHaveTextContent('Packages: 250 changed · 249 new')
      expect(screen.getByText("Older history isn't shown.")).toBeInTheDocument()
    })

    it('calls the oldest of a grains history exactly the limit long the first collection', async () => {
      api({
        '/api/minions/rover-01/grains/history': grainsHistory(GRAINS_HISTORY_LIMIT),
        '/api/inventory/changes': [],
      })
      renderApp('/minions/rover-01?tab=history')
      const history = await screen.findByRole('list', { name: 'History' })
      expect(history.children).toHaveLength(GRAINS_HISTORY_LIMIT)
      expect(history.lastElementChild).toHaveTextContent('First collection · 1 grains')
      expect(screen.queryByText("Older history isn't shown.")).toBeNull()
    })

    it('does not call the oldest of a cut-short grains history the first collection', async () => {
      api({
        '/api/minions/rover-01/grains/history': grainsHistory(GRAINS_HISTORY_LIMIT + 1),
        '/api/inventory/changes': [],
      })
      renderApp('/minions/rover-01?tab=history')
      const history = await screen.findByRole('list', { name: 'History' })
      expect(history.children).toHaveLength(GRAINS_HISTORY_LIMIT)
      expect(history.lastElementChild).toHaveTextContent('Grains: 1 changed')
      expect(screen.queryByText(/First collection/)).toBeNull()
      expect(screen.getByText("Older history isn't shown.")).toBeInTheDocument()
    })
  })

  it('says when there is no history yet', async () => {
    api({ '/api/minions/rover-01/grains/history': [], '/api/inventory/changes': [] })
    renderApp('/minions/rover-01?tab=history')
    expect(await screen.findByText('No grains or packages collected yet.')).toBeInTheDocument()
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
