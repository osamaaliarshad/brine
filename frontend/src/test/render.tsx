import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import type { Fleet, MinionSummary, SystemStatus } from '@/api/types'
import { routes } from '@/routes'

export const NOW = Date.parse('2026-10-20T12:00:00Z')
export const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString()

export function minion(id: string, patch: Partial<MinionSummary> = {}): MinionSummary {
  return {
    id,
    status: 'online',
    connected: true,
    last_seen_at: ago(10),
    key_state: 'accepted',
    os: 'Debian 12',
    salt_version: '3006.28',
    ip: '10.0.0.1',
    grains_at: ago(240),
    grains_source: 'minion',
    columns: { site: 'site-a', app_version: '2.4.1' },
    ...patch,
  }
}

export const DEFAULT_COLUMNS = [
  { grain: 'site', label: 'Site' },
  { grain: 'app_version', label: 'App version' },
]

export function fleet(minions: MinionSummary[], patch: Partial<Fleet> = {}): Fleet {
  const count = (s: MinionSummary['status']) => minions.filter((m) => m.status === s).length
  return {
    summary: {
      total: minions.length,
      online: count('online'),
      offline: count('offline'),
      stale: count('stale'),
      unknown: count('unknown'),
      pending_keys: 0,
    },
    columns: DEFAULT_COLUMNS,
    default_columns: DEFAULT_COLUMNS,
    presence: { method: 'events', checked_at: ago(20) },
    minions,
    ...patch,
  }
}

export function systemStatus(patch: Partial<SystemStatus['salt_api']> = {}): SystemStatus {
  return {
    version: 'dev',
    salt_api: {
      url: 'http://salt.test:8000/',
      connected: true,
      since: ago(600),
      error: null,
      last_event_at: ago(5),
      ...patch,
    },
    presence_method_configured: 'auto',
    presence: { method: 'events', checked_at: ago(20) },
    stale_after_minutes: 15,
  }
}

type Responder = unknown | ((url: URL) => unknown)

/**
 * Stub fetch with a pathname -> response map; anything else 404s. A response can be a function
 * of the full URL, to answer differently per query string.
 */
export function mockApi(responses: Record<string, Responder>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://brine.test')
    if (url.pathname in responses) {
      const responder = responses[url.pathname]
      const body = typeof responder === 'function' ? (responder as (u: URL) => unknown)(url) : responder
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export function renderApp(path = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { queryClient, router }
}
