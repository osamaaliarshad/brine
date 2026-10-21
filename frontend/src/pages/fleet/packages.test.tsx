import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InventoryChange, InventoryDistribution, InventoryKey, User } from '@/api/types'
import { ago, fleet, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const OPERATOR: User = { email: 'o@example.com', name: 'Otto', picture: null, role: 'operator', provider: 'oidc' }
const VIEWER: User = { ...OPERATOR, role: 'viewer' }

const FLEET = fleet(['dock-01', 'rover-01', 'rover-02', 'rover-03', 'rover-04'].map((id) => minion(id)))

const CHECKS: InventoryKey[] = [
  { key: '@containers:web', source: 'containers', name: 'web', kind: 'check', minions: 2 },
  { key: '@rover-cli', source: 'rover-cli', name: '', kind: 'check', minions: 4 },
]
const AGENT_KEY: InventoryKey = {
  key: '@packages:rover-agent',
  source: 'packages',
  name: 'rover-agent',
  kind: 'package',
  minions: 3,
}

const AGENT: InventoryDistribution = {
  key: '@packages:rover-agent',
  source: 'packages',
  name: 'rover-agent',
  kind: 'package',
  total: 5,
  values: [
    { value: '2.4.1', text: '2.4.1', minions: ['rover-01', 'rover-02'] },
    { value: '2.3.0', text: '2.3.0', minions: ['dock-01'] },
  ],
  missing: ['rover-03'],
  unknown: ['rover-04'],
  oldest_read_at: ago(3 * 3600),
  newest_read_at: ago(20 * 60),
  refused: null,
}

const change = (patch: Partial<InventoryChange>): InventoryChange => ({
  minion_id: 'rover-01',
  source: 'packages',
  name: 'rover-agent',
  old: '2.3.0',
  new: '2.4.1',
  at: ago(20 * 60),
  since: ago(3 * 3600),
  jid: null,
  user: null,
  ...patch,
})

const CHANGES: InventoryChange[] = [
  change({ jid: '20261020114000000001', user: 'alice@example.com' }),
  change({ minion_id: 'rover-02', at: ago(3600), since: ago(4 * 3600), user: 'bob@example.com' }),
  change({ minion_id: 'rover-03', new: null, at: ago(2 * 3600), since: ago(8 * 3600) }),
  change({ minion_id: 'dock-01', old: null, new: '2.3.0', at: ago(5 * 3600), since: ago(11 * 3600), jid: '20261020070000000002' }),
]

function api(extra: Record<string, unknown> = {}) {
  return mockApi({
    '/api/fleet': FLEET,
    '/api/status': systemStatus(),
    '/api/auth/me': OPERATOR,
    '/api/capabilities': { manage_keys: { allowed: true, missing: [] }, commands: ['*'] },
    '/api/grains/keys': [{ key: 'app_version', minions: 5 }],
    '/api/grains/values': { grain: 'site', total: 5, values: [], missing: [] },
    // Like the backend: every check's entries, or with q, the packages and checks that match.
    '/api/inventory/keys': (url: URL) => {
      const q = url.searchParams.get('q') ?? ''
      return q ? [AGENT_KEY, ...CHECKS].filter((k) => k.key.includes(q)) : CHECKS
    },
    '/api/inventory/values': AGENT,
    '/api/inventory/changes': CHANGES,
    ...extra,
  })
}

describe('Fleet › Grains & packages', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('lists every check, and finds packages once two letters are typed', async () => {
    const user = userEvent.setup()
    const fetchMock = api()
    const { router } = renderApp('/?tab=grains')
    expect(await screen.findByRole('tab', { name: 'Grains & packages' })).toHaveAttribute('aria-selected', 'true')
    const list = screen.getByRole('list', { name: 'Packages and checks' })
    expect(await within(list).findByRole('button', { name: /web/ })).toHaveTextContent('check')
    expect(within(list).getByRole('button', { name: /rover-cli/ })).toHaveTextContent('check')
    expect(within(list).getByText('Type 2 or more letters to find a package.')).toBeInTheDocument()

    const asked = () =>
      fetchMock.mock.calls
        .map(([url]) => new URL(String(url), 'http://brine.test'))
        .filter((url) => url.pathname === '/api/inventory/keys')
        .map((url) => url.searchParams.get('q'))
    const search = screen.getByRole('searchbox', { name: 'Find a grain or package' })
    await user.type(search, 'a')
    await new Promise((resolve) => setTimeout(resolve, 400)) // past the debounce
    expect(asked().every((q) => q === '')).toBe(true) // one letter doesn't search packages

    await user.type(search, 'gent')
    const agent = await within(list).findByRole('button', { name: /rover-agent/ })
    expect(agent).toHaveTextContent('package')
    expect(agent).toHaveTextContent('3')
    expect(asked()).toContain('agent')
    expect(within(list).queryByText('Type 2 or more letters to find a package.')).toBeNull()
    expect(screen.getByText('No grains match.')).toBeInTheDocument()

    await user.click(agent)
    expect(new URLSearchParams(router.state.location.search).get('grain')).toBe('@packages:rover-agent')
    expect(await screen.findByRole('heading', { name: 'rover-agent' })).toBeInTheDocument()

    await user.clear(search)
    await user.type(search, 'zzz')
    expect(await within(list).findByText('No packages or checks match.')).toBeInTheDocument()
  })

  it("shows a package's versions newest first, who lacks it, who hasn't answered, and its changes", async () => {
    const user = userEvent.setup()
    api()
    renderApp('/?tab=grains&grain=@packages:rover-agent')

    const versions = await screen.findByRole('list', { name: 'Versions of rover-agent' })
    expect(screen.getByRole('heading', { name: 'rover-agent' })).toBeInTheDocument()
    expect(screen.getByText('2 distinct versions across 3 of 5 minions')).toBeInTheDocument()
    expect(within(versions).getAllByRole('button').map((row) => row.textContent)).toEqual([
      '2.4.12 · 40%',
      '2.3.01 · 20%',
      'Not installed1 · 20%',
      'Unknown (no answer yet, or the last answer was cut short)1 · 20%',
    ])

    await user.click(within(versions).getByRole('button', { name: /2\.4\.1/ }))
    expect(within(versions).getByRole('link', { name: 'Run on these' })).toHaveAttribute(
      'href',
      '/run?target=rover-01%2Crover-02&type=list',
    )
    expect(within(versions).getByRole('link', { name: 'rover-02' })).toHaveAttribute('href', '/minions/rover-02')

    const footer = screen.getByRole('button', { name: 'Ask now' }).parentElement!
    expect(footer).toHaveTextContent('Read between 3h and 20m ago')
    expect(within(footer).getByText('3h')).toHaveAttribute('title', expect.stringContaining('UTC'))
    expect(within(footer).getByText('20m ago')).toHaveAttribute('title', expect.stringContaining('UTC'))

    const changes = await screen.findByRole('list', { name: 'Changes to rover-agent' })
    const [byJob, byPerson, between, appeared] = within(changes).getAllByRole('listitem')
    expect(byJob).toHaveTextContent('20m ago rover-01 2.3.0 → 2.4.1 found after job 20261020114000000001 by alice@example.com')
    expect(within(byJob!).getByRole('link', { name: '20261020114000000001' })).toHaveAttribute(
      'href',
      '/jobs/20261020114000000001',
    )
    expect(within(byJob!).getByText('20m ago')).toHaveAttribute('title', expect.stringContaining('UTC'))
    expect(byPerson).toHaveTextContent('1h ago rover-02 2.3.0 → 2.4.1 found after jobs by bob@example.com')
    expect(between).toHaveTextContent('2h ago rover-03 2.3.0 (removed) sometime between 8h and 2h ago')
    expect(appeared).toHaveTextContent('5h ago dock-01 2.3.0 (new) found after job 20261020070000000002')
    expect(appeared).not.toHaveTextContent(/ by /)
  })

  it('asks the whole fleet now and says what happens next', async () => {
    const user = userEvent.setup()
    const bodies: unknown[] = []
    api({
      '/api/inventory/ask': (_url: URL, init?: RequestInit) => {
        bodies.push({ method: init?.method, body: JSON.parse(String(init?.body)) })
        return { asked: ['dock-01', 'rover-01', 'rover-02'], queued: true, failed: {}, reason: null }
      },
    })
    renderApp('/?tab=grains&grain=@packages:rover-agent')
    await user.click(await screen.findByRole('button', { name: 'Ask now' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Reading 3 minions over the next minute; answers appear as they arrive.',
    )
    expect(bodies).toEqual([{ method: 'POST', body: { minion: null } }])
  })

  it('says why nobody was asked, what failed, and what the server refused', async () => {
    const user = userEvent.setup()
    const answers: unknown[] = [
      { asked: [], queued: false, failed: {}, reason: 'no minions are online' },
      { asked: ['rover-01'], queued: false, failed: { containers: 'salt-api answered 403' }, reason: null },
      new Response(JSON.stringify({ detail: 'Asked a moment ago; try again in a minute.' }), { status: 429 }),
    ]
    api({ '/api/inventory/ask': () => answers.shift() })
    renderApp('/?tab=grains&grain=@packages:rover-agent')
    const ask = await screen.findByRole('button', { name: 'Ask now' })

    await user.click(ask)
    expect(await screen.findByRole('status')).toHaveTextContent('Nobody was asked: no minions are online.')
    await user.click(ask)
    expect(await screen.findByText('Asked 1 minion; answers appear as they arrive.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent("Couldn't ask for the containers check: salt-api answered 403")
    await user.click(ask)
    expect(await screen.findByRole('alert')).toHaveTextContent('Asked a moment ago; try again in a minute.')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it("explains a check salt-api won't let brine read, in a check's words", async () => {
    const user = userEvent.setup()
    api({
      '/api/auth/me': VIEWER,
      '/api/inventory/values': {
        key: '@containers:web',
        source: 'containers',
        name: 'web',
        kind: 'check',
        total: 5,
        values: [{ value: 'ghcr.io/acme/web:1.4', text: 'ghcr.io/acme/web:1.4', minions: ['rover-01'] }],
        missing: ['dock-01', 'rover-02', 'rover-03', 'rover-04'],
        unknown: [],
        oldest_read_at: ago(2 * 3600),
        newest_read_at: ago(2 * 3600),
        refused: "salt-api answered 403: brine's account may not run cmd.run_all",
      } satisfies InventoryDistribution,
      '/api/inventory/changes': [],
    })
    renderApp('/?tab=grains&grain=@containers:web')

    const banner = (await screen.findByText("brine can't read the containers check")).parentElement!
    expect(banner).toHaveTextContent(
      "salt-api answered 403: brine's account may not run cmd.run_all. Settings › Packages and checks has the lines to add to brine's Salt account.",
    )
    expect(within(banner).getByRole('link', { name: 'Settings › Packages and checks' })).toHaveAttribute('href', '/settings')

    expect(screen.getByRole('heading', { name: 'web' })).toBeInTheDocument()
    expect(screen.getByText('From the containers check · 1 distinct value across 1 of 5 minions')).toBeInTheDocument()
    const values = screen.getByRole('list', { name: 'Values of web' })
    expect(within(values).getByText('Nothing reported')).toBeInTheDocument()
    expect(within(values).queryByText(/Unknown/)).toBeNull() // no row when nobody is unknown
    await user.click(within(values).getByRole('button', { name: /ghcr\.io/ }))
    expect(within(values).getByRole('link', { name: 'rover-01' })).toBeInTheDocument()
    expect(within(values).queryByRole('link', { name: 'Run on these' })).toBeNull() // viewers can't run commands

    expect(screen.getByRole('button', { name: 'Ask now' }).parentElement).toHaveTextContent('Read 2h ago')
    expect(await screen.findByText('No changes since brine first looked.')).toBeInTheDocument()
  })
})
