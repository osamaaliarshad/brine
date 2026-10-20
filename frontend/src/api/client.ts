export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Sent with every request; the server refuses writes without it (CSRF). */
const CSRF_HEADERS = { 'X-Requested-With': 'brine' }

function goToLogin() {
  if (window.location.pathname === '/login') return
  const next = window.location.pathname + window.location.search
  window.location.assign(`/login?next=${encodeURIComponent(next)}`)
}

/** What happens when the server says "sign in first". Tests swap this out. */
let onUnauthorized: () => void = goToLogin

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(path, {
      ...init,
      headers: { Accept: 'application/json', ...CSRF_HEADERS, ...init?.headers },
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError(0, "Can't reach the brine server.")
  }
  if (resp.status === 401) onUnauthorized()
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = (await resp.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(resp.status, detail || `Request failed (${resp.status})`)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return fetchJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function signOut(): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin', headers: CSRF_HEADERS })
  } finally {
    window.location.assign('/login')
  }
}
