import { Link } from 'react-router'
import { ComingSoon, PageHeader } from '@/components/PageHeader'

// Placeholder pages. Each moves to its own file as it gets built out.

export function IssuesPage() {
  return (
    <>
      <PageHeader title="Issues" subtitle="Things in the fleet that need attention." />
      <ComingSoon phase="Phase 3" />
    </>
  )
}

export function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" />
      <ComingSoon phase="Phase 3" />
    </>
  )
}

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Not found" subtitle="That page doesn't exist." />
      <Link to="/" className="text-accent hover:underline">
        Back to the fleet
      </Link>
    </>
  )
}
