import { Link, isRouteErrorResponse, useRouteError } from 'react-router'
import { Card } from '@/components/ui'

/** Shown instead of a page (or the whole app) that crashed while rendering. */
export function ErrorPage() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : String(error)

  return (
    <div className="mx-auto w-full max-w-xl py-12">
      <Card className="px-6 py-8">
        <h1 className="text-xl font-semibold">Something went wrong on this page</h1>
        <p className="mt-2 text-sm text-muted">
          brine hit a bug showing it. Reloading usually helps; if it keeps happening, the details below help track it
          down.
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-surface-2 px-3 py-2 font-mono text-[13px] whitespace-pre-wrap">
          {message}
        </pre>
        <div className="mt-6 flex gap-2">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="h-10 rounded-lg bg-accent px-4 text-sm font-medium text-accent-fg"
          >
            Reload
          </button>
          <Link to="/" reloadDocument className="flex h-10 items-center rounded-lg border px-4 text-sm hover:bg-surface-2">
            Back to the fleet
          </Link>
        </div>
      </Card>
    </div>
  )
}
