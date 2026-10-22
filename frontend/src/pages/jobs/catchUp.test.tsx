import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CatchUpRun, JobDetail, JobResult, MinionDetail, User } from '@/api/types'
import { formatAbsolute } from '@/lib/time'
import { ago, minion, mockApi, NOW, renderApp, systemStatus } from '@/test/render'

const ME: User = { email: 'o@example.com', name: 'Otto', picture: null, role: 'operator', provider: 'oidc' }
const later = (seconds: number) => new Date(NOW + seconds * 1000).toISOString()

function catchUp(patch: Partial<CatchUpRun>): CatchUpRun {
  return {
    id: 1,
    minion_id: 'rover-03',
    source_jid: '20261020120000000001',
    fun: 'test.echo',
    args: ['hello world'],
    actor: 'o@example.com',
    created_at: ago(600),
    expires_at: later(6 * 86400),
    state: 'waiting',
    reason: null,
    sent_jid: null,
    sent_at: null,
    answered_at: null,
    ...patch,
  }
}

const JOB: JobDetail = {
  jid: '20261020120000000001',
  kind: 'local',
  fun: 'test.echo',
  target: 'rover-*',
  target_type: 'glob',
  user: 'o@example.com',
  started_at: ago(600),
  finished_at: ago(598),
  expected: 3,
  returned: 2,
  succeeded: 2,
  failed: 0,
  caught_up: 0,
  args: ['hello world'],
  minions: ['rover-01', 'rover-02', 'rover-03'],
  missing: ['rover-03'],
  results: [],
  catch_up: [
    catchUp({}),
    catchUp({ id: 2, minion_id: 'rover-04', state: 'sent', sent_jid: '20261020121000000009', sent_at: ago(60) }),
    catchUp({ id: 3, minion_id: 'rover-05', state: 'refused', reason: 'o@example.com may no longer run test.echo' }),
  ],
  catch_up_of: null,
}

const LATE_JID = '20261020121000000009'

function result(minionId: string, patch: Partial<JobResult> = {}): JobResult {
  return {
    minion_id: minionId,
    returned_at: ago(598),
    success: true,
    retcode: 0,
    data: `hello from ${minionId}`,
    states: null,
    caught_up: null,
    ...patch,
  }
}

function open(job: JobDetail) {
  mockApi({ '/api/auth/me': ME, '/api/status': systemStatus(), [`/api/jobs/${job.jid}`]: job })
  renderApp(`/jobs/${job.jid}`)
}

const panelRows = async () => {
  const heading = await screen.findByRole('heading', { name: 'Catching up offline minions' })
  return within(heading.closest('div.overflow-hidden') as HTMLElement).getAllByRole('listitem')
}

