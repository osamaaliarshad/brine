import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Settings } from '@/api/types'
import { mockApi, renderApp, systemStatus } from '@/test/render'

const SETTINGS: Settings = {
  version: '0.1.0',
  salt_api: { url: 'http://127.0.0.1:8001/', username: 'brine', eauth: 'pam', verify_tls: true, timeout_seconds: 10 },
  presence: { method: 'auto', active_method: 'events', poll_seconds: 60 },
  fleet: { stale_after_minutes: 15, grains_refresh_minutes: 30, columns: [{ grain: 'site', label: 'Site' }] },
  jobs_backfill_limit: 200,
  retention: { jobs_days: 90, history_days: 90, audit_days: 0 },
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
  inventory: { refresh_hours: 6, checks: [], acl: "- '*':\n  - pkg.list_pkgs$\n", refused: {} },
}

const INVENTORY: Settings['inventory'] = {
  refresh_hours: 6,
  checks: [
    { name: 'rover-cli', command: '/opt/rover/bin/rover-cli --version' },
    { name: 'containers', command: "podman ps --format '{{.Names}}={{.Image}}'" },
  ],
  acl: [
    "- '*':",
    '  - pkg.list_pkgs$',
    '  - cmd.run_all$:',
    '      args:',
    "        - '^/opt/rover/bin/rover\\-cli\\ \\-\\-version$'",
    '',
  ].join('\n'),
  refused: {},
}

describe('SettingsPage', () => {
  it('shows the running configuration', async () => {
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings')
    expect(await screen.findByText('http://127.0.0.1:8001/')).toBeInTheDocument()
    expect(screen.getByText('· currently events')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('sqlite:///data/brine.db')).toBeInTheDocument()
    expect(screen.getByText('jobs 90 days · presence, grains and packages 90 days · audit log forever')).toBeInTheDocument()
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

  it('shows what brine reads from each minion, and the Salt permissions it needs', async () => {
    mockApi({ '/api/settings': { ...SETTINGS, inventory: INVENTORY }, '/api/status': systemStatus() })
    renderApp('/settings')
    const section = await screen.findByRole('region', { name: 'Packages and checks' })
    expect(section).toHaveAttribute('id', 'packages-and-checks')
    expect(
      within(section).getByText("Read every 6 hours, after people's jobs, when a minion comes back, and on Read now"),
    ).toBeInTheDocument()
    expect(within(section).getByText('rover-cli: /opt/rover/bin/rover-cli --version')).toHaveClass('font-mono')
    expect(within(section).getByText("containers: podman ps --format '{{.Names}}={{.Image}}'")).toHaveClass('font-mono')
    expect(
      within(section).getByText(
        'Commands are sent exactly as written and shown to everyone signed in; keep secrets out of them.',
      ),
    ).toBeInTheDocument()

    // Nothing refused: the permissions are there to look at, folded away.
    const permissions = within(section).getByText('Salt permissions brine needs').closest('details')!
    expect(permissions).not.toHaveAttribute('open')
    expect(permissions.querySelector('pre')?.textContent).toBe(INVENTORY.acl)
    expect(
      within(permissions).getByText("Add these under external_auth › pam › brine in the master's config."),
    ).toBeInTheDocument()
    expect(within(section).queryByText(/can't read/)).toBeNull()
  })

  it('opens the permissions and says what Salt refused', async () => {
    mockApi({
      '/api/settings': {
        ...SETTINGS,
        inventory: {
          ...INVENTORY,
          refused: {
            // A reason's own full stop isn't doubled up or left dangling.
            packages: "brine's Salt account isn't allowed to run pkg.list_pkgs.",
            containers: "brine's Salt account isn't allowed to run cmd.run_all",
          },
        },
      },
      '/api/status': systemStatus(),
    })
    renderApp('/settings')
    const section = await screen.findByRole('region', { name: 'Packages and checks' })
    expect(within(section).getByText('Salt permissions brine needs').closest('details')).toHaveAttribute('open')
    expect(
      within(section).getByText("brine can't read packages: brine's Salt account isn't allowed to run pkg.list_pkgs"),
    ).toBeInTheDocument()
    expect(
      within(section).getByText(
        "brine can't read the containers check: brine's Salt account isn't allowed to run cmd.run_all",
      ),
    ).toBeInTheDocument()
  })

  it('shows the page whatever follows the # in a link', async () => {
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings#%E0%A4%A') // not valid percent-encoding
    expect(await screen.findByRole('region', { name: 'Packages and checks' })).toBeInTheDocument()
  })

  it('says how to add checks when there are none', async () => {
    mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
    renderApp('/settings')
    const section = await screen.findByRole('region', { name: 'Packages and checks' })
    expect(within(section).getByText('None, so brine reads only packages. Add checks under inventory › checks in the config.')).toBeInTheDocument()
    expect(within(section).queryByText(/keep secrets out/)).toBeNull()
  })

  it('scrolls to a section a link points at', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    try {
      mockApi({ '/api/settings': SETTINGS, '/api/status': systemStatus() })
      renderApp('/settings#packages-and-checks')
      const section = await screen.findByRole('region', { name: 'Packages and checks' })
      await waitFor(() => expect(scroll).toHaveBeenCalled())
      expect(scroll.mock.contexts[0]).toBe(section)
    } finally {
      // @ts-expect-error -- jsdom doesn't have it; take the stub away again.
      delete Element.prototype.scrollIntoView
    }
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
