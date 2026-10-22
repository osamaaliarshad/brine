import { Link } from 'react-router'
import { PageHeader } from '@/components/PageHeader'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Not found" subtitle="That page doesn't exist." />
      <Link to="/" className="self-start text-accent hover:underline">
        Back to the fleet
      </Link>
    </>
  )
}
