import type { RouteObject } from 'react-router'
import { AppShell } from '@/components/AppShell'
import {
  EventsPage,
  FleetPage,
  IssuesPage,
  JobsPage,
  KeysPage,
  NotFoundPage,
  SettingsPage,
} from '@/pages'

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <FleetPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'keys', element: <KeysPage /> },
      { path: 'events', element: <EventsPage /> },
      { path: 'issues', element: <IssuesPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
