import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { Fleet, GrainKey, SystemStatus } from '@/api/types'

export const queryKeys = {
  fleet: ['fleet'] as const,
  status: ['status'] as const,
  grainKeys: ['grain-keys'] as const,
  minion: (id: string) => ['minion', id] as const,
  jobs: ['jobs'] as const,
}

/** `/api/fleet`, with `?column=` for each grain when the user picked their own columns. */
export function fleetUrl(grains: string[] | null): string {
  if (grains === null) return '/api/fleet'
  const params = new URLSearchParams()
  // An explicit empty value means "no grain columns", not "the defaults".
  for (const grain of grains.length ? grains : ['']) params.append('column', grain)
  return `/api/fleet?${params}`
}

export function useFleet(grains: string[] | null = null) {
  return useQuery({
    queryKey: [...queryKeys.fleet, grains],
    queryFn: () => fetchJson<Fleet>(fleetUrl(grains)),
    // Keep showing the table while a column change refetches.
    placeholderData: keepPreviousData,
  })
}

export function useGrainKeys(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.grainKeys,
    queryFn: () => fetchJson<GrainKey[]>('/api/grains/keys'),
    enabled,
    staleTime: 60_000,
  })
}

export function useSystemStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: () => fetchJson<SystemStatus>('/api/status'),
  })
}
