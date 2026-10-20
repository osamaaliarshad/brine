import { Link, useParams } from 'react-router'
import { ComingSoon, PageHeader } from '@/components/PageHeader'

// Placeholder pages. Each moves to its own file as it gets built out.

export function JobsPage() {
  return (
    <>
      <PageHeader title="Jobs" subtitle="Every job, kept longer than the master's cache." />
      <ComingSoon phase="Phase 3" />
    </>
  )
}

export function KeysPage() {
  return (
    <>
      <PageHeader title="Keys" subtitle="Minion keys and their acceptance state." />
      <ComingSoon phase="Phase 3" />
    </>
  )
}

export function EventsPage() {
  return (
    <>
      <PageHeader title="Events" subtitle="The live Salt event bus." />
      <ComingSoon phase="Phase 3" />
    </>
  )
}

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

export function MinionPage() {
  const { id = '' } = useParams()
  return (
    <>
      <PageHeader title={id} subtitle="Grains, presence timeline, and recent jobs." />
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
