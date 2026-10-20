import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Capabilities, Key, MinionDetail, User } from '@/api/types'
import { ago, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const ADMIN: User = { email: 'a@example.com', name: 'Ada Admin', picture: null, role: 'admin', provider: 'oidc' }
const VIEWER: User = { ...ADMIN, name: 'Val Viewer', role: 'viewer' }
const ALLOWED: Capabilities = { manage_keys: { allowed: true, missing: [] } }

const KEYS: Key[] = [
  { id: 'rover-01', key_state: 'accepted', fingerprint: 'aa:01', first_seen_at: ago(86400), last_seen_at: ago(5), status: 'online' },
  { id: 'rover-04', key_state: 'pending', fingerprint: 'ff:ee:dd', first_seen_at: ago(1200), last_seen_at: null, status: null },
]

type Sent = { path: string; body: unknown; headers: Record<string, string> }

/** The usual API, plus key actions that record what was sent and answer `answer`. */
function api(user: User, extra: Record<string, unknown> = {}, answer?: (path: string) => unknown) {
  const sent: Sent[] = []
  const action = (url: URL, init?: RequestInit) => {
    sent.push({
      path: url.pathname,
      body: JSON.parse(String(init?.body)),
      headers: init?.headers as Record<string, string>,
    })
    const [, , , id, verb] = url.pathname.split('/')
    return answer?.(url.pathname) ?? { id, key_state: { accept: 'accepted', reject: 'rejected', delete: 'deleted' }[verb!] }
  }
  mockApi({
    '/api/auth/me': user,
    '/api/keys': KEYS,
    '/api/status': systemStatus(),
    '/api/capabilities': ALLOWED,
    '/api/keys/rover-04/accept': action,
    '/api/keys/rover-01/delete': action,
    ...extra,
  })
  return sent
}

describe('key management', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('accepts a pending key after showing its fingerprint', async () => {
    const user = userEvent.setup()
    const sent = api(ADMIN)
    renderApp('/keys')
    await user.click(await screen.findByRole('button', { name: 'Accept rover-04' }))
    const dialog = screen.getByRole('dialog', { name: "Accept rover-04's key?" })
    expect(within(dialog).getByText('ff:ee:dd')).toBeInTheDocument()
    // Cancel has focus: Enter on a dialog that appeared mid-click shouldn't accept anything.
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Accept key' }))
    expect(await screen.findByRole('status')).toHaveTextContent("rover-04's key was accepted.")
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(sent).toEqual([
      {
        path: '/api/keys/rover-04/accept',
        body: { state: 'pending', fingerprint: 'ff:ee:dd' },
        headers: expect.objectContaining({ 'X-Requested-With': 'brine' }),
      },
    ])
  })

  it('deletes only after the name is typed', async () => {
    const user = userEvent.setup()
    const sent = api(ADMIN)
    renderApp('/keys')
    await user.click(await screen.findByRole('button', { name: 'More actions for rover-01' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete…' }))
    const dialog = screen.getByRole('dialog', { name: "Delete rover-01's key?" })
    expect(dialog).toHaveTextContent('stop salt-minion on it first')
    const confirm = within(dialog).getByRole('button', { name: 'Delete key' })
    const input = within(dialog).getByRole('textbox', { name: 'Type rover-01 to confirm' })
    expect(input).toHaveFocus()
    await user.type(input, 'rover-0')
    expect(confirm).toBeDisabled()
    await user.type(input, '1')
    await user.click(confirm)
    expect(await screen.findByRole('status')).toHaveTextContent("rover-01's key was deleted.")
    expect(sent.map((s) => s.body)).toEqual([{ state: 'accepted', confirm: 'rover-01' }])
  })

  it('shows why the server refused, and keeps the dialog open', async () => {
    const user = userEvent.setup()
    api(ADMIN, {}, () =>
      new Response(JSON.stringify({ detail: "rover-04's key changed since you looked" }), { status: 409 }),
    )
    renderApp('/keys')
    await user.click(await screen.findByRole('button', { name: 'Accept rover-04' }))
    await user.click(screen.getByRole('button', { name: 'Accept key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('changed since you looked')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it("explains what to add when Salt's ACL doesn't allow it", async () => {
    api(ADMIN, {
      '/api/capabilities': { manage_keys: { allowed: false, missing: ['key.accept_dict', 'key.delete_dict'] } },
    })
    renderApp('/keys')
    expect(await screen.findByText(/Key management is off/)).toHaveTextContent(
      "brine's Salt account isn't allowed to run key.accept_dict, key.delete_dict. Add them under @wheel",
    )
    expect(screen.queryByRole('button', { name: 'Accept rover-04' })).toBeNull()
  })

  it('offers nothing to non-admins', async () => {
    api(VIEWER)
    renderApp('/keys')
    expect(await screen.findByText(/Admins can accept, reject and delete keys/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept rover-04' })).toBeNull()
    expect(screen.queryByRole('button', { name: /More actions/ })).toBeNull()
  })

  it('deletes from the minion page and lands on Keys', async () => {
    const user = userEvent.setup()
    const detail: MinionDetail = {
      ...minion('rover-01'),
      first_seen_at: ago(86400),
      grains: {},
      presence_history: [],
      recent_jobs: [],
    }
    const sent = api(ADMIN, { '/api/minions/rover-01': detail })
    const { router } = renderApp('/minions/rover-01')
    await user.click(await screen.findByRole('button', { name: /Manage key/ }))
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['Reject…', 'Delete…'])
    await user.click(screen.getByRole('menuitem', { name: 'Delete…' }))
    await user.type(screen.getByRole('textbox'), 'rover-01')
    await user.click(screen.getByRole('button', { name: 'Delete key' }))
    expect(await screen.findByRole('status')).toHaveTextContent("rover-01's key was deleted.")
    expect(router.state.location.pathname).toBe('/keys')
    expect(sent).toHaveLength(1)
  })
})
