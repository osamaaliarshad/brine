import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { JobDetail, User } from '@/api/types'
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
  })

  it('re-runs targets the Run page cannot take on the minions the job reached', async () => {
    api({ ...JOB, target: '10.0.0.0/24', target_type: 'ipcidr', missing: [] }, ['state.*'])
    renderApp(`/jobs/${JOB.jid}`)
    const again = await screen.findByRole('link', { name: 'Run again' })
    const params = new URL(again.getAttribute('href')!, 'http://x').searchParams
    expect([params.get('target'), params.get('type')]).toEqual(['rover-01,rover-02,rover-03', 'list'])
    expect(screen.queryByRole('link', { name: 'Kill' })).toBeNull()
  })

  it('shows nothing to people who cannot run commands', async () => {
    api(JOB, [])
    renderApp(`/jobs/${JOB.jid}`)
    await screen.findByRole('heading', { name: /state\.apply/ })
    expect(screen.queryByRole('link', { name: 'Run again' })).toBeNull()
  })
})
