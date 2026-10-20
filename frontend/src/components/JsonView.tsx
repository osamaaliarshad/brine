import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'

function isContainer(value: unknown): value is Record<string, unknown> | unknown[] {
  return typeof value === 'object' && value !== null
}

function Scalar({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted">null</span>
  if (typeof value === 'string') return <span className="break-all">{value}</span>
  if (typeof value === 'boolean') return <span className="text-accent">{String(value)}</span>
  return <span className="tabular-nums">{String(value)}</span>
}

function summary(value: Record<string, unknown> | unknown[]): string {
  const n = Array.isArray(value) ? value.length : Object.keys(value).length
  return Array.isArray(value) ? `[ ${n} item${n === 1 ? '' : 's'} ]` : `{ ${n} key${n === 1 ? '' : 's'} }`
}

const AUTO_OPEN_MAX_ENTRIES = 12

/**
 * A collapsible tree for nested Salt data (grains, pillar, job returns). Levels shallower than
 * `expandDepth` start open, unless they're long (a 100-item cpu_flags list stays folded).
 */
export function JsonTree({
  value,
  depth = 0,
  expandDepth = 1,
}: {
  value: unknown
  depth?: number
  expandDepth?: number
}) {
  const size = isContainer(value) ? Object.keys(value).length : 0
  const [expanded, setExpanded] = useState(depth < expandDepth && size <= AUTO_OPEN_MAX_ENTRIES)
  if (!isContainer(value)) return <Scalar value={value} />
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((v, i) => [String(i), v])
    : Object.entries(value)
  if (entries.length === 0) return <span className="text-muted">{Array.isArray(value) ? '[]' : '{}'}</span>
  // Short lists of plain values read best inline.
  if (Array.isArray(value) && value.length <= 8 && value.every((v) => !isContainer(v))) {
    return <span className="break-all">{value.map((v) => String(v)).join(', ')}</span>
  }
  return (
    <div className="font-mono text-[13px]">
      <button
        type="button"
        className="inline-flex items-center gap-1 text-muted hover:text-fg"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <ChevronRight className={cn('size-3.5 transition-transform', expanded && 'rotate-90')} aria-hidden />
        {summary(value)}
      </button>
      {expanded && (
        <dl className="mt-1 ml-1.5 border-l pl-3">
          {entries.map(([key, child]) => (
            <div key={key} className="flex gap-2 py-0.5">
              <dt className="shrink-0 text-muted">{key}:</dt>
              <dd className="min-w-0">
                <JsonTree value={child} depth={depth + 1} expandDepth={expandDepth} />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
