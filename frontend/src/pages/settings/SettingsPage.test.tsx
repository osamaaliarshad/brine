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
  auth: { provider: 'oidc', issuer: null, configured: false },
}

describe('SettingsPage', () => {
  it('shows the running configuration', async () => {
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings')
    expect(await screen.findByText('http://127.0.0.1:8001/')).toBeInTheDocument()
    expect(screen.getByText('· currently events')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('sqlite:///data/brine.db')).toBeInTheDocument()
    expect(screen.getByText('Not configured yet')).toBeInTheDocument()
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
