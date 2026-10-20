import {
  KeyRound,
  LayoutGrid,
  Menu,
  Moon,
  Play,
  ScrollText,
  Settings,
  Sun,
  TriangleAlert,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { useLiveUpdates } from '@/api/live'
import { attentionCount, useIssues } from '@/api/queries'
import { Wordmark } from '@/components/Wordmark'
import { cn } from '@/lib/cn'
import { getTheme, onThemeChange, setTheme, type Theme } from '@/lib/theme'

type NavItem = { to: string; label: string; icon: LucideIcon }

const MAIN_NAV: NavItem[] = [
  { to: '/', label: 'Fleet', icon: LayoutGrid },
  { to: '/jobs', label: 'Jobs', icon: Play },
  { to: '/keys', label: 'Keys', icon: KeyRound },
  { to: '/events', label: 'Events', icon: ScrollText },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
]

function NavRow({ item, onNavigate, badge }: { item: NavItem; onNavigate?: () => void; badge?: number }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] text-muted transition-colors hover:bg-surface-2 hover:text-fg',
          isActive &&
            'bg-surface-2 text-fg before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-accent',
        )
      }
    >
      <Icon className="size-5" strokeWidth={1.75} aria-hidden />
      {item.label}
      {!!badge && (
        <span className="ml-auto rounded-full bg-warn/15 px-2 py-0.5 text-xs font-medium text-warn tabular-nums" aria-label={`${badge} need attention`}>
          {badge}
        </span>
      )}
    </NavLink>
  )
}

function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(getTheme)
  // Settings can change the theme too; keep the toggle's label in step.
  useEffect(() => onThemeChange(() => setThemeState(getTheme())), [])
  const next: Theme = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] text-muted transition-colors hover:bg-surface-2 hover:text-fg"
      aria-label={`Switch to ${next} theme`}
    >
      {theme === 'dark' ? <Sun className="size-5" strokeWidth={1.75} /> : <Moon className="size-5" strokeWidth={1.75} />}
      {theme === 'dark' ? 'Light theme' : 'Dark theme'}
    </button>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const attention = attentionCount(useIssues().data)
  return (
    <div className="flex h-full flex-col gap-6 px-3 py-6">
      <Wordmark className="mx-auto h-10" />
      <nav aria-label="Main" className="flex flex-col gap-1">
        {MAIN_NAV.map((item) => (
          <NavRow
            key={item.to}
            item={item}
            onNavigate={onNavigate}
            badge={item.to === '/issues' ? attention : undefined}
          />
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-1">
        <ThemeToggle />
        <NavRow item={{ to: '/settings', label: 'Settings', icon: Settings }} onNavigate={onNavigate} />
      </div>
    </div>
  )
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false)
  useLiveUpdates()

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 border-r bg-surface/40 lg:block">
        <Sidebar />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/50"
            aria-label="Close menu"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-surface">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b px-4 py-3 lg:hidden">
          <button
            type="button"
            className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg"
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            onClick={() => setMobileOpen((open) => !open)}
          >
            {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
          <Wordmark className="h-6" />
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
