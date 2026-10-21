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
    // The bottom line is an inset shadow, not a border the tabs overlap: an overlap would stick
    // out of this scroll container and show a pointless vertical scrollbar.
    <div
      role="tablist"
      aria-label={label}
      className="flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--border)]"
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={tab.key === active}
          onClick={() => onSelect(tab.key)}
          className={cn(
            'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm transition-colors',
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
