import { LogIn } from 'lucide-react'
import { Navigate, useSearchParams } from 'react-router'
import { useAuthInfo } from '@/api/queries'
import { Logo } from '@/components/Logo'
import { Card } from '@/components/ui'

const ERRORS: Record<string, string> = {
  denied:
    "That account doesn't have access to brine. Ask an admin to add it under roles in brine's config.",
  unverified: "Your sign-in provider didn't confirm that email address, so brine can't use it.",
  failed: "Sign-in didn't complete. Please try again.",
}

/** Only same-site paths, mirroring the server's check. */
function safeNext(value: string | null): string {
  return value && value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') ? value : '/'
}

export function LoginPage() {
  const [params] = useSearchParams()
  const info = useAuthInfo()
  const next = safeNext(params.get('next'))
  const error = params.get('error')

  if (info.data?.provider === 'none') return <Navigate to={next} replace />

  return (
    <main className="flex min-h-full items-center justify-center bg-bg px-4 py-12">
      <Card className="w-full max-w-sm px-8 py-10 text-center">
        <Logo className="mx-auto h-12" />
        <h1 className="mt-6 text-xl font-semibold">Sign in to brine</h1>
        <p className="mt-1 text-sm text-muted">Your Salt fleet, at a glance.</p>
        {error && (
          <p role="alert" className="mt-6 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-left text-sm">
            {ERRORS[error] ?? ERRORS.failed}
          </p>
        )}
        <a
          href={`/api/auth/login?next=${encodeURIComponent(next)}`}
          aria-disabled={!info.data}
          className="mt-8 flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent font-medium text-accent-fg transition-opacity hover:opacity-90"
        >
          <LogIn className="size-4" aria-hidden />
          Sign in with {info.data?.display_name ?? '…'}
        </a>
        {info.isError && <p className="mt-4 text-sm text-danger">Can't reach the brine server.</p>}
      </Card>
    </main>
  )
}
