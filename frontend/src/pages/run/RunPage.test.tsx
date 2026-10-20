import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Capabilities, CommandPreview, User } from '@/api/types'
import { mockApi, renderApp, systemStatus } from '@/test/render'

const OPERATOR: User = { email: 'o@example.com', name: 'Otto Operator', picture: null, role: 'operator', provider: 'oidc' }
const CAPS: Capabilities = { manage_keys: { allowed: true, missing: [] }, commands: ['test.*', 'runners.manage.*'] }

const PREVIEW: CommandPreview = {
  client: 'local',
  fun: 'test.ping',
  qualified: 'test.ping',
  args: [],
  minions: ['rover-01', 'rover-02', 'rover-03'],
  offline: ['rover-03'],
  unknown: [],
  from_cache: false,
}

type Sent = { path: string; body: Record<string, unknown> }

function api(extra: Record<string, unknown> = {}) {
  const sent: Sent[] = []
  const record = (answer: unknown) => (url: URL, init?: RequestInit) => {
    sent.push({ path: url.pathname, body: JSON.parse(String(init?.body)) as Record<string, unknown> })
    return typeof answer === 'function' ? (answer as () => unknown)() : answer
  }
  mockApi({
    '/api/auth/me': OPERATOR,
    '/api/status': systemStatus(),
    '/api/capabilities': CAPS,
    '/api/commands/preview': record(PREVIEW),
    '/api/commands/run': record({ client: 'local', jid: '20261020120000000001', minions: PREVIEW.minions, result: null, success: null }),
    ...Object.fromEntries(Object.entries(extra).map(([k, v]) => [k, k.startsWith('/api/commands/') ? record(v) : v])),
  })
  return sent
}

describe('RunPage', () => {
  it('previews where a command runs, then runs exactly that', async () => {
    const user = userEvent.setup()
    const sent = api()
    const { router } = renderApp('/run')
    await user.type(await screen.findByRole('textbox', { name: 'Target' }), 'rover-0*')
    await user.type(screen.getByRole('textbox', { name: 'Command' }), 'test.ping{Enter}')

    expect(await screen.findByText(/Runs/)).toHaveTextContent('Runs test.ping on 3 minions (1 offline')
    const chips = within(screen.getByRole('list', { name: 'Minions it runs on' })).getAllByRole('listitem')
    expect(chips.map((c) => c.textContent)).toEqual(['rover-01', 'rover-02', 'rover-03'])
    expect(chips[2]).toHaveAttribute('title', 'Offline')
    expect(sent).toEqual([
      { path: '/api/commands/preview', body: { command: 'test.ping', target: 'rover-0*', target_type: 'glob' } },
    ])

    await user.click(screen.getByRole('button', { name: 'Run on 3 minions' }))
    expect(sent[1]).toEqual({
      path: '/api/commands/run',
      body: { command: 'test.ping', target: 'rover-0*', target_type: 'glob', expect: PREVIEW.minions },
    })
    expect(router.state.location.pathname).toBe('/jobs/20261020120000000001')
    expect(JSON.parse(localStorage.getItem('brine-command-history')!)).toEqual([
      { command: 'test.ping', target: 'rover-0*', target_type: 'glob' },
    ])
  })

  it('forgets the preview as soon as you edit', async () => {
    const user = userEvent.setup()
    api()
    renderApp('/run?target=rover-01&type=list')
    expect(await screen.findByRole('textbox', { name: 'Target' })).toHaveValue('rover-01')
    expect(screen.getByRole('combobox', { name: 'Target type' })).toHaveValue('list')
    await user.type(screen.getByRole('textbox', { name: 'Command' }), 'test.ping{Enter}')
    expect(await screen.findByRole('button', { name: /Run on/ })).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: 'Command' }), ' extra')
    expect(screen.queryByRole('button', { name: /Run on/ })).toBeNull()
  })

  it('opens a shared link already previewed, without running it', async () => {
    const sent = api()
    renderApp('/run?target=rover-0*&command=test.ping')
    expect(await screen.findByRole('button', { name: 'Run on 3 minions' })).toBeInTheDocument()
    expect(sent.map((s) => s.path)).toEqual(['/api/commands/preview'])
  })

  it('runs master commands without a target and shows the answer', async () => {
    const user = userEvent.setup()
    const sent = api({
      '/api/commands/preview': { ...PREVIEW, client: 'runner', fun: 'manage.status', qualified: 'runners.manage.status', minions: [], offline: [] },
      '/api/commands/run': { client: 'runner', jid: null, minions: [], result: { up: ['rover-01'] }, success: null },
    })
    renderApp('/run')
    await user.type(await screen.findByRole('textbox', { name: 'Command' }), 'runners.manage.status{Enter}')
    expect(screen.getByRole('textbox', { name: 'Target' })).toBeDisabled()
    expect(await screen.findByText(/^Runs/)).toHaveTextContent('Runs runners.manage.status on the master.')
    await user.click(screen.getByRole('button', { name: 'Run on the master' }))
    expect(await screen.findByRole('heading', { name: 'Result' })).toBeInTheDocument()
    expect(screen.getByText('rover-01')).toBeInTheDocument()
    expect(sent[0]!.body.target).toBe('')
  })

  it('says why a command is refused', async () => {
    const user = userEvent.setup()
    api({
      '/api/commands/preview': () =>
        new Response(JSON.stringify({ detail: "The operator role can't run cmd.run." }), { status: 403 }),
    })
    renderApp('/run')
    await user.type(await screen.findByRole('textbox', { name: 'Target' }), '*')
    await user.type(screen.getByRole('textbox', { name: 'Command' }), 'cmd.run reboot{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent("The operator role can't run cmd.run.")
    expect(screen.queryByRole('button', { name: /Run on/ })).toBeNull()
  })

  it('shows operators what they may run, and puts Run in the sidebar', async () => {
    api()
    renderApp('/run')
    expect(await screen.findByText('You can run:')).toBeInTheDocument()
    expect(screen.getByText('test.*')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Run' })[0]).toHaveAttribute('href', '/run')
  })

  it('refills a recent command', async () => {
    const user = userEvent.setup()
    localStorage.setItem(
      'brine-command-history',
      JSON.stringify([{ command: 'test.version', target: 'dock-*', target_type: 'glob' }]),
    )
    api()
    renderApp('/run')
    await user.click(await screen.findByRole('button', { name: /test\.version/ }))
    expect(screen.getByRole('textbox', { name: 'Command' })).toHaveValue('test.version')
    expect(screen.getByRole('textbox', { name: 'Target' })).toHaveValue('dock-*')
  })

  it('tells viewers they cannot run commands', async () => {
    api({ '/api/auth/me': { ...OPERATOR, role: 'viewer' }, '/api/capabilities': { ...CAPS, commands: [] } })
    renderApp('/run')
    expect(await screen.findByText(/Your role can't run commands in brine/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Run' })).toBeNull()
  })
})
