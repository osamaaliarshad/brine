import {
  CalendarClock,
  FileCode,
  History,
  KeyRound,
  LayoutGrid,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  ScrollText,
  Settings,
  Sun,
  TerminalSquare,
  TriangleAlert,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { useLiveUpdates } from '@/api/live'
import { attentionCount, useCapabilities, useIssues, useMe } from '@/api/queries'
import type { User } from '@/api/types'
import { UserMenu } from '@/components/UserMenu'
import { Wordmark } from '@/components/Wordmark'
import { cn } from '@/lib/cn'
import { getTheme, onThemeChange, setTheme, type Theme } from '@/lib/theme'

type NavItem = { to: string; label: string; icon: LucideIcon }

const MAIN_NAV: NavItem[] = [
  { to: '/', label: 'Fleet', icon: LayoutGrid },
  { to: '/jobs', label: 'Jobs', icon: Play },
  { to: '/events', label: 'Events', icon: ScrollText },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
]

const CONFIG_NAV: NavItem[] = [
  { to: '/states', label: 'States', icon: FileCode },
  { to: '/automation', label: 'Automation', icon: CalendarClock },
  { to: '/keys', label: 'Keys', icon: KeyRound },
]

const AUDIT_NAV: NavItem = { to: '/audit', label: 'Audit log', icon: History }
const RUN_NAV: NavItem = { to: '/run', label: 'Run', icon: TerminalSquare }

const COLLAPSED_KEY = 'brine-sidebar-collapsed'

const ROW =
  'relative flex items-center gap-3 rounded-lg py-2.5 text-[15px] text-muted transition-colors hover:bg-surface-2 hover:text-fg'

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

function NavRow({
  item,
  onNavigate,
  badge,
  collapsed = false,
}: {
  item: NavItem
  onNavigate?: () => void
  badge?: number
  collapsed?: boolean
}) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          ROW,
          collapsed ? 'justify-center px-0' : 'px-3',
          isActive &&
            'bg-surface-2 text-fg before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-accent',
        )
      }
    >
      <Icon className="size-5 shrink-0" strokeWidth={1.75} aria-hidden />
      <span className={cn(collapsed && 'sr-only')}>{item.label}</span>
      {!!badge &&
        (collapsed ? (
          <span
            className="absolute top-1.5 right-2.5 size-2 rounded-full bg-warn"
            aria-label={`${badge} need attention`}
          />
        ) : (
          <span
            className="ml-auto rounded-full bg-warn/15 px-2 py-0.5 text-xs font-medium text-warn tabular-nums"
            aria-label={`${badge} need attention`}
          >
            {badge}
          </span>
        ))}
    </NavLink>
  )
}

function ThemeToggle({ collapsed }: { collapsed: boolean }) {
  const [theme, setThemeState] = useState<Theme>(getTheme)
  // Settings can change the theme too; keep the toggle's label in step.
  useEffect(() => onThemeChange(() => setThemeState(getTheme())), [])
  const next: Theme = theme === 'dark' ? 'light' : 'dark'
  const label = theme === 'dark' ? 'Light theme' : 'Dark theme'
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className={cn(ROW, 'w-full', collapsed ? 'justify-center px-0' : 'px-3')}
      aria-label={`Switch to ${next} theme`}
      title={collapsed ? label : undefined}
    >
      {theme === 'dark' ? (
        <Sun className="size-5 shrink-0" strokeWidth={1.75} />
      ) : (
        <Moon className="size-5 shrink-0" strokeWidth={1.75} />
      )}
      {!collapsed && label}
    </button>
  )
}

function Sidebar({
  onNavigate,
  collapsed = false,
  onToggleCollapsed,
  user,
}: {
  onNavigate?: () => void
  collapsed?: boolean
  user: User | undefined
  /** Only the desktop sidebar can collapse; the phone drawer is always full width. */
  onToggleCollapsed?: () => void
}) {
  const attention = attentionCount(useIssues().data)
  // Run sits under Jobs, for people whose role may run something.
  const mayRun = !!user && user.role !== 'viewer'
  const canRun = !!useCapabilities(mayRun).data?.commands.length
  const mainNav = canRun ? [...MAIN_NAV.slice(0, 2), RUN_NAV, ...MAIN_NAV.slice(2)] : MAIN_NAV
  const toggle = onToggleCollapsed && (
    <button
      type="button"
      onClick={onToggleCollapsed}
      className="rounded-lg p-2 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
      aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      title={`${collapsed ? 'Expand' : 'Collapse'} sidebar ( [ )`}
    >
      {collapsed ? (
        <PanelLeftOpen className="size-5" strokeWidth={1.75} />
      ) : (
        <PanelLeftClose className="size-5" strokeWidth={1.75} />
      )}
    </button>
  )
  return (
    <div className={cn('flex h-full flex-col gap-6 py-6', collapsed ? 'px-2' : 'px-3')}>
      {collapsed ? (
        <div className="flex flex-col items-center gap-3">
          <Wordmark mark className="h-9" />
          {toggle}
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2 pl-3">
          <Wordmark className="h-10" />
          {toggle}
        </div>
      )}
      <nav aria-label="Main" className="flex flex-col gap-1">
        {mainNav.map((item) => (
          <NavRow
            key={item.to}
            item={item}
            onNavigate={onNavigate}
            collapsed={collapsed}
            badge={item.to === '/issues' ? attention : undefined}
          />
        ))}
        {collapsed ? (
          <hr className="mx-3 my-2" />
        ) : (
          <div className="mt-4 mb-1 px-3 text-xs font-medium uppercase tracking-wider text-muted">
            Configuration
          </div>
        )}
        {CONFIG_NAV.map((item) => (
          <NavRow key={item.to} item={item} onNavigate={onNavigate} collapsed={collapsed} />
        ))}
        {user?.role === 'admin' && (
          <NavRow item={AUDIT_NAV} onNavigate={onNavigate} collapsed={collapsed} />
        )}
      </nav>
      <div className="mt-auto flex flex-col gap-1">
        <ThemeToggle collapsed={collapsed} />
        <NavRow
          item={{ to: '/settings', label: 'Settings', icon: Settings }}
          onNavigate={onNavigate}
          collapsed={collapsed}
        />
        {user && (
          <div className="mt-2 border-t pt-2">
            <UserMenu user={user} collapsed={collapsed} />
          </div>
        )}
      </div>
    </div>
  )
}

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  )
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(loadCollapsed)
  const user = useMe().data
  useLiveUpdates()

  const toggleCollapsed = () =>
    setCollapsed((was) => {
      const next = !was
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        // storage unavailable: lasts for this page load only
      }
      return next
    })

  // "[" toggles the sidebar, unless you're typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === '[' && !event.ctrlKey && !event.metaKey && !event.altKey && !isTyping(event.target)) {
        toggleCollapsed()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex h-full">
      <aside
        className={cn(
          'hidden shrink-0 border-r bg-surface/40 transition-[width] duration-200 lg:block',
          collapsed ? 'w-[72px]' : 'w-64',
        )}
      >
        <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} user={user} />
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
            <Sidebar onNavigate={() => setMobileOpen(false)} user={user} />
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
          {user?.provider === 'none' && (
            <div
              role="note"
              className="mb-6 rounded-xl border border-warn/40 bg-warn/10 px-4 py-2.5 text-sm"
            >
              <span className="font-medium">Sign-in is off.</span>{' '}
              <span className="text-muted">
                Everyone who can open brine is treated as {user.role}. Fine for the demo; set up
                sign-in (docs/oidc-providers.md) for anything real.
              </span>
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
