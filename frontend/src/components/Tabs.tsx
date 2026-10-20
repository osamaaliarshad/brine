import { cn } from '@/lib/cn'
import type { TabDef } from '@/lib/useTab'

export function Tabs<K extends string>({
  tabs,
  active,
  onSelect,
  label,
}: {
  tabs: readonly TabDef<K>[]
  active: K
  onSelect: (key: K) => void
  label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={tab.key === active}
          onClick={() => onSelect(tab.key)}
          className={cn(
            '-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm transition-colors',
            tab.key === active
              ? 'border-accent font-medium text-fg'
              : 'border-transparent text-muted hover:text-fg',
          )}
        >
          {tab.label}
          {tab.badge}
        </button>
      ))}
    </div>
  )
}
