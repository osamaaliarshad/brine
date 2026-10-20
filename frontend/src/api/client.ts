export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(path, { headers: { Accept: 'application/json' }, ...init })
  } catch {
    throw new ApiError(0, "Can't reach the brine server.")
  }
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
  return (await resp.json()) as T
}
