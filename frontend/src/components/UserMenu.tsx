import { ChevronUp, LogOut } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { signOut } from '@/api/client'
import type { User } from '@/api/types'
import { cn } from '@/lib/cn'
import { initials } from '@/lib/initials'

const ROLE_LABEL = { viewer: 'Viewer', operator: 'Operator', admin: 'Admin' } as const

/** Who's signed in, at the bottom of the sidebar (like the mockup), with Sign out. */
export function UserMenu({ user, collapsed }: { user: User; collapsed: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent | KeyboardEvent) => {
      const outside =
        event instanceof KeyboardEvent ? event.key === 'Escape' : !ref.current?.contains(event.target as Node)
      if (outside) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const avatar = (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent/20 text-sm font-semibold text-accent">
      {initials(user.name)}
    </span>
  )

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Account: ${user.name}`}
        title={collapsed ? `${user.name} (${ROLE_LABEL[user.role]})` : undefined}
        className={cn(
          'flex w-full items-center gap-3 rounded-lg py-2 text-left transition-colors hover:bg-surface-2',
          collapsed ? 'justify-center px-0' : 'px-2',
        )}
      >
        {avatar}
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{user.name}</span>
              <span className="block text-xs text-muted">{ROLE_LABEL[user.role]}</span>
            </span>
            <ChevronUp className={cn('size-4 text-muted transition-transform', !open && 'rotate-180')} aria-hidden />
          </>
        )}
      </button>
      {open && (
        <div
          role="menu"
          className={cn(
            'absolute bottom-full z-30 mb-2 w-60 rounded-xl border bg-surface p-2 shadow-xl',
            collapsed ? 'left-0' : 'inset-x-0 w-auto',
          )}
        >
          <div className="px-2 py-1.5">
            <div className="truncate text-sm font-medium">{user.name}</div>
            {user.provider === 'oidc' && <div className="truncate text-xs text-muted">{user.email}</div>}
            <div className="mt-1 text-xs text-muted">Role: {ROLE_LABEL[user.role]}</div>
          </div>
          {user.provider === 'oidc' && (
            <button
              type="button"
              role="menuitem"
              onClick={() => void signOut()}
              className="mt-1 flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-surface-2"
            >
              <LogOut className="size-4" aria-hidden />
              Sign out
            </button>
          )}
        </div>
      )}
    </div>
  )
}
