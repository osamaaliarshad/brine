import { ChevronRight, Folder, RefreshCw } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
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
import { highlightYaml, isYamlFile, type Token, type TokenKind } from '@/lib/yamlHighlight'
import { FileTree } from '@/pages/states/FileTree'
import { slsToPath } from '@/pages/states/sls'

const TABS = [
  { key: 'top', label: 'Top file' },
  { key: 'files', label: 'Files' },
] as const

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="border-t px-6 py-12 text-center text-muted">{children}</div>
}

/** "common.install_auditd" -> "common"; "dev:web.nginx" -> "dev:web"; "motd" -> null. */
function groupOf(sls: string): string | null {
  const dot = sls.indexOf('.')
  return dot > 0 ? sls.slice(0, dot) : null
}

const FOLD_OVER = 12 // states: more than this and groups start folded

function TopTab({ now, statusOf }: { now: number; statusOf: Record<string, MinionStatus> }) {
  const top = useStateTop(true)
  const files = useStateFiles(true)
  const [open, setOpen] = useState<Set<string> | 'all' | null>(null)
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
  const loose = rows.filter(([sls]) => groupOf(sls) === null)
  const groups = new Map<string, [string, string[]][]>()
  for (const row of rows) {
    const group = groupOf(row[0])
    if (group !== null) groups.set(group, [...(groups.get(group) ?? []), row])
  }
  // Small top files start unfolded; big ones start as an overview of groups.
  const isOpen = (group: string) => (open === null ? rows.length <= FOLD_OVER : open === 'all' || open.has(group))
  const toggle = (group: string) =>
    setOpen((was) => {
      const next = new Set(was === null || was === 'all' ? [...groups.keys()].filter(isOpen) : was)
      if (next.has(group)) next.delete(group)
      else next.add(group)
      return next
    })
  const allOpen = groups.size > 0 && [...groups.keys()].every(isOpen)

  const stateRow = ([sls, minions]: [string, string[]], nested: boolean) => {
    const path = files.data ? slsToPath(sls, files.data) : null
    return (
      <tr key={sls} className="border-t align-top">
        <td className={cn('px-4 py-3 font-mono sm:pl-6', nested && 'pl-10 sm:pl-12')}>
          {path ? (
            <Link to={`/states?tab=files&file=${encodeURIComponent(path)}`} className="hover:text-accent">
              {nested ? sls.slice(sls.indexOf('.') + 1) : sls}
            </Link>
          ) : nested ? (
            sls.slice(sls.indexOf('.') + 1)
          ) : (
            sls
          )}
        </td>
        <td className="px-4 py-3">
          <div className="flex flex-wrap gap-2">
            {[...minions].sort().map((m) => (
              <MinionChip key={m} id={m} status={statusOf[m]} />
            ))}
          </div>
        </td>
      </tr>
    )
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 sm:px-6">
        <p className="text-sm text-muted">Which states each minion gets, from the top file (state.show_top, asked live).</p>
        <div className="flex items-center gap-3 text-sm text-muted">
          {groups.size > 1 && (
            <button
              type="button"
              onClick={() => setOpen(allOpen ? new Set() : 'all')}
              className="flex h-8 items-center rounded-lg border px-2.5 hover:bg-surface-2"
            >
              {allOpen ? 'Collapse all' : 'Expand all'}
            </button>
          )}
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
            {loose.map((row) => stateRow(row, false))}
            {[...groups.entries()].map(([group, states]) => {
              const expanded = isOpen(group)
              const reached = [...new Set(states.flatMap(([, minions]) => minions))].sort()
              return (
                <Fragment key={group}>
                  <tr className="border-t bg-surface-2/30 align-top">
                    <td className="px-4 py-2.5 sm:pl-6">
                      <button
                        type="button"
                        onClick={() => toggle(group)}
                        aria-expanded={expanded}
                        className="flex items-center gap-1.5 font-mono font-medium hover:text-accent"
                      >
                        <ChevronRight
                          className={cn('size-4 text-muted transition-transform', expanded && 'rotate-90')}
                          aria-hidden
                        />
                        <Folder className="size-4 text-muted" aria-hidden />
                        {group}
                        <span className="ml-1 font-sans text-xs font-normal text-muted">
                          {states.length} state{states.length === 1 ? '' : 's'}
                        </span>
                      </button>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap gap-2">
                        {reached.map((m) => (
                          <MinionChip key={m} id={m} status={statusOf[m]} />
                        ))}
                      </div>
                    </td>
                  </tr>
                  {expanded && states.map((row) => stateRow(row, true))}
                </Fragment>
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

// Each kind of token in a state file, in the theme's code colors.
const TOKEN_CLASS: Record<TokenKind, string> = {
  key: 'text-code-key',
  fn: 'text-code-fn',
  string: 'text-code-string',
  number: 'text-code-number',
  comment: 'text-code-comment italic',
  jinja: 'text-code-jinja',
  punct: 'text-muted',
}

/** A file's text with line numbers; Salt states and other YAML in color. */
function FileText({ content, yaml }: { content: string; yaml: boolean }) {
  const lines = useMemo(
    () => (yaml ? highlightYaml(content) : content.split('\n').map((text): Token[] => [{ text }])),
    [content, yaml],
  )
  return (
    <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed sm:px-6">
      {lines.map((tokens, i) => (
        <div key={i} className="flex">
          <span className="w-10 shrink-0 pr-4 text-right text-muted select-none">{i + 1}</span>
          <code>
            {tokens.some((token) => token.text)
              ? tokens.map((token, j) => (
                  <span key={j} className={token.kind && TOKEN_CLASS[token.kind]}>
                    {token.text}
                  </span>
                ))
              : ' '}
          </code>
        </div>
      ))}
    </pre>
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
  return (
    // Beside the file, the tree takes the panel's height and scrolls within it.
    <div className="grid border-t md:min-h-[28rem] md:grow md:grid-cols-[16rem_1fr]">
      <div className="border-b md:relative md:border-r md:border-b-0">
        <div className="flex max-h-72 flex-col md:absolute md:inset-0 md:max-h-none">
          <FileTree paths={[...new Set(files.data.map((f) => f.path))]} selected={selected} onOpen={open} />
        </div>
      </div>
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
          <FileText content={file.data.content} yaml={isYamlFile(selected)} />
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
      <Card fill className="overflow-hidden">
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
