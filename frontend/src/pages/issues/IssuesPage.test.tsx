import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Issue } from '@/api/types'
import { ago, fleet, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const ISSUES: Issue[] = [
  { key: 'state:dock-01', severity: 'critical', title: 'dock-01: 1 state failed', detail: 'In its latest state.apply.', since: ago(300), minion_id: 'dock-01', jid: '123' },
  { key: 'key:rover-04', severity: 'warning', title: 'rover-04 is waiting for key approval', detail: '', since: ago(3600), minion_id: 'rover-04', jid: null },
  { key: 'version:rover-02', severity: 'info', title: 'rover-02 runs Salt 3006.9', detail: 'Most of the fleet runs 3006.28.', since: null, minion_id: 'rover-02', jid: null },
]

describe('IssuesPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('lists issues with severity, age, and links', async () => {
    mockApi({ '/api/issues': ISSUES, '/api/status': systemStatus() })
    renderApp('/issues')
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(3)
    const critical = items[0]!
    expect(within(critical).getByLabelText('Critical')).toBeInTheDocument()
    expect(within(critical).getByText('5m ago')).toBeInTheDocument()
    expect(within(critical).getByRole('link', { name: 'View job' })).toHaveAttribute('href', '/jobs/123')
    expect(within(critical).getByRole('link', { name: 'Open dock-01' })).toHaveAttribute('href', '/minions/dock-01')
  })

  it('sends pending keys to the Keys page', async () => {
    mockApi({ '/api/issues': ISSUES, '/api/status': systemStatus() })
    renderApp('/issues')
    const link = await screen.findByRole('link', { name: 'Review on the Keys page' })
    expect(link).toHaveAttribute('href', '/keys?state=pending')
  })

  it("sends a package or check brine can't read to Settings", async () => {
    const refused: Issue = {
      key: 'inventory:packages',
      severity: 'warning',
      title: "brine can't read packages",
      detail: "brine's Salt account isn't allowed to run pkg.list_pkgs. Settings › Packages and checks has the lines to add to brine's Salt account.",
      since: null,
      minion_id: null,
      jid: null,
    }
    mockApi({ '/api/issues': [refused], '/api/status': systemStatus() })
    renderApp('/issues')
    const link = await screen.findByRole('link', { name: 'Open Settings › Packages and checks' })
    expect(link).toHaveAttribute('href', '/settings#packages-and-checks')
  })

  it('filters by severity', async () => {
    const user = userEvent.setup()
    mockApi({ '/api/issues': ISSUES, '/api/status': systemStatus() })
    renderApp('/issues')
    await user.click(await screen.findByRole('tab', { name: /Info/ }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('rover-02 runs Salt 3006.9')).toBeInTheDocument()
  })

  it('celebrates an empty list', async () => {
    mockApi({ '/api/issues': [], '/api/status': systemStatus() })
    renderApp('/issues')
    expect(await screen.findByText('All clear')).toBeInTheDocument()
  })

  it('feeds the fleet card and the sidebar badge (critical + warning only)', async () => {
    mockApi({ '/api/issues': ISSUES, '/api/fleet': fleet([minion('a')]), '/api/status': systemStatus() })
    renderApp('/')
    expect(await screen.findByLabelText('2 need attention')).toBeInTheDocument()
    const card = screen.getByRole('link', { name: 'Need attention: see issues' })
    expect(card).toHaveTextContent('2')
  })
})
