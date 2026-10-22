import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Issue } from '@/api/types'
import { ago, fleet, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const ISSUES: Issue[] = [
  { key: 'state:dock-01', severity: 'critical', title: 'dock-01: 1 state failed', detail: 'In its latest state.apply.', since: ago(300), minion_id: 'dock-01', jid: '123', fingerprint: 'f1', read: false },
  { key: 'key:rover-04', severity: 'warning', title: 'rover-04 is waiting for key approval', detail: '', since: ago(3600), minion_id: 'rover-04', jid: null, fingerprint: 'f2', read: false },
  { key: 'version:rover-02', severity: 'info', title: 'rover-02 runs Salt 3006.9', detail: 'Most of the fleet runs 3006.28.', since: null, minion_id: 'rover-02', jid: null, fingerprint: 'f3', read: false },
]

/** A server that remembers what was marked read, and every write's body. */
function issuesServer(initial: Issue[]) {
  let issues = initial
  const writes: { path: string; body: unknown }[] = []
  const write = (url: URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { issues?: { key: string }[]; keys?: string[] }
    writes.push({ path: url.pathname, body })
    const read = url.pathname.endsWith('/read')
    const keys = new Set(read ? body.issues!.map((i) => i.key) : body.keys)
    issues = issues.map((i) => (keys.has(i.key) ? { ...i, read } : i))
    return new Response(null, { status: 204 })
  }
  const fetchMock = mockApi({
    '/api/issues': () => issues,
    '/api/issues/read': write,
    '/api/issues/unread': write,
    '/api/status': systemStatus(),
  })
  return { fetchMock, writes }
}

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
    expect(within(critical).getByRole('button', { name: 'Mark as read' })).toHaveAccessibleDescription(
      'dock-01: 1 state failed',
    )
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
      fingerprint: 'f4',
      read: false,
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
    expect(screen.queryByRole('button', { name: /Mark all/ })).not.toBeInTheDocument()
  })

  it('marks an issue as read, as the page showed it, and hides it', async () => {
    const user = userEvent.setup()
    const { writes } = issuesServer(ISSUES)
    renderApp('/issues')
    const row = (await screen.findAllByRole('listitem'))[1]!
    await user.click(within(row).getByRole('button', { name: 'Mark as read' }))
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    expect(screen.queryByText('rover-04 is waiting for key approval')).not.toBeInTheDocument()
    expect(writes).toEqual([{ path: '/api/issues/read', body: { issues: [{ key: 'key:rover-04', fingerprint: 'f2' }] } }])
    expect(screen.getByRole('tab', { name: /Warning/ })).toHaveTextContent('0')
    expect(screen.getByRole('button', { name: 'Show 1 read' })).toBeInTheDocument()
  })

  it('keeps keyboard focus in the list when a row leaves it', async () => {
    const user = userEvent.setup()
    issuesServer(ISSUES)
    renderApp('/issues')
    const [first, second] = await screen.findAllByRole('button', { name: 'Mark as read' })
    first!.focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    expect(second).toHaveFocus()
  })

  it('shows read issues on request, muted, to mark as unread', async () => {
    const user = userEvent.setup()
    const { writes } = issuesServer(ISSUES.map((i) => (i.severity === 'critical' ? { ...i, read: true } : i)))
    renderApp('/issues')
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('tab', { name: /All/ })).toHaveTextContent('2')

    await user.click(screen.getByRole('button', { name: 'Show 1 read' }))
    const read = screen.getByRole('list', { name: 'Read issues' })
    expect(within(read).getByText('dock-01: 1 state failed')).toHaveClass('text-muted')
    await user.click(within(read).getByRole('button', { name: 'Mark as unread' }))
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Read issues' })).not.toBeInTheDocument())
    expect(writes).toEqual([{ path: '/api/issues/unread', body: { keys: ['state:dock-01'] } }])
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
  })

  it('marks all as read, and says how many are hidden', async () => {
    const user = userEvent.setup()
    const { writes } = issuesServer(ISSUES)
    renderApp('/issues')
    await user.click(await screen.findByRole('button', { name: 'Mark all as read' }))
    expect(await screen.findByText('Nothing new')).toBeInTheDocument()
    expect(screen.getByText('3 read issues hidden.')).toBeInTheDocument()
    expect(writes[0]!.body).toEqual({ issues: ISSUES.map(({ key, fingerprint }) => ({ key, fingerprint })) })
    expect(screen.queryByRole('button', { name: /Mark all/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show 3 read' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Show 3 read' }))
    expect(within(screen.getByRole('list', { name: 'Read issues' })).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.queryByText('3 read issues hidden.')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Hide read' }))
    expect(screen.queryByRole('list', { name: 'Read issues' })).not.toBeInTheDocument()
  })

  it('marks all at one level as read', async () => {
    const user = userEvent.setup()
    const { writes } = issuesServer(ISSUES)
    renderApp('/issues?severity=info')
    await user.click(await screen.findByRole('button', { name: 'Mark all info as read' }))
    await waitFor(() => expect(writes).toHaveLength(1))
    expect(writes[0]!.body).toEqual({ issues: [{ key: 'version:rover-02', fingerprint: 'f3' }] })
    await user.click(screen.getByRole('tab', { name: /All/ }))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it("says so when marking doesn't work, and shows the issue again", async () => {
    const user = userEvent.setup()
    mockApi({
      '/api/issues': ISSUES,
      '/api/issues/read': new Response(JSON.stringify({ detail: 'database is locked' }), { status: 500 }),
      '/api/status': systemStatus(),
    })
    renderApp('/issues')
    const row = (await screen.findAllByRole('listitem'))[0]!
    await user.click(within(row).getByRole('button', { name: 'Mark as read' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't mark it as read: database is locked")
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
  })

  it('feeds the fleet card and the sidebar badge (critical + warning only)', async () => {
    mockApi({ '/api/issues': ISSUES, '/api/fleet': fleet([minion('a')]), '/api/status': systemStatus() })
    renderApp('/')
    expect(await screen.findByLabelText('2 need attention')).toBeInTheDocument()
    const card = screen.getByRole('link', { name: 'Need attention: see issues' })
    expect(card).toHaveTextContent('2')
  })

  it('leaves issues marked as read out of the fleet card and the sidebar badge', async () => {
    const issues = ISSUES.map((i) => (i.severity === 'warning' ? { ...i, read: true } : i))
    mockApi({ '/api/issues': issues, '/api/fleet': fleet([minion('a')]), '/api/status': systemStatus() })
    renderApp('/')
    expect(await screen.findByLabelText('1 need attention')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Need attention: see issues' })).toHaveTextContent('1')
  })
})
