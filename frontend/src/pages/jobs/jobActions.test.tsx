import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CatchUpRun, JobDetail, User } from '@/api/types'
import { ago, mockApi, renderApp, systemStatus } from '@/test/render'

const OPERATOR: User = { email: 'o@example.com', name: 'Otto', picture: null, role: 'operator', provider: 'oidc' }

const JOB: JobDetail = {
  jid: '20261020120000000001',
  kind: 'local',
  fun: 'state.apply',
  target: 'rover-*',
  target_type: 'glob',
  user: 'o@example.com',
  started_at: ago(60),
  finished_at: null,
  expected: 3,
  returned: 2,
  succeeded: 2,
  failed: 0,
  caught_up: 0,
  catching_up: 0,
  args: ['motd', { test: true, __kwarg__: true }],
  minions: ['rover-01', 'rover-02', 'rover-03'],
  missing: ['rover-03'],
  catch_up: [],
  catch_up_of: null,
  results: [],
}

function api(job: JobDetail, commands: string[]) {
  mockApi({
    '/api/auth/me': OPERATOR,
    '/api/status': systemStatus(),
    '/api/capabilities': { manage_keys: { allowed: true, missing: [] }, commands },
    [`/api/jobs/${job.jid}`]: job,
  })
}

describe('job actions', () => {
  it('runs a job again, or stops it where it is still running, through the Run page', async () => {
    api(JOB, ['state.*', 'saltutil.*'])
    renderApp(`/jobs/${JOB.jid}`)
    const again = await screen.findByRole('link', { name: 'Run again' })
    expect(new URL(again.getAttribute('href')!, 'http://x').searchParams.get('command')).toBe(
      'state.apply motd test=true',
    )
    expect(again).toHaveAttribute('href', expect.stringContaining('target=rover-*'))
    const kill = screen.getByRole('link', { name: 'Kill' })
    const params = new URL(kill.getAttribute('href')!, 'http://x').searchParams
    expect([params.get('command'), params.get('target'), params.get('type')]).toEqual([
      'saltutil.kill_job 20261020120000000001',
      'rover-03',
      'list',
    ])
    const stop = screen.getByRole('link', { name: 'Stop' })
    expect(new URL(stop.getAttribute('href')!, 'http://x').searchParams.get('command')).toBe(
      'saltutil.term_job 20261020120000000001',
    )
    // What each does, in words a touch screen shows too.
    const help = screen.getByText(/^Stop asks/)
    expect(help).toHaveTextContent('Stop asks it to end (saltutil.term_job): it gets a chance to clean up.')
    expect(help).toHaveTextContent('Kill ends it at once (saltutil.kill_job), like kill -9.')
    expect(help).toHaveTextContent('Both open Run first; nothing runs until you click Run.')
  })

  // rover-03 is still to catch up; rover-04's catch-up was sent and never answered, so it's
  // missing, but what it may be running is the catch-up's job (with its own Stop), not this one.
  const run = (minion: string, patch: Partial<CatchUpRun>): CatchUpRun => ({
    id: 1, minion_id: minion, source_jid: JOB.jid, fun: JOB.fun, args: JOB.args, actor: OPERATOR.email,
    created_at: ago(7200), expires_at: ago(-86400), state: 'waiting', reason: null,
    sent_jid: null, sent_at: null, answered_at: null, ...patch,
  })
  const waiting = run('rover-03', {})
  const unanswered = run('rover-04', { id: 2, state: 'sent', sent_jid: '20261020121000000009', sent_at: ago(3600) })

  it('stops it only where it may be running, not on minions caught up in a catch-up', async () => {
    api(
      { ...JOB, missing: ['rover-02', 'rover-04'], catching_up: 1, catch_up: [waiting, unanswered] },
      ['saltutil.*'],
    )
    renderApp(`/jobs/${JOB.jid}`)
    const kill = await screen.findByRole('link', { name: 'Kill' })
    expect(new URL(kill.getAttribute('href')!, 'http://x').searchParams.get('target')).toBe('rover-02')
    const stop = screen.getByRole('link', { name: 'Stop' })
    expect(new URL(stop.getAttribute('href')!, 'http://x').searchParams.get('target')).toBe('rover-02')
    // Still said to be missing.
    expect(screen.getByText(/^No return from/)).toHaveTextContent('rover-04 (catch-up sent, no answer)')
  })

  it('offers no Stop when no missing minion may be running it', async () => {
    api({ ...JOB, missing: ['rover-04'], catching_up: 1, catch_up: [waiting, unanswered] }, ['saltutil.*'])
    renderApp(`/jobs/${JOB.jid}`)
    expect(await screen.findByRole('link', { name: 'Run again' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Stop' })).toBeNull()
    expect(screen.queryByText(/^Stop asks/)).toBeNull()
    expect(screen.getByText(/^No return from/)).toHaveTextContent('rover-04 (catch-up sent, no answer)')
  })

  it('re-runs targets the Run page cannot take on the minions the job reached', async () => {
    api({ ...JOB, target: '10.0.0.0/24', target_type: 'ipcidr', missing: [] }, ['state.*'])
    renderApp(`/jobs/${JOB.jid}`)
    const again = await screen.findByRole('link', { name: 'Run again' })
    const params = new URL(again.getAttribute('href')!, 'http://x').searchParams
    expect([params.get('target'), params.get('type')]).toEqual(['rover-01,rover-02,rover-03', 'list'])
    expect(screen.queryByRole('link', { name: 'Kill' })).toBeNull()
    expect(screen.queryByText(/^Stop asks/)).toBeNull()
  })

  it('shows nothing to people who cannot run commands', async () => {
    api(JOB, [])
    renderApp(`/jobs/${JOB.jid}`)
    await screen.findByRole('heading', { name: /state\.apply/ })
    expect(screen.queryByRole('link', { name: 'Run again' })).toBeNull()
  })
})
