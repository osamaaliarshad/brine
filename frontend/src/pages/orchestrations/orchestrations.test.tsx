import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { CommandTemplate, JobDetail, Orchestrations, User } from '@/api/types'
import { ago, mockApi, renderApp, systemStatus } from '@/test/render'

const ADMIN: User = { email: 'a@example.com', name: 'Ada Admin', picture: null, role: 'admin', provider: 'oidc' }

const ORCHESTRATIONS: Orchestrations = {
  saltenv: 'base',
  truncated: false,
  can_run: true,
  orchestrations: [
    {
      sls: 'orch.rollout',
      path: 'orch/rollout.sls',
      error: null,
      steps: [
        { id: 'rovers-answer', function: 'salt.function', what: 'test.ping', target: 'rover-*', target_type: null, needs: [], details: {} },
        {
          id: 'dock-calibration',
          function: 'salt.state',
          what: 'dock',
          target: 'G@role:dock',
          target_type: 'compound',
          needs: ['rovers-answer', 'onfail rovers-motd'],
          details: { pillar: { speed: 'slow' } },
        },
      ],
    },
    { sls: 'orch.broken', path: 'orch/broken.sls', error: 'Jinja syntax error', steps: [] },
  ],
}

const TEMPLATES: CommandTemplate[] = [
  { name: 'fib', description: 'First template', target: '*', target_type: 'glob', command: 'test.fib num=10', categories: ['cat1'], source: 'master', allowed: true },
  { name: 'nuke', description: 'Not for you', target: '*', target_type: 'glob', command: 'cmd.run reboot', categories: ['cat2'], source: 'brine', allowed: false },
]

describe('orchestrations page', () => {
  it('lists each orchestration step by step', async () => {
    mockApi({ '/api/auth/me': ADMIN, '/api/status': systemStatus(), '/api/orchestrations': ORCHESTRATIONS })
    renderApp('/orchestrations')
    const rollout = (await screen.findByRole('heading', { name: 'orch.rollout' })).closest('div.overflow-hidden') as HTMLElement
    const rows = within(rollout).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[1]!.textContent)).toEqual([
      'rovers-answer',
      'dock-calibrationpillar: {"speed":"slow"}',
    ])
    expect(rows[1]).toHaveTextContent('applies dock')
    expect(rows[1]).toHaveTextContent('G@role:dock(compound)')
    expect(rows[1]).toHaveTextContent('onfail rovers-motd')
    expect(within(rollout).getByRole('link', { name: 'Test' })).toHaveAttribute(
      'href',
      '/run?command=runners.state.orchestrate%20orch.rollout%20test%3DTrue',
    )
    expect(screen.getByText('Jinja syntax error')).toBeInTheDocument()
  })

  it('offers no buttons to roles that may not run them', async () => {
    mockApi({
      '/api/auth/me': { ...ADMIN, role: 'operator' },
      '/api/status': systemStatus(),
      '/api/orchestrations': { ...ORCHESTRATIONS, can_run: false },
    })
    renderApp('/orchestrations')
    await screen.findByRole('heading', { name: 'orch.rollout' })
    expect(screen.queryByRole('link', { name: /Run…/ })).toBeNull()
  })
})

describe('templates on the Run page', () => {
  it('fills in and previews a template, by category', async () => {
    const user = userEvent.setup()
    const previews: unknown[] = []
    mockApi({
      '/api/auth/me': ADMIN,
      '/api/status': systemStatus(),
      '/api/capabilities': { manage_keys: { allowed: true, missing: [] }, commands: ['*'] },
      '/api/commands/templates': TEMPLATES,
      '/api/commands/preview': (_url: URL, init?: RequestInit) => {
        previews.push(JSON.parse(String(init?.body)))
        return { client: 'local', fun: 'test.fib', qualified: 'test.fib', args: ['num=10'], minions: ['rover-01'], offline: [], unknown: [], from_cache: false }
      },
    })
    renderApp('/run')
    expect(await screen.findByRole('button', { name: /Not for you/ })).toBeDisabled()
    await user.click(screen.getByRole('tab', { name: 'cat1' }))
    expect(screen.queryByRole('button', { name: /Not for you/ })).toBeNull()
    await user.click(screen.getByRole('button', { name: /First template/ }))
    expect(screen.getByRole('textbox', { name: 'Command' })).toHaveValue('test.fib num=10')
    expect(await screen.findByRole('button', { name: 'Run on 1 minion' })).toBeInTheDocument()
    expect(previews).toEqual([{ command: 'test.fib num=10', target: '*', target_type: 'glob' }])
  })
})

describe('an orchestration job', () => {
  it('links each step to the job it started', async () => {
    const job: JobDetail = {
      jid: '20261020120000000100',
      kind: 'runner',
      fun: 'state.orchestrate',
      target: null,
      target_type: null,
      user: 'a@example.com',
      started_at: ago(60),
      finished_at: ago(30),
      expected: 1,
      returned: 1,
      succeeded: 0,
      failed: 1,
      args: ['orch.rollout'],
      minions: ['master'],
      missing: [],
      catch_up: [],
      catch_up_of: null,
      results: [
        {
          minion_id: 'master',
          returned_at: ago(30),
          success: false,
          retcode: null,
          data: {},
          states: [
            { id: 'rovers-answer', name: 'test.ping', function: 'salt.function', sls: 'orch.rollout', result: true, changed: false, comment: 'ok', duration_ms: 120, jid: '20261020120000000201' },
          ],
        },
      ],
    }
    mockApi({ '/api/auth/me': ADMIN, '/api/status': systemStatus(), [`/api/jobs/${job.jid}`]: job })
    renderApp(`/jobs/${job.jid}`)
    expect(await screen.findByRole('link', { name: 'its job' })).toHaveAttribute('href', '/jobs/20261020120000000201')
  })
})
