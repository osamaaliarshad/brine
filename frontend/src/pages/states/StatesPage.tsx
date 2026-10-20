import { FileCode, RefreshCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { useFleet, useStateFile, useStateFiles, useStateTop } from '@/api/queries'
import type { MinionStatus } from '@/api/types'
import { MinionChip } from '@/components/MinionChip'
import { PageHeader } from '@/components/PageHeader'
import { Tabs } from '@/components/Tabs'
import { Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { useTab } from '@/lib/useTab'
import { slsToPath } from '@/pages/states/sls'

const TABS = [
  { key: 'top', label: 'Top file' },
  { key: 'files', label: 'Files' },
] as const

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="border-t px-6 py-12 text-center text-muted">{children}</div>
}

function TopTab({ now, statusOf }: { now: number; statusOf: Record<string, MinionStatus> }) {
  const top = useStateTop(true)
  const files = useStateFiles(true)
  const bySls = new Map<string, string[]>()
  for (const [minion, envs] of Object.entries(top.data?.minions ?? {})) {
    for (const [env, states] of Object.entries(envs)) {
      for (const sls of states) {
        const name = env === 'base' ? sls : `${env}:${sls}`
        bySls.set(name, [...(bySls.get(name) ?? []), minion])
      }
    }
  }
  const rows = [...bySls.entries()].sort(([a], [b]) => a.localeCompare(b))

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 sm:px-6">
        <p className="text-sm text-muted">Which states each minion gets, from the top file (state.show_top, asked live).</p>
        <div className="flex items-center gap-3 text-sm text-muted">
          {top.data && (
            <span title={formatAbsolute(top.data.fetched_at)}>Asked {formatRelative(top.data.fetched_at, now)}</span>
          )}
          <button
            type="button"
            onClick={() => void top.refetch()}
            className="flex h-8 items-center gap-1.5 rounded-lg border px-2.5 hover:bg-surface-2"
          >
            <RefreshCw className={cn('size-3.5', top.isFetching && 'animate-spin')} aria-hidden />
            Refresh
          </button>
        </div>
      </div>
      {top.isPending ? (
        <Empty>Asking the minions…</Empty>
      ) : top.isError ? (
        <Empty>Couldn't get the top file: {top.error.message}</Empty>
      ) : rows.length === 0 ? (
        <Empty>No minion answered with any states.</Empty>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-surface-2/40 text-left text-xs uppercase tracking-wider text-muted">
            <tr>
              <th className="px-4 py-3 font-medium sm:pl-6">State</th>
              <th className="px-4 py-3 font-medium">Applied to</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([sls, minions]) => {
              const path = files.data ? slsToPath(sls, files.data) : null
              return (
                <tr key={sls} className="border-t align-top">
                  <td className="px-4 py-3 font-mono sm:pl-6">
                    {path ? (
                      <Link to={`/states?tab=files&file=${encodeURIComponent(path)}`} className="hover:text-accent">
                        {sls}
                      </Link>
                    ) : (
                      sls
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      {minions.sort().map((m) => (
                        <MinionChip key={m} id={m} status={statusOf[m]} />
                      ))}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {top.data && top.data.missing.length > 0 && (
        <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">Didn't answer: {top.data.missing.join(', ')}</p>
      )}
      {top.data && top.data.skipped.length > 0 && (
        <p className="border-t px-4 py-3 text-sm text-muted sm:px-6">
          Offline, not asked: {top.data.skipped.join(', ')}
        </p>
      )}
    </>
  )
}

function FilesTab() {
  const [params, setParams] = useSearchParams()
  const files = useStateFiles(true)
  const selected = params.get('file') ?? files.data?.find((f) => f.path === 'top.sls')?.path ?? files.data?.[0]?.path ?? null
  const file = useStateFile(selected)
  const open = (path: string) => {
    const next = new URLSearchParams(params)
    next.set('file', path)
    setParams(next, { replace: true })
  }
  if (files.isPending) return <Empty>Loading files…</Empty>
  if (files.isError) return <Empty>Couldn't list state files: {files.error.message}</Empty>
  if (files.data.length === 0) return <Empty>No files in the master's file roots.</Empty>
  const lines = file.data?.content.split('\n') ?? []

  return (
    <div className="grid border-t md:grid-cols-[16rem_1fr]">
      <ul aria-label="State files" className="max-h-64 overflow-y-auto border-b py-2 md:max-h-[36rem] md:border-r md:border-b-0">
        {files.data.map((f) => (
          <li key={`${f.root}/${f.path}`}>
            <button
              type="button"
              onClick={() => open(f.path)}
              aria-current={f.path === selected ? 'true' : undefined}
              className={cn(
                'flex w-full items-center gap-2 px-4 py-1.5 text-left font-mono text-[13px] hover:bg-surface-2',
                f.path === selected && 'bg-surface-2 text-accent',
              )}
            >
              <FileCode className="size-3.5 shrink-0 text-muted" aria-hidden />
              <span className="truncate">{f.path}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="min-w-0">
        <div className="border-b px-4 py-3 font-mono text-sm sm:px-6">
          {file.data?.full_path ?? selected}
          {file.data?.truncated && <span className="ml-2 text-warn">(truncated)</span>}
        </div>
        {file.isPending ? (
          <p className="px-6 py-10 text-center text-muted">Loading…</p>
        ) : file.isError ? (
          <p className="px-6 py-10 text-center text-muted">Couldn't read {selected}: {file.error.message}</p>
        ) : (
          <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed sm:px-6">
            {lines.map((line, i) => (
              <div key={i} className="flex">
                <span className="w-10 shrink-0 pr-4 text-right text-muted select-none">{i + 1}</span>
                <code>{line || ' '}</code>
              </div>
            ))}
          </pre>
        )}
      </div>
    </div>
  )
}

export function StatesPage() {
  const now = useNow()
  const [tab, setTab] = useTab(TABS, 'top')
  const fleet = useFleet()
  const statusOf = Object.fromEntries((fleet.data?.minions ?? []).map((m) => [m.id, m.status]))
  return (
    <>
      <PageHeader title="States" subtitle="What the master tells each minion to be." />
      <Card className="overflow-hidden">
        <div className="px-2 sm:px-4">
          <Tabs tabs={TABS} active={tab} onSelect={setTab} label="State views" />
        </div>
        {tab === 'top' ? <TopTab now={now} statusOf={statusOf} /> : <FilesTab />}
      </Card>
      <p className="mt-3 text-sm text-muted">
        Results of state runs are under{' '}
        <Link to="/jobs?tab=states" className="text-accent hover:underline">
          Jobs › State runs
        </Link>
        .
      </p>
    </>
  )
}
