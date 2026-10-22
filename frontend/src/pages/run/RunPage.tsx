import { LayoutTemplate, Server, TerminalSquare } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useCapabilities, useCommandPreview, useRunCommand, useTemplates } from '@/api/queries'
import type { CommandPreview, CommandRequest, CommandTemplate, TargetType } from '@/api/types'
import { JsonTree } from '@/components/JsonView'
import { Select } from '@/components/Listbox'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Card } from '@/components/ui'
import { cn } from '@/lib/cn'
import { CONTROL } from '@/pages/fleet/FleetToolbar'
import { loadHistory, remember, type HistoryItem } from '@/pages/run/history'

const TARGET_TYPES: { value: TargetType; label: string; placeholder: string }[] = [
  { value: 'glob', label: 'Glob', placeholder: 'rover-*' },
  { value: 'list', label: 'List', placeholder: 'rover-01, rover-02' },
  { value: 'compound', label: 'Compound', placeholder: 'G@os:Debian and rover-*' },
  { value: 'grain', label: 'Grain', placeholder: 'os:Debian' },
  { value: 'nodegroup', label: 'Nodegroup', placeholder: 'rovers' },
  { value: 'pcre', label: 'Regex', placeholder: 'rover-0[1-3]' },
]

const MAX_CHIPS = 60

/** runners.* and wheel.* run on the master and take no target. */
function onMaster(command: string) {
  return /^(runners?|wheel)\./.test(command.trim())
}

/** `{{ name }}` in a target or command is a fill-in field (templates, orchestration inputs). */
const FIELD = /\{\{\s*([A-Za-z_][\w-]*)\s*\}\}/g

function fieldNames(...texts: string[]): string[] {
  const names: string[] = []
  for (const text of texts) for (const match of text.matchAll(FIELD)) if (!names.includes(match[1]!)) names.push(match[1]!)
  return names
}

function fillIn(text: string, values: Record<string, string>): string {
  return text.replace(FIELD, (_, name: string) => values[name] ?? '')
}

function asTargetType(value: string | null): TargetType {
  return TARGET_TYPES.find((t) => t.value === value)?.value ?? 'glob'
}

const Code = ({ children }: { children: ReactNode }) => (
  <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[13px]">{children}</code>
)

function Preview({ preview }: { preview: CommandPreview }) {
  const what = [preview.qualified, ...preview.args].join(' ')
  if (preview.client !== 'local')
    return (
      <p className="flex items-center gap-2">
        <Server className="size-4 text-muted" aria-hidden />
        Runs <Code>{what}</Code> on the master.
      </p>
    )
  const offline = new Set(preview.offline)
  const n = preview.minions.length
  return (
    <div className="flex flex-col gap-3">
      <p>
        {n === 0 ? (
          <>Nothing matches that target.</>
        ) : (
          <>
            Runs <Code>{what}</Code> on {n} minion{n === 1 ? '' : 's'}
            {offline.size > 0 && (
              <span className="text-muted">
                {' '}
                ({offline.size} offline: {offline.size === 1 ? "it won't" : "they won't"} answer now)
              </span>
            )}
            :
          </>
        )}
      </p>
      {n > 0 && (
        <ul aria-label="Minions it runs on" className="flex flex-wrap gap-1.5">
          {preview.minions.slice(0, MAX_CHIPS).map((m) => (
            <li
              key={m}
              className={cn(
                'rounded-md border px-2 py-0.5 font-mono text-[13px]',
                offline.has(m) && 'border-dashed text-muted',
              )}
              title={offline.has(m) ? 'Offline' : undefined}
            >
              {m}
            </li>
          ))}
          {n > MAX_CHIPS && <li className="px-1 text-sm text-muted">and {n - MAX_CHIPS} more</li>}
        </ul>
      )}
      {preview.unknown.length > 0 && (
        <p className="text-sm text-warn">Not accepted minions, so skipped: {preview.unknown.join(', ')}</p>
      )}
      {preview.from_cache && (
        <p className="text-sm text-muted">
          Matched from the master's cache. Minions it has no data for aren't listed, but Salt may still ask them.
        </p>
      )}
    </div>
  )
}

