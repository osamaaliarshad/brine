import { ChevronRight, FileCode, Folder, Search } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { buildTree, countFiles, type TreeFolder } from '@/pages/states/tree'

/** The folders a file sits in: "a/b/c.sls" -> ["a", "a/b"]. */
function ancestors(path: string | null): string[] {
  const parts = path?.split('/').slice(0, -1) ?? []
  return parts.map((_, i) => parts.slice(0, i + 1).join('/'))
}

const ROW = 'flex w-full items-center gap-1.5 py-1.5 pr-3 text-left font-mono text-[13px] hover:bg-surface-2'
const indent = (depth: number) => ({ paddingLeft: `${0.75 + depth * 0.9}rem` })

export function FileTree({
  paths,
  selected,
  onOpen,
}: {
  paths: string[]
  selected: string | null
  onOpen: (path: string) => void
}) {
  const [open, setOpen] = useState(() => new Set(ancestors(selected)))
  const [filter, setFilter] = useState('')
  const toggle = (path: string) =>
    setOpen((was) => {
      const next = new Set(was)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })

  const file = (path: string, depth: number, label: string) => (
    <li key={path}>
      <button
        type="button"
        onClick={() => onOpen(path)}
        aria-current={path === selected ? 'true' : undefined}
        title={path}
        className={cn(ROW, path === selected && 'bg-surface-2 text-accent')}
        style={indent(depth)}
      >
        <FileCode className="size-3.5 shrink-0 text-muted" aria-hidden />
        <span className="truncate">{label}</span>
      </button>
    </li>
  )

  const folder = (node: TreeFolder, depth: number) => {
    const expanded = open.has(node.path)
    return (
      <li key={node.path}>
        <button type="button" onClick={() => toggle(node.path)} aria-expanded={expanded} className={ROW} style={indent(depth)}>
          <ChevronRight className={cn('size-3.5 shrink-0 text-muted transition-transform', expanded && 'rotate-90')} aria-hidden />
          <Folder className="size-3.5 shrink-0 text-muted" aria-hidden />
          <span className="truncate">{node.name}</span>
          <span className="ml-auto pl-2 font-sans text-xs text-muted tabular-nums">{countFiles(node)}</span>
        </button>
        {expanded && <ul>{children(node, depth + 1)}</ul>}
      </li>
    )
  }

  const children = (node: TreeFolder, depth: number) => [
    ...node.folders.map((f) => folder(f, depth)),
    ...node.files.map((p) => file(p, depth + (node.path ? 0.6 : 0), p.split('/').at(-1)!)),
  ]

  const query = filter.trim().toLowerCase()
  const matches = query ? paths.filter((p) => p.toLowerCase().includes(query)) : []

  return (
    <div className="flex min-h-0 flex-col">
      <label className="mx-3 my-2 flex h-9 items-center gap-2 rounded-lg border bg-bg px-2.5">
        <Search className="size-3.5 shrink-0 text-muted" aria-hidden />
        <input
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter files…"
          aria-label="Filter files"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
        />
      </label>
      <ul aria-label="State files" className="min-h-0 flex-1 overflow-y-auto pb-2">
        {query ? (
          matches.length ? (
            matches.map((p) => file(p, 0, p))
          ) : (
            <li className="px-4 py-3 text-sm text-muted">No files match.</li>
          )
        ) : (
          children(buildTree(paths), 0)
        )}
      </ul>
    </div>
  )
}
