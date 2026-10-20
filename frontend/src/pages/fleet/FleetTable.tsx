import { ChevronDown, ChevronLeft, ChevronRight, ChevronsUpDown, ChevronUp } from 'lucide-react'
import type { ReactNode } from 'react'
import type { MinionSummary } from '@/api/types'
import { cn } from '@/lib/cn'
import type { TableColumn } from '@/pages/fleet/columns'
import type { FleetView, SortKey } from '@/pages/fleet/model'

function SortHeader({ column, view, onSort }: {
  column: TableColumn
  view: FleetView
  onSort: (key: SortKey) => void
}) {
  const active = view.sort === column.key
  const Icon = !active ? ChevronsUpDown : view.dir === 'asc' ? ChevronUp : ChevronDown
  return (
    <th
      scope="col"
      aria-sort={active ? (view.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="whitespace-nowrap px-4 py-3 text-left first:pl-6"
    >
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className={cn(
          'inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wider hover:text-fg',
          active ? 'text-fg' : 'text-muted',
        )}
      >
        {column.label}
        <Icon className={cn('size-3.5', active ? 'text-accent' : 'opacity-60')} aria-hidden />
      </button>
    </th>
  )
}

function pageList(page: number, pages: number): (number | '…')[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1)
  const near = [page - 1, page, page + 1].filter((p) => p > 1 && p < pages)
  const list: (number | '…')[] = [1]
  if (near[0]! > 2) list.push('…')
  list.push(...near)
  if (near[near.length - 1]! < pages - 1) list.push('…')
  list.push(pages)
  return list
}

function Pagination({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  const btn = 'flex size-9 items-center justify-center rounded-lg border text-sm tabular-nums'
  return (
    <nav aria-label="Pages" className="flex items-center gap-1.5">
      <button
        type="button"
        className={cn(btn, 'hover:bg-surface-2 disabled:opacity-40')}
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        aria-label="Previous page"
      >
        <ChevronLeft className="size-4" />
      </button>
      {pageList(page, pages).map((p, i) =>
        p === '…' ? (
          <span key={`gap-${i}`} className="px-1 text-muted">
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onPage(p)}
            aria-current={p === page ? 'page' : undefined}
            className={cn(
              btn,
              p === page
                ? 'border-accent bg-accent font-medium text-accent-fg'
                : 'border-transparent text-muted hover:bg-surface-2 hover:text-fg',
            )}
          >
            {p}
          </button>
        ),
      )}
      <button
        type="button"
        className={cn(btn, 'hover:bg-surface-2 disabled:opacity-40')}
        disabled={page >= pages}
        onClick={() => onPage(page + 1)}
        aria-label="Next page"
      >
        <ChevronRight className="size-4" />
      </button>
    </nav>
  )
}

export function FleetTable({
  columns,
  minions,
  view,
  now,
  total,
  page,
  pages,
  pageSize,
  onSort,
  onPage,
  empty,
  loading = false,
}: {
  columns: TableColumn[]
  minions: MinionSummary[]
  view: FleetView
  now: number
  total: number
  page: number
  pages: number
  pageSize: number
  onSort: (key: SortKey) => void
  onPage: (page: number) => void
  empty: ReactNode
  loading?: boolean
}) {
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(total, page * pageSize)
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse">
          <thead className="bg-surface-2/40">
            <tr>
              {columns.map((column) => (
                <SortHeader key={column.key} column={column} view={view} onSort={onSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {minions.map((m) => (
              <tr key={m.id} className="border-t align-middle transition-colors hover:bg-surface-2/40">
                {columns.map((column) => (
                  <td key={column.key} className="whitespace-nowrap px-4 py-3.5 first:pl-6">
                    {column.render(m, now)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {minions.length === 0 && <div className="border-t px-6 py-12 text-center text-muted">{empty}</div>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 sm:px-6">
        <span className="text-sm text-muted">
          {loading ? ' ' : total === 0 ? 'No minions' : `Showing ${first}–${last} of ${total} minions`}
        </span>
        {pages > 1 && <Pagination page={page} pages={pages} onPage={onPage} />}
      </div>
    </>
  )
}