/** Ready-made commands (brine's templates and SaltGUI's saltgui_templates), by category. */
function Templates({ onPick }: { onPick: (template: CommandTemplate) => void }) {
  const templates = useTemplates(true).data ?? []
  const [category, setCategory] = useState<string | null>(null)
  if (templates.length === 0) return null
  const categories = [...new Set(templates.flatMap((t) => t.categories))].sort()
  const shown = category ? templates.filter((t) => t.categories.includes(category)) : templates
  return (
    <Card className="h-fit overflow-hidden">
      <h2 className="flex items-center gap-2 border-b px-4 py-3 font-medium">
        <LayoutTemplate className="size-4 text-muted" aria-hidden />
        Templates
      </h2>
      {categories.length > 0 && (
        <div role="tablist" aria-label="Template categories" className="flex flex-wrap gap-1.5 border-b px-4 py-2.5">
          {[null, ...categories].map((c) => (
            <button
              key={c ?? '(all)'}
              type="button"
              role="tab"
              aria-selected={category === c}
              onClick={() => setCategory(c)}
              className={cn(
                'rounded-md border px-2 py-0.5 text-xs hover:bg-surface-2',
                category === c && 'border-accent bg-accent/10',
              )}
            >
              {c ?? 'All'}
            </button>
          ))}
        </div>
      )}
      <ul>
        {shown.map((t) => (
          <li key={t.name} className="border-b last:border-b-0">
            <button
              type="button"
              disabled={!t.allowed}
              title={t.allowed ? undefined : "Your role can't run this one"}
              onClick={() => onPick(t)}
              className="w-full px-4 py-2.5 text-left hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <div className="text-sm">{t.description || t.name}</div>
              <div className="truncate font-mono text-xs text-muted">
                {t.command || '(fills in the target)'}
                {t.target && !onMaster(t.command) && ` · ${t.target}`}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function RunPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const patterns = useCapabilities(true).data?.commands
  const [target, setTarget] = useState(params.get('target') ?? '')
  const [targetType, setTargetType] = useState<TargetType>(asTargetType(params.get('type')))
  const [command, setCommand] = useState(params.get('command') ?? '')
  const [history, setHistory] = useState(loadHistory)
  const [catchUp, setCatchUp] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const preview = useCommandPreview()
  const run = useRunCommand()
  const master = onMaster(command)
  const fields = fieldNames(command, master ? '' : target)
  const unfilled = fields.filter((name) => !values[name]?.trim())
  const request: CommandRequest = {
    command: fillIn(command, values),
    target: master ? '' : fillIn(target, values),
    target_type: targetType,
  }
  const shown = preview.data
  const canRun = !!shown && (shown.client !== 'local' || shown.minions.length > 0)

  // A link with a command in it (/run?target=…&command=…) opens already previewed. A preview
  // never runs anything; running still takes a click.
  const linked = useRef(params.get('command') && unfilled.length === 0 ? request : null)
  const { mutate: previewNow } = preview
  useEffect(() => {
    if (linked.current) previewNow(linked.current)
    linked.current = null
  }, [previewNow])

  // Any edit makes the preview (and a previous result) out of date.
  const changed = () => {
    preview.reset()
    run.reset()
    setCatchUp(false)
  }

  const fill = (item: HistoryItem) => {
    setCommand(item.command)
    setTarget(item.target)
    setTargetType(item.target_type)
    changed()
  }

  // A template fills the form and previews straight away (a preview runs nothing), unless it
  // has fields to fill in first.
  const pick = (template: CommandTemplate) => {
    fill({ command: template.command, target: template.target, target_type: template.target_type })
    if (template.command.trim() && fieldNames(template.command, template.target).length === 0)
      preview.mutate({
        command: template.command,
        target: onMaster(template.command) ? '' : template.target,
        target_type: template.target_type,
      })
  }

  const start = () => {
    if (!shown) return
    run.mutate(
      { ...request, expect: shown.minions, catch_up: catchUp && shown.offline.length > 0 },
      {
        onSuccess: (result) => {
          setHistory((h) => remember({ command: request.command, target: request.target, target_type: targetType }, h))
          if (result.jid) void navigate(`/jobs/${result.jid}`)
        },
      },
    )
  }

  if (patterns && patterns.length === 0)
    return (
      <>
        <PageHeader title="Run a command" />
        <Card className="px-6 py-10 text-center text-muted">
          Your role can't run commands in brine. Admins decide who can, under <Code>commands</Code> in brine's config.
        </Card>
      </>
    )

  const typeInfo = TARGET_TYPES.find((t) => t.value === targetType)!
  const unrestricted = patterns?.includes('*')

  return (
    <>
      <PageHeader title="Run a command" subtitle="Salt functions on minions or the master. You'll see where it runs first." />
      <div className="grid gap-4 sm:gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-4 sm:gap-6">
          <Card className="p-4 sm:p-6">
            <form
              className="flex flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault()
                if (unfilled.length === 0) preview.mutate(request)
              }}
            >
              <div className={cn('flex flex-col gap-2 sm:flex-row', master && 'opacity-50')}>
                <Select
                  label="Target type"
                  value={targetType}
                  options={TARGET_TYPES}
                  disabled={master}
                  onChange={(type) => {
                    setTargetType(type)
                    changed()
                  }}
                  className="sm:w-36"
                  buttonClassName={cn(CONTROL, 'cursor-pointer')}
                />
                <input
                  aria-label="Target"
                  value={master ? '' : target}
                  disabled={master}
                  placeholder={master ? 'Runs on the master' : typeInfo.placeholder}
                  onChange={(event) => {
                    setTarget(event.target.value)
                    changed()
                  }}
                  spellCheck={false}
                  autoComplete="off"
                  className="h-10 min-w-0 flex-1 rounded-lg border bg-bg px-3 font-mono text-sm outline-none focus:border-accent"
                />
              </div>
              <div>
                <input
                  aria-label="Command"
                  value={command}
                  autoFocus
                  placeholder="test.ping"
                  onChange={(event) => {
                    setCommand(event.target.value)
                    changed()
                  }}
                  spellCheck={false}
                  autoComplete="off"
                  className="h-11 w-full rounded-lg border bg-bg px-3 font-mono outline-none focus:border-accent"
                />
                <p className="mt-2 text-xs text-muted">
                  Like the salt CLI after the target: <Code>state.apply webserver test=True</Code>. Start with{' '}
                  <Code>runners.</Code> or <Code>wheel.</Code> to run on the master.
                </p>
                {fields.length > 0 && (
                  <fieldset className="mt-3 rounded-lg border px-3 pt-1 pb-3">
                    <legend className="px-1 text-xs text-muted">Fill in</legend>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {fields.map((name, i) => (
                        <label key={name} className="block">
                          <span className="font-mono text-xs text-muted">{name}</span>
                          <input
                            value={values[name] ?? ''}
                            autoFocus={i === 0}
                            onChange={(event) => {
                              setValues((v) => ({ ...v, [name]: event.target.value }))
                              changed()
                            }}
                            spellCheck={false}
                            autoComplete="off"
                            className="mt-1 h-10 w-full rounded-lg border bg-bg px-3 font-mono text-sm outline-none focus:border-accent"
                          />
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )}
                {patterns && !unrestricted && (
                  <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    You can run:
                    {patterns.map((p) => (
                      <Badge key={p}>{p}</Badge>
                    ))}
                  </p>
                )}
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!command.trim() || unfilled.length > 0 || preview.isPending}
                  className="h-10 rounded-lg border px-4 text-sm font-medium hover:bg-surface-2 disabled:opacity-40"
                >
                  {preview.isPending ? 'Checking…' : 'Preview'}
                </button>
              </div>
            </form>
          </Card>

          {(preview.isError || shown) && (
            <Card className="p-4 sm:p-6">
              {preview.isError ? (
                <p role="alert" className="text-danger">
                  {preview.error.message}
                </p>
              ) : (
                shown && (
                  <div className="flex flex-col gap-4">
                    <Preview preview={shown} />
                    {shown.client === 'local' && shown.offline.length > 0 && !run.data && (
                      <label className="flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm">
                        <input
                          type="checkbox"
                          checked={catchUp}
                          onChange={(event) => setCatchUp(event.target.checked)}
                          className="mt-0.5 size-4 accent-accent"
                        />
                        <span>
                          Also run it on the {shown.offline.length} offline minion
                          {shown.offline.length === 1 ? " when it's" : "s when they're"} back
                          <span className="block text-xs text-muted">
                            brine waits up to {shown.catch_up_days} days and you can cancel it from the job page.
                            Nothing changes on the master: it's brine that remembers and runs it.
                          </span>
                        </span>
                      </label>
                    )}
                    {run.isError && (
                      <p role="alert" className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm">
                        {run.error.message}
                      </p>
                    )}
                    {canRun && !run.data && (
                      <div className="flex items-center justify-end gap-3">
                        <span className="text-xs text-muted">Recorded in the audit log.</span>
                        <button
                          type="button"
                          onClick={start}
                          disabled={run.isPending}
                          className="h-10 rounded-lg bg-accent px-4 text-sm font-medium text-accent-fg disabled:opacity-50"
                        >
                          {run.isPending
                            ? shown.client === 'local'
                              ? 'Starting…'
                              : 'Waiting for the master…'
                            : shown.client === 'local'
                              ? `Run on ${shown.minions.length} minion${shown.minions.length === 1 ? '' : 's'}`
                              : 'Run on the master'}
                        </button>
                      </div>
                    )}
                  </div>
                )
              )}
            </Card>
          )}

          {run.data && run.data.client !== 'local' && (
            <Card className="overflow-hidden">
              <div className="flex items-center justify-between border-b px-4 py-3 sm:px-6">
                <h2 className="font-medium">Result</h2>
                {run.data.success === false && <Badge tone="danger">Failed</Badge>}
              </div>
              <div className="overflow-x-auto p-4 font-mono text-sm sm:px-6">
                <JsonTree value={run.data.result} expandDepth={2} />
              </div>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-4 sm:gap-6">
          <Templates onPick={pick} />
          <Card className="h-fit overflow-hidden">
            <h2 className="flex items-center gap-2 border-b px-4 py-3 font-medium">
              <TerminalSquare className="size-4 text-muted" aria-hidden />
              Recent
            </h2>
            {history.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted">
                Commands you run show up here (in this browser only). Results are on the{' '}
                <Link to="/jobs" className="text-accent hover:underline">
                  Jobs
                </Link>{' '}
                page.
              </p>
            ) : (
              <ul>
                {history.map((h) => (
                  <li key={`${h.target_type}:${h.target}:${h.command}`} className="border-b last:border-b-0">
                    <button
                      type="button"
                      onClick={() => fill(h)}
                      className="w-full px-4 py-2.5 text-left hover:bg-surface-2"
                    >
                      <div className="truncate font-mono text-sm">{h.command}</div>
                      <div className="truncate text-xs text-muted">{h.target ? `${h.target} (${h.target_type})` : 'master'}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
