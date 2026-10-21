import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CatchUpRun, JobDetail, MinionDetail, User } from '@/api/types'
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
