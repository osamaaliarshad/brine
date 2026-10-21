import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GRAINS_HISTORY_LIMIT, MINION_CHANGES_LIMIT } from '@/api/queries'
import type { InventoryChange, InventorySource, MinionComparison, MinionDetail, MinionInventory } from '@/api/types'
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
      entries: [{ name: '', value: 'rover-cli 1.2.0', since: ago(DAY) }],
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
    expect(within(packages).getByText('Read 2h ago')).toHaveAttribute('title', expect.stringContaining('UTC'))
    expect(within(packages).getByRole('columnheader', { name: 'Version' })).toBeInTheDocument()
    expect(within(packages).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual([
      'bash5.2since brine first looked',
      'rover-agent2.4.15h ago',
      'vim9.03d ago',
    ])
    expect(within(packages).getByText('since brine first looked')).toHaveAttribute('title', expect.stringContaining('UTC'))
    expect(within(packages).getByText('5h ago')).toHaveAttribute('title', expect.stringContaining('UTC'))
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
    // A check's single value is shown as it is.
    expect(within(cli).queryByRole('table')).toBeNull()
    expect(within(cli).getByRole('link', { name: 'rover-cli 1.2.0' })).toHaveAttribute('href', '/?tab=grains&grain=%40rover-cli')

    const containers = region('containers')
    expect(containers).toHaveTextContent('The last answer was cut short; some entries may be missing.')
    expect(within(containers).getByRole('columnheader', { name: 'Value' })).toBeInTheDocument()
    expect(within(within(containers).getByRole('row', { name: /^db/ })).getByText('(empty)')).toBeInTheDocument()

    expect(region('ports')).toHaveTextContent('Not reported')
    expect(region('gpu')).toHaveTextContent('Not read yet. brine reads every online minion within a few minutes.')
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
    expect(gpu).toHaveTextContent(`brine can't read the gpu check: ${why}. Settings › Packages and checks has the lines to add.`)
    expect(within(gpu).getByRole('link', { name: 'Settings › Packages and checks' })).toHaveAttribute(
      'href',
      '/settings#packages-and-checks',
    )
    expect(gpu).not.toHaveTextContent('Not read yet')
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
    expect(within(table).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual([
      'rover-agentpackage2.4.12.3.0',
      'vimpackage—9.0',
      'rover-clicheckrover-cli 1.2.0(empty)',
    ])
    expect(within(table).getByRole('link', { name: 'vim' })).toHaveAttribute('href', '/?tab=grains&grain=%40packages%3Avim')
    expect(screen.getByText('3 differences')).toBeInTheDocument()
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
    expect(await screen.findByText('Same packages and checks.')).toBeInTheDocument()
  })

  it('shows how the fleet differs from this minion, most different first', async () => {
    const user = userEvent.setup()
    const fetchMock = renderWith({
      '/api/inventory/compare': (url: URL) => ({
        reference: url.searchParams.get('reference'),
        minions: [
          { minion_id: 'dock-01', read: true, different: 0, only_reference: 1, only_minion: 0 },
          { minion_id: 'rover-02', read: true, different: 0, only_reference: 0, only_minion: 0 },
          { minion_id: 'rover-03', read: true, different: 3, only_reference: 1, only_minion: 2 },
          { minion_id: 'rover-05', read: false, different: 0, only_reference: 0, only_minion: 0 },
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
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/inventory/compare'))).toBe(false)

    await user.click(open)
    expect(open).toHaveAttribute('aria-expanded', 'true')
    const list = await screen.findByRole('list', { name: 'How the fleet differs from rover-01' })
    expect(within(list).getAllByRole('listitem').map((r) => r.textContent)).toEqual([
      'rover-033 different · 1 missing · 2 extraCompare',
      'dock-011 missingCompare',
      'rover-02Same as rover-01Compare',
      'rover-05Not read yet',
    ])
    expect(screen.getByText("Missing: rover-01 has it, they don't. Extra: they have it, rover-01 doesn't.")).toBeInTheDocument()

    await user.click(within(list).getByRole('link', { name: 'Compare with rover-03' }))
    expect(await screen.findByRole('table', { name: 'Where rover-01 and rover-03 differ' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Compare with' })).toHaveValue('rover-03')
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
    expect(within(grains!).getByText('1 changed · 1 added')).toBeInTheDocument()
    expect(within(grains!).getByText('"2.4.0"')).toHaveClass('line-through')

    expect(packages).toHaveTextContent('10m ago')
    expect(packages).toHaveTextContent('Packages: 1 changed · 1 added')
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

  it('stops the history where either list was cut short', async () => {
    const upgrade: InventoryChange[] = Array.from({ length: MINION_CHANGES_LIMIT }, (_, i) => ({
      minion_id: 'rover-01',
      source: 'packages',
      name: `lib-${i}`,
      old: '1.0',
      new: '1.1',
      at: ago(3600),
      since: ago(7200),
      jid: null,
      user: null,
    }))
    api({
      '/api/minions/rover-01/grains/history': [
        { collected_at: ago(60), added: { new: 1 }, removed: {}, changed: {} },
        // Older than the oldest change listed: other package changes may be missing around it.
        { collected_at: ago(DAY), added: { os: 'Debian' }, removed: {}, changed: {} },
      ],
      '/api/inventory/changes': upgrade,
    })
    renderApp('/minions/rover-01?tab=history')
    const history = await screen.findByRole('list', { name: 'History' })
    expect(Array.from(history.children).map((e) => e.firstElementChild?.textContent)).toEqual(['1m ago', '1h ago'])
    expect(history.children[1]).toHaveTextContent(`Packages: ${MINION_CHANGES_LIMIT} changed`)
    expect(screen.getByText("Older history isn't shown.")).toBeInTheDocument()
  })

  it('does not call the oldest of a cut-short grains history the first collection', async () => {
    api({
      '/api/minions/rover-01/grains/history': Array.from({ length: GRAINS_HISTORY_LIMIT }, (_, i) => ({
        collected_at: ago(60 * (i + 1)),
        added: {},
        removed: {},
        changed: { app_version: { from: `2.${i}`, to: `2.${i + 1}` } },
      })),
      '/api/inventory/changes': [],
    })
    renderApp('/minions/rover-01?tab=history')
    const history = await screen.findByRole('list', { name: 'History' })
    expect(history.children).toHaveLength(GRAINS_HISTORY_LIMIT)
    expect(history.lastElementChild).toHaveTextContent('1 changed')
    expect(screen.queryByText(/First collection/)).toBeNull()
    expect(screen.getByText("Older history isn't shown.")).toBeInTheDocument()
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
