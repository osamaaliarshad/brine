import type { RouteObject } from 'react-router'
import { AppShell } from '@/components/AppShell'
import { AuditPage } from '@/pages/audit/AuditPage'
import { AutomationPage } from '@/pages/automation/AutomationPage'
import { ErrorPage } from '@/pages/ErrorPage'
import { EventsPage } from '@/pages/events/EventsPage'
import { FleetPage } from '@/pages/fleet/FleetPage'
import { IssuesPage } from '@/pages/issues/IssuesPage'
import { JobPage } from '@/pages/jobs/JobPage'
import { JobsPage } from '@/pages/jobs/JobsPage'
import { KeysPage } from '@/pages/keys/KeysPage'
import { RunPage } from '@/pages/run/RunPage'
import { LoginPage } from '@/pages/LoginPage'
import { MinionPage } from '@/pages/minion/MinionPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { StatesPage } from '@/pages/states/StatesPage'

export const routes: RouteObject[] = [
  { path: 'login', element: <LoginPage /> },
  {
    element: <AppShell />,
    // The shell itself failed: the error page on its own.
    errorElement: (
      <main className="min-h-full bg-bg px-4">
        <ErrorPage />
      </main>
    ),
    children: [
      {
        // A page failed: keep the sidebar so the rest of brine is a click away.
        errorElement: <ErrorPage />,
        children: [
      { index: true, element: <FleetPage /> },
      { path: 'minions/:id', element: <MinionPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'jobs/:jid', element: <JobPage /> },
      { path: 'keys', element: <KeysPage /> },
      { path: 'run', element: <RunPage /> },
      { path: 'states', element: <StatesPage /> },
      { path: 'automation', element: <AutomationPage /> },
      { path: 'events', element: <EventsPage /> },
      { path: 'issues', element: <IssuesPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'audit', element: <AuditPage /> },
      { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
