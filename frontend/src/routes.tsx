import type { RouteObject } from 'react-router'
import { AppShell } from '@/components/AppShell'
import { AutomationPage } from '@/pages/automation/AutomationPage'
import { EventsPage } from '@/pages/events/EventsPage'
import { FleetPage } from '@/pages/fleet/FleetPage'
import { IssuesPage } from '@/pages/issues/IssuesPage'
import { JobPage } from '@/pages/jobs/JobPage'
import { JobsPage } from '@/pages/jobs/JobsPage'
import { KeysPage } from '@/pages/keys/KeysPage'
import { MinionPage } from '@/pages/minion/MinionPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { StatesPage } from '@/pages/states/StatesPage'

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <FleetPage /> },
      { path: 'minions/:id', element: <MinionPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'jobs/:jid', element: <JobPage /> },
      { path: 'keys', element: <KeysPage /> },
      { path: 'states', element: <StatesPage /> },
      { path: 'automation', element: <AutomationPage /> },
      { path: 'events', element: <EventsPage /> },
      { path: 'issues', element: <IssuesPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