describe('catch-up runs', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('shows on the job which minions it is still waiting for, and lets you cancel', async () => {
    const user = userEvent.setup()
    const cancelled: string[] = []
    mockApi({
      '/api/auth/me': ME,
      '/api/status': systemStatus(),
      [`/api/jobs/${JOB.jid}`]: JOB,
      '/api/commands/catch-up/1/cancel': (url: URL) => {
        cancelled.push(url.pathname)
        return { ...JOB.catch_up[0], state: 'cancelled' }
      },
    })
    renderApp(`/jobs/${JOB.jid}`)
    const panel = (await screen.findByRole('heading', { name: 'Catching up offline minions' })).closest('div.overflow-hidden') as HTMLElement
    const rows = within(panel).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent("rover-03WaitingRuns when it's back · gives up in 6d")
    expect(within(rows[1]!).getByRole('link', { name: 'its job' })).toHaveAttribute('href', '/jobs/20261020121000000009')
    expect(rows[2]).toHaveTextContent('Not sento@example.com may no longer run test.echo')
    expect(within(panel).getAllByRole('button', { name: /^Cancel/ })).toHaveLength(1)
    await user.click(within(rows[0]!).getByRole('button', { name: 'Cancel the catch-up for rover-03' }))
    expect(cancelled).toEqual(['/api/commands/catch-up/1/cancel'])
  })

  it('shows the result of a minion that caught up with the others, and where it came from', async () => {
    open({
      ...JOB,
      succeeded: 3,
      caught_up: 1,
      missing: [],
      results: [
        result('rover-01'),
        result('rover-02'),
        result('rover-03', { returned_at: ago(55), caught_up: { jid: LATE_JID, at: ago(60) } }),
      ],
      catch_up: [catchUp({ state: 'sent', sent_jid: LATE_JID, sent_at: ago(60), answered_at: ago(55) })],
    })
    expect(await screen.findByText('hello from rover-03')).toBeInTheDocument()
    expect(screen.getByText('Results').nextSibling).toHaveTextContent('2/3· 1 caught up')
    expect(screen.queryByText(/missing/)).toBeNull()
    expect(screen.queryByText(/No return from/)).toBeNull()
    expect(screen.queryByText(/Waiting to catch up/)).toBeNull()

    const note = screen.getByText(/^Caught up later/)
    expect(note).toHaveTextContent(`Caught up later, in job ${LATE_JID}, 1m ago`)
    expect(within(note).getByRole('link', { name: LATE_JID })).toHaveAttribute('href', `/jobs/${LATE_JID}`)
    expect(within(note).getByText('1m ago')).toHaveAttribute('title', formatAbsolute(ago(60)))
    // Its time is in the note, not as time since the job started.
    expect(screen.getAllByText(/^returned after/)).toHaveLength(2)

    const [row] = await panelRows()
    expect(row).toHaveTextContent('rover-03Caught upRan 1m ago · its job')
  })

  it('says who is still to catch up, and how it is getting on, apart from who never answered', async () => {
    open({
      ...JOB,
      expected: 4,
      returned: 1,
      succeeded: 1,
      minions: ['rover-01', 'rover-02', 'rover-03', 'rover-04'],
      missing: ['rover-02', 'rover-03', 'rover-04'],
      results: [result('rover-01')],
      catch_up: [
        catchUp({}),
        catchUp({ id: 2, minion_id: 'rover-04', state: 'sent', sent_jid: LATE_JID, sent_at: ago(60) }),
      ],
    })
    expect(await screen.findByText(/^Waiting to catch up/)).toHaveTextContent(
      "Waiting to catch up: rover-03 (runs when it's back), rover-04 (sent, no answer yet).",
    )
    expect(screen.getByText(/^No return from/)).toHaveTextContent(
      'No return from rover-02. They may have been offline, or are still running it.',
    )
    expect(screen.getByText('Results').nextSibling).toHaveTextContent('1/4· 3 missing')
    const [, sent] = await panelRows()
    expect(sent).toHaveTextContent('rover-04SentSent 1m ago, no answer yet · its job')
  })

  it('while the job is young, waits only for the minions that got it', async () => {
    open({ ...JOB, started_at: ago(5), finished_at: null, missing: ['rover-02', 'rover-03'], results: [result('rover-01')] })
    expect(await screen.findByRole('status')).toHaveTextContent(/^Waiting for 1 of 3 minions$/)
    expect(screen.getByText('rover-02')).toBeInTheDocument()
    expect(screen.getByText(/^Waiting to catch up/)).toHaveTextContent("Waiting to catch up: rover-03 (runs when it's back).")
  })

  it('says why a minion whose catch-up came to nothing is still missing', async () => {
    open({
      ...JOB,
      missing: ['rover-02', 'rover-03'],
      catch_up: [
        catchUp({ minion_id: 'rover-02', state: 'refused', reason: 'o@example.com may no longer run test.echo' }),
        catchUp({ id: 2, state: 'cancelled', reason: 'cancelled by o@example.com' }),
      ],
    })
    expect(await screen.findByText(/^No return from/)).toHaveTextContent(
      'No return from rover-02 (catch-up not sent), rover-03 (catch-up cancelled). They may have been offline, or are still running it.',
    )
    expect(screen.queryByText(/Waiting to catch up/)).toBeNull()
  })

  it('says when a job was itself a catch-up run', async () => {
    mockApi({
      '/api/auth/me': ME,
      '/api/status': systemStatus(),
      '/api/jobs/9': { ...JOB, jid: '9', target: 'rover-03', catch_up: [], catch_up_of: JOB.jid },
    })
    renderApp('/jobs/9')
    expect(await screen.findByRole('link', { name: 'the original job' })).toHaveAttribute('href', `/jobs/${JOB.jid}`)
  })

  it('lists on a minion what is waiting for it', async () => {
    const detail: MinionDetail = {
      ...minion('rover-03', { status: 'offline', connected: false }),
      first_seen_at: ago(86400),
      grains: {},
      presence_history: [],
      recent_jobs: [],
      waiting_runs: [catchUp({})],
    }
    mockApi({ '/api/auth/me': ME, '/api/status': systemStatus(), '/api/minions/rover-03': detail })
    renderApp('/minions/rover-03')
    expect(await screen.findByText('1 command waiting for rover-03 to come back')).toBeInTheDocument()
    expect(screen.getByText('test.echo "hello world"')).toBeInTheDocument()
  })
})
