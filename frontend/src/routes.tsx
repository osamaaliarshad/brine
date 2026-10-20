import type { RouteObject } from 'react-router'
import { AppShell } from '@/components/AppShell'
import {
  IssuesPage,
  NotFoundPage,
  SettingsPage,
} from '@/pages'
import { FleetPage } from '@/pages/fleet/FleetPage'
import { EventsPage } from '@/pages/events/EventsPage'
import { JobPage } from '@/pages/jobs/JobPage'
import { KeysPage } from '@/pages/keys/KeysPage'
import { JobsPage } from '@/pages/jobs/JobsPage'
import { MinionPage } from '@/pages/minion/MinionPage'

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <FleetPage /> },
      { path: 'minions/:id', element: <MinionPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'jobs/:jid', element: <JobPage /> },
      { path: 'keys', element: <KeysPage /> },
      { path: 'events', element: <EventsPage /> },
      { path: 'issues', element: <IssuesPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
