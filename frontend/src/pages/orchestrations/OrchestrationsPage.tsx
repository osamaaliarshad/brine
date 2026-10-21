import { FlaskConical, Play } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useOrchestrations } from '@/api/queries'
import type { Orchestration, OrchestrationStep } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui'
import { CONTROL } from '@/pages/fleet/FleetToolbar'

const DOES: Record<string, string> = {
  'salt.state': 'applies',
  'salt.function': 'runs',
  'salt.runner': 'runner',
  'salt.wheel': 'wheel',
  'salt.parallel_runners': 'runners',
}

const Code = ({ children }: { children: ReactNode }) => <code className="font-mono text-[13px]">{children}</code>

/** "key: value · key: value" for the arguments without a column of their own. */
function details(step: OrchestrationStep): string {
  return Object.entries(step.details)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ')
}

/** Running goes through the Run page: it previews, needs a click, and is audited. Required
 *  pillar inputs become fill-in fields there. */
function runLink(o: Orchestration, test: boolean) {
  const required = o.inputs.filter((i) => i.required)
  const pillar = required.length
    ? ` pillar='${JSON.stringify(Object.fromEntries(required.map((i) => [i.name, `{{ ${i.name} }}`])))}'`
    : ''
  const command = `runners.state.orchestrate ${o.sls}${pillar}${test ? ' test=True' : ''}`
  return `/run?command=${encodeURIComponent(command)}`
}

function Inputs({ inputs }: { inputs: Orchestration['inputs'] }) {
  const required = inputs.filter((i) => i.required).map((i) => i.name)
  const optional = inputs.filter((i) => !i.required).map((i) => i.name)
  return (
    <div className="border-b px-4 py-2.5 text-sm sm:px-6">
      <span className="text-muted">Takes pillar: </span>
      {required.map((name, i) => (
        <span key={name}>
          {i > 0 && ', '}
          <Code>{name}</Code>
        </span>
      ))}
      {optional.length > 0 && (
        <span className="text-muted">
          {required.length > 0 && ' · '}optional {optional.join(', ')}
        </span>
      )}
      {required.length > 0 && (
        <span className="text-muted"> (steps below show them as {'<'}name{'>'})</span>
      )}
    </div>
  )
}

function OrchestrationCard({ orchestration: o, canRun }: { orchestration: Orchestration; canRun: boolean }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <h2 className="font-mono font-medium break-all">{o.sls}</h2>
          <div className="text-xs text-muted">
            {o.path}
            {!o.error && ` · ${o.steps.length} step${o.steps.length === 1 ? '' : 's'}`}
          </div>
        </div>
        {canRun && (!o.error || o.inputs.length > 0) && (
          <div className="flex gap-2">
            <Link to={runLink(o, true)} className={CONTROL} title="Run with test=True: shows what would change">
              <FlaskConical className="size-4 text-muted" aria-hidden />
              Test
            </Link>
            <Link
              to={runLink(o, false)}
              className="flex h-10 items-center gap-2 rounded-lg bg-accent px-3 text-sm font-medium text-accent-fg"
            >
              <Play className="size-4" aria-hidden />
              Run…
            </Link>
          </div>
        )}
      </div>
      {o.inputs.length > 0 && <Inputs inputs={o.inputs} />}
      {o.error ? (
        <pre className="overflow-x-auto px-4 py-3 font-mono text-[13px] whitespace-pre-wrap text-danger sm:px-6">
          {o.error}
        </pre>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
              <tr>
                <th className="w-10 px-4 py-2 font-medium sm:pl-6">#</th>
                <th className="px-4 py-2 font-medium">Step</th>
                <th className="px-4 py-2 font-medium">Does</th>
                <th className="px-4 py-2 font-medium">On</th>
                <th className="px-4 py-2 font-medium">After</th>
              </tr>
            </thead>
            <tbody>
              {o.steps.map((s, i) => (
                <tr key={s.id} className="border-t align-top">
                  <td className="px-4 py-2.5 tabular-nums text-muted sm:pl-6">{i + 1}</td>
                  <td className="px-4 py-2.5">
                    <div className="font-mono">{s.id}</div>
                    {details(s) && <div className="mt-0.5 text-xs text-muted">{details(s)}</div>}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-muted">{DOES[s.function] ?? s.function}</span> <Code>{s.what || '—'}</Code>
                  </td>
                  <td className="px-4 py-2.5">
                    {s.target ? (
                      <>
                        <Code>{s.target}</Code>
                        {s.target_type && s.target_type !== 'glob' && (
                          <span className="ml-1 text-xs text-muted">({s.target_type})</span>
                        )}
                      </>
                    ) : (
                      <span className="text-muted">master</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-muted">
                    {s.needs.length ? s.needs.map((n) => <div key={n}>{n}</div>) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

export function OrchestrationsPage() {
  const query = useOrchestrations()
  const data = query.data
  return (
    <>
      <PageHeader
        title="Orchestrations"
        subtitle="Runs the master drives step by step: each step targets minions, or runs on the master."
      />
      {query.isPending ? (
        <Card className="px-6 py-12 text-center text-muted">Loading orchestrations from the master…</Card>
      ) : query.isError ? (
        <Card className="px-6 py-12 text-center text-muted">Couldn't load orchestrations: {query.error.message}</Card>
      ) : data && data.orchestrations.length === 0 ? (
        <Card className="px-6 py-12 text-center text-muted">
          No orchestrations in <Code>{data.saltenv}</Code>. They're .sls files whose steps use <Code>salt.state</Code>,{' '}
          <Code>salt.function</Code>, <Code>salt.runner</Code> or <Code>salt.wheel</Code>.
        </Card>
      ) : (
        data && (
          <div className="flex flex-col gap-4 sm:gap-6">
            {data.orchestrations.map((o) => (
              <OrchestrationCard key={o.sls} orchestration={o} canRun={data.can_run} />
            ))}
            <p className="text-xs text-muted">
              Steps are in run order; requisites can change it. Each step starts its own job, recorded under whoever ran
              the orchestration.
              {data.truncated && ' Only the first 300 .sls files were checked.'}
            </p>
          </div>
        )
      )}
    </>
  )
}
