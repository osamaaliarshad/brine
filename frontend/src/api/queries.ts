import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { Fleet, SystemStatus } from '@/api/types'

export const queryKeys = {
  fleet: ['fleet'] as const,
  status: ['status'] as const,
  minion: (id: string) => ['minion', id] as const,
  jobs: ['jobs'] as const,
}

export function useFleet() {
  return useQuery({ queryKey: queryKeys.fleet, queryFn: () => fetchJson<Fleet>('/api/fleet') })
}

export function useSystemStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: () => fetchJson<SystemStatus>('/api/status'),
  })
}
