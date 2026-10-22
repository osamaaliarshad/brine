import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createLiveInvalidator } from '@/api/live'
import type { Issue } from '@/api/types'
import { ago, fleet, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const ISSUES: Issue[] = [
  { key: 'state:dock-01', severity: 'critical', title: 'dock-01: 1 state failed', detail: 'In its latest state.apply.', since: ago(300), minion_id: 'dock-01', jid: '123', fingerprint: 'f1', read: false },
  { key: 'key:rover-04', severity: 'warning', title: 'rover-04 is waiting for key approval', detail: '', since: ago(3600), minion_id: 'rover-04', jid: null, fingerprint: 'f2', read: false },
  { key: 'version:rover-02', severity: 'info', title: 'rover-02 runs Salt 3006.9', detail: 'Most of the fleet runs 3006.28.', since: null, minion_id: 'rover-02', jid: null, fingerprint: 'f3', read: false },
]

const MARK = /^Mark as read/
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

/**
 * A server that remembers what was marked read, and every write's body. `changed` issues have
 * changed since the page showed them, so marking them does nothing. `hold` keeps every answer
 * to a write back until `release()`.
 */
function issuesServer(initial: Issue[], { changed = [] as string[], hold = false } = {}) {
  let issues = initial
  const writes: { path: string; body: unknown }[] = []
  const waiting: (() => void)[] = []
  const write = (url: URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { issues?: { key: string }[]; keys?: string[] }
    writes.push({ path: url.pathname, body })
    const read = url.pathname.endsWith('/read')
    const keys = (read ? body.issues!.map((i) => i.key) : body.keys!).filter((k) => !changed.includes(k))
    const answer = () => {
      issues = issues.map((i) => (keys.includes(i.key) ? { ...i, read } : i))
      return read ? json({ marked: keys, changed: body.issues!.map((i) => i.key).filter((k) => changed.includes(k)) }) : new Response(null, { status: 204 })
    }
    return hold ? new Promise<Response>((resolve) => waiting.push(() => resolve(answer()))) : answer()
  }
  const fetchMock = mockApi({
    '/api/issues': () => issues,
    '/api/issues/read': write,
    '/api/issues/unread': write,
    '/api/status': systemStatus(),
  })
  const fetches = () => fetchMock.mock.calls.filter(([url]) => String(url) === '/api/issues').length
  const release = () => waiting.splice(0).forEach((answer) => answer())
  return { writes, fetches, release }
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
    // Its name says which issue: there's one on every row.
    expect(within(critical).getByRole('button', { name: 'Mark as read dock-01: 1 state failed' })).toBeInTheDocument()
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
    await user.click(within(row).getByRole('button', { name: MARK }))
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    expect(screen.queryByText('rover-04 is waiting for key approval')).not.toBeInTheDocument()
    expect(writes).toEqual([{ path: '/api/issues/read', body: { issues: [{ key: 'key:rover-04', fingerprint: 'f2' }] } }])
    expect(screen.getByRole('tab', { name: /Warning/ })).toHaveTextContent('0')
    expect(screen.getByRole('button', { name: 'Show 1 read' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Marked as read. 1 read issue hidden.'))
  })

  it('says so when an issue changed before it was marked, and leaves it unread', async () => {
    const user = userEvent.setup()
    issuesServer(ISSUES, { changed: ['key:rover-04'] })
    renderApp('/issues')
    const row = (await screen.findAllByRole('listitem'))[1]!
    await user.click(within(row).getByRole('button', { name: MARK }))
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        'rover-04 is waiting for key approval changed in the meantime, so it stays unread.',
      ),
    )
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
  })

  it('a double-click marks one issue, not the next one too', async () => {
    const user = userEvent.setup()
    const { writes } = issuesServer(ISSUES)
    renderApp('/issues')
    await user.click((await screen.findAllByRole('button', { name: MARK }))[0]!)
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    // The second click lands on the button that moved up; the browser counts it as the second.
    fireEvent.click(screen.getAllByRole('button', { name: MARK })[0]!, { detail: 2 })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(writes).toHaveLength(1)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('keeps keyboard focus in the list when a row leaves it', async () => {
    const user = userEvent.setup()
    issuesServer(ISSUES)
    renderApp('/issues')
    const [first, second] = await screen.findAllByRole('button', { name: MARK })
    first!.focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    expect(second).toHaveFocus()
  })

  it("a live refresh while a mark is on its way doesn't bring the row back", async () => {
    const user = userEvent.setup()
    const { fetches, release } = issuesServer(ISSUES, { hold: true })
    const { queryClient } = renderApp('/issues')
    const row = (await screen.findAllByRole('listitem'))[1]!
    await user.click(within(row).getByRole('button', { name: MARK }))
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    // A fleet change comes in before the server has answered.
    const fetched = fetches()
    createLiveInvalidator(queryClient, 0)({ type: 'fleet' })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(fetches()).toBe(fetched)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    // The answer comes, and the list is fetched once more, with the mark.
    release()
    await waitFor(() => expect(fetches()).toBe(fetched + 1))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('when one mark fails, only that issue comes back', async () => {
    const user = userEvent.setup()
    let answers = 0
    mockApi({
      '/api/issues': ISSUES,
      '/api/issues/read': () =>
        ++answers === 1
          ? new Promise<Response>(() => {}) // still on its way
          : new Response(JSON.stringify({ detail: 'database is locked' }), { status: 500 }),
      '/api/status': systemStatus(),
    })
    renderApp('/issues')
    await user.click((await screen.findAllByRole('button', { name: MARK }))[0]!)
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    await user.click(screen.getAllByRole('button', { name: MARK })[1]!)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't mark it as read: database is locked")
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('rover-04'),
      expect.stringContaining('rover-02'),
    ])
  })

  it('says so when an earlier mark fails after a later one worked', async () => {
    const user = userEvent.setup()
    let answers = 0
    let failFirst!: () => void
    mockApi({
      '/api/issues': ISSUES,
      '/api/issues/read': () =>
        ++answers === 1
          ? new Promise<Response>((resolve) => {
              failFirst = () => resolve(new Response(JSON.stringify({ detail: 'database is locked' }), { status: 500 }))
            })
          : json({ marked: ['key:rover-04'], changed: [] }),
      '/api/status': systemStatus(),
    })
    renderApp('/issues')
    await user.click((await screen.findAllByRole('button', { name: MARK }))[0]!)
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    await user.click(screen.getAllByRole('button', { name: MARK })[0]!)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Marked as read.'))
    failFirst()
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't mark it as read: database is locked")
    await waitFor(() => expect(screen.getByText('dock-01: 1 state failed')).toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent('Marked as read.')
  })

  it('shows read issues on request, muted, to mark as unread', async () => {
    const user = userEvent.setup()
    const { writes } = issuesServer(ISSUES.map((i) => (i.severity === 'critical' ? { ...i, read: true } : i)))
    renderApp('/issues')
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('tab', { name: /All/ })).toHaveTextContent('2')

    const toggle = screen.getByRole('button', { name: 'Show 1 read' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    const read = screen.getByRole('list', { name: 'Read issues' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAttribute('aria-controls', read.id)
    expect(within(read).getByText('dock-01: 1 state failed')).toHaveClass('text-muted')
    await user.click(within(read).getByRole('button', { name: /^Mark as unread/ }))
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Read issues' })).not.toBeInTheDocument())
    expect(writes).toEqual([{ path: '/api/issues/unread', body: { keys: ['state:dock-01'] } }])
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
  })

  it('opens with read issues shown', async () => {
    mockApi({ '/api/issues': ISSUES.map((i) => ({ ...i, read: true })), '/api/status': systemStatus() })
    renderApp('/issues?read=show')
    const read = await screen.findByRole('list', { name: 'Read issues' })
    expect(within(read).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('Nothing new')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide read' })).toHaveAttribute('aria-expanded', 'true')
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
    await user.click(within(row).getByRole('button', { name: MARK }))
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
