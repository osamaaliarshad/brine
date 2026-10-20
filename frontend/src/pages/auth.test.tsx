import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { User } from '@/api/types'
import { initials } from '@/lib/initials'
import { unauthorized } from '@/test/setup'
import { fleet, mockApi, renderApp, systemStatus } from '@/test/render'

const ADMIN: User = { email: 'osama@example.com', name: 'Osama Arshad', picture: null, role: 'admin', provider: 'oidc' }
const VIEWER: User = { ...ADMIN, email: 'v@example.com', name: 'Val Viewer', role: 'viewer' }
const ANON: User = { email: 'local', name: 'Local user', picture: null, role: 'admin', provider: 'none' }

describe('sign-in page', () => {
  it('offers the configured provider and keeps where you were going', async () => {
    mockApi({ '/api/auth/info': { provider: 'oidc', display_name: 'Google' } })
    renderApp('/login?next=%2Fjobs%3Ftab%3Dstates')
    const button = await screen.findByRole('link', { name: 'Sign in with Google' })
    expect(button).toHaveAttribute('href', '/api/auth/login?next=%2Fjobs%3Ftab%3Dstates')
  })

  it('explains a refused account', async () => {
    mockApi({ '/api/auth/info': { provider: 'oidc', display_name: 'Google' } })
    renderApp('/login?error=denied')
    expect(await screen.findByRole('alert')).toHaveTextContent("doesn't have access")
  })

  it('never sends you off-site after sign-in', async () => {
    mockApi({ '/api/auth/info': { provider: 'oidc', display_name: 'Google' } })
    renderApp('/login?next=%2F%2Fevil.example.com')
    expect(await screen.findByRole('link', { name: 'Sign in with Google' })).toHaveAttribute(
      'href',
      '/api/auth/login?next=%2F',
    )
  })

  it('skips itself when sign-in is off', async () => {
    mockApi({ '/api/auth/info': { provider: 'none', display_name: 'single sign-on' }, '/api/fleet': fleet([]), '/api/status': systemStatus() })
    const { router } = renderApp('/login?next=%2Fkeys')
    await screen.findByRole('heading', { name: 'Keys' })
    expect(router.state.location.pathname).toBe('/keys')
  })
})

describe('signed in', () => {
  it('shows who you are at the bottom of the sidebar', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/auth/me': ADMIN, '/api/fleet': fleet([]), '/api/status': systemStatus() })
    renderApp('/')
    const account = await screen.findAllByRole('button', { name: 'Account: Osama Arshad' })
    expect(account[0]).toHaveTextContent('OA')
    await user.click(account[0]!)
    const menu = screen.getByRole('menu')
    expect(within(menu).getByText('osama@example.com')).toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('shows the audit log to admins only', async () => {
    mockApi({ '/api/auth/me': VIEWER, '/api/fleet': fleet([]), '/api/status': systemStatus() })
    renderApp('/')
    await screen.findAllByRole('button', { name: 'Account: Val Viewer' })
    expect(screen.queryByRole('link', { name: 'Audit log' })).toBeNull()
  })

  it('sends you to sign in when the session is gone', async () => {
    mockApi({
      '/api/fleet': () => new Response(JSON.stringify({ detail: 'sign in first' }), { status: 401 }),
      '/api/status': systemStatus(),
    })
    renderApp('/')
    await screen.findByText(/Couldn't load the fleet/)
    expect(unauthorized).toHaveBeenCalled()
  })

  it('warns when sign-in is off', async () => {
    mockApi({ '/api/auth/me': ANON, '/api/fleet': fleet([]), '/api/status': systemStatus() })
    renderApp('/')
    expect(await screen.findByRole('note')).toHaveTextContent('Sign-in is off')
    expect(screen.getByRole('note')).toHaveTextContent('treated as admin')
  })
})

describe('audit log page', () => {
  it('lists entries in plain words', async () => {
    mockApi({
      '/api/auth/me': ADMIN,
      '/api/status': systemStatus(),
      '/api/audit': {
        entries: [
          { id: 3, at: '2026-10-20T12:00:00Z', actor: 'stranger@gmail.com', action: 'auth.login_denied', target: null, detail: { reason: 'no role', ip: '10.0.0.9' } },
          { id: 2, at: '2026-10-20T11:00:00Z', actor: 'osama@example.com', action: 'pillar.view', target: 'rover-01', detail: null },
          { id: 1, at: '2026-10-20T10:00:00Z', actor: 'osama@example.com', action: 'auth.login', target: null, detail: { role: 'admin' } },
        ],
        next_before: null,
      },
    })
    renderApp('/audit')
    expect(await screen.findByText('Sign-in refused')).toHaveClass('text-danger')
    expect(screen.getByText('reason: no role · ip: 10.0.0.9')).toBeInTheDocument()
    expect(screen.getByText('Viewed pillar')).toBeInTheDocument()
    expect(screen.getByText('· rover-01')).toBeInTheDocument()
  })
})

describe('initials', () => {
  it.each([
    ['Osama Arshad', 'OA'],
    ['jane.doe@example.com', 'JD'],
    ['cher', 'C'],
    ['', '?'],
  ])('%s -> %s', (name, expected) => {
    expect(initials(name)).toBe(expected)
  })
})
