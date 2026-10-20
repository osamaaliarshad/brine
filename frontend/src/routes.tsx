import type { RouteObject } from 'react-router'
import { AppShell } from '@/components/AppShell'
import {
  EventsPage,
  IssuesPage,
  JobsPage,
  KeysPage,
  NotFoundPage,
  SettingsPage,
} from '@/pages'
import { FleetPage } from '@/pages/fleet/FleetPage'
import { MinionPage } from '@/pages/minion/MinionPage'

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <FleetPage /> },
      { path: 'minions/:id', element: <MinionPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'keys', element: <KeysPage /> },
      { path: 'events', element: <EventsPage /> },
      { path: 'issues', element: <IssuesPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
