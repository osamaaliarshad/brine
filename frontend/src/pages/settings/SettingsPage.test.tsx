import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Settings } from '@/api/types'
import { mockApi, renderApp, systemStatus } from '@/test/render'

const SETTINGS: Settings = {
  version: '0.1.0',
  salt_api: { url: 'http://127.0.0.1:8001/', username: 'brine', eauth: 'pam', verify_tls: true, timeout_seconds: 10 },
  presence: { method: 'auto', active_method: 'events', poll_seconds: 60 },
  fleet: { stale_after_minutes: 15, grains_refresh_minutes: 30, columns: [{ grain: 'site', label: 'Site' }] },
  jobs_backfill_limit: 200,
  database: { backend: 'sqlite', url: 'sqlite:///data/brine.db' },
  auth: {
    provider: 'oidc',
    issuer: 'https://accounts.google.com',
    display_name: 'Google',
    configured: true,
    allowed_domains: ['example.com'],
    anonymous_role: 'viewer',
    session_hours: 12,
    role_patterns: { viewer: 3, operator: 0, admin: 1 },
  },
}

describe('SettingsPage', () => {
  it('shows the running configuration', async () => {
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings')
    expect(await screen.findByText('http://127.0.0.1:8001/')).toBeInTheDocument()
    expect(screen.getByText('· currently events')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('sqlite:///data/brine.db')).toBeInTheDocument()
  })

  it('explains sign-in without listing who holds which role', async () => {
    mockApi({
      '/api/settings': SETTINGS,
      '/api/status': systemStatus(),
      '/api/auth/me': { email: 'a@example.com', name: 'A', picture: null, role: 'admin', provider: 'oidc' },
    })
    renderApp('/settings')
    expect(await screen.findByText('https://accounts.google.com')).toBeInTheDocument()
    expect(screen.getByText('Admin: 1 · Viewer: 3')).toBeInTheDocument()
    expect(screen.getByText('example.com')).toBeInTheDocument()
    expect(await screen.findByText('a@example.com · Admin')).toBeInTheDocument()
  })

  it('warns plainly when sign-in is off', async () => {
    mockApi({
      '/api/settings': { ...SETTINGS, auth: { ...SETTINGS.auth, provider: 'none', anonymous_role: 'admin' } },
      '/api/status': systemStatus(),
    })
    renderApp('/settings')
    const off = await screen.findByText('Off')
    expect(off.parentElement).toHaveTextContent('Off: everyone is treated as Admin')
  })

  it('switches theme, including following the system', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings')
    await user.click(screen.getByRole('radio', { name: 'Light' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('brine-theme')).toBe('light')
    // The sidebar toggle follows along.
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'System' }))
    expect(localStorage.getItem('brine-theme')).toBeNull()
  })

  it('resets customised fleet columns', async () => {
    const user = userEvent.setup()
    localStorage.setItem('brine-fleet-columns', JSON.stringify({ grains: ['osfinger'], hidden: [] }))
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings')
    expect(screen.getByText('osfinger')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reset to team default' }))
    expect(screen.getByText('Team default')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('brine-fleet-columns')!).grains).toBeNull()
  })
})
