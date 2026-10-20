import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type {
  Fleet,
  FleetLiveView,
  GrainDistribution,
  GrainKey,
  GrainsChange,
  Issue,
  JobDetail,
  JobPage,
  Key,
  LiveKind,
  LiveView,
  MinionDetail,
  Nodegroups,
  Reactor,
  Settings,
  StateFile,
  StateFileContent,
  StateRuns,
  StateTop,
  SystemStatus,
} from '@/api/types'

export const queryKeys = {
  fleet: ['fleet'] as const,
  status: ['status'] as const,
  grainKeys: ['grain-keys'] as const,
  minion: (id: string) => ['minion', id] as const,
  // Not under ['minion', id]: live views run a Salt job, so they mustn't refetch on every hint.
  minionLive: (id: string, kind: LiveKind) => ['minion-live', id, kind] as const,
  jobs: ['jobs'] as const,
  keys: ['keys'] as const,
  issues: ['issues'] as const,
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

const enc = encodeURIComponent

export function useMinion(id: string) {
  return useQuery({
    queryKey: queryKeys.minion(id),
    queryFn: () => fetchJson<MinionDetail>(`/api/minions/${enc(id)}`),
  })
}

export function useGrainsHistory(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.minion(id), 'grains-history'],
    queryFn: () => fetchJson<GrainsChange[]>(`/api/minions/${enc(id)}/grains/history`),
    enabled,
  })
}

export function useMinionLive(id: string, kind: LiveKind, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.minionLive(id, kind),
    queryFn: () => fetchJson<LiveView>(`/api/minions/${enc(id)}/live/${kind}`),
    enabled,
    staleTime: Infinity, // refetch only when asked
  })
}

export type JobFilters = { q: string; kind: 'local' | 'runner' | null }

// Everything job-related lives under ['jobs', ...] so a live "job" hint refreshes it all.
export function useJobs(filters: JobFilters) {
  return useInfiniteQuery({
    queryKey: [...queryKeys.jobs, 'list', filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: '50' })
      if (filters.q.trim()) params.set('q', filters.q.trim())
      if (filters.kind) params.set('kind', filters.kind)
      if (pageParam) params.set('before', pageParam)
      return fetchJson<JobPage>(`/api/jobs?${params}`)
    },
    getNextPageParam: (last) => last.next_before,
    placeholderData: keepPreviousData,
  })
}

export function useJob(jid: string) {
  return useQuery({
    queryKey: [...queryKeys.jobs, 'detail', jid],
    queryFn: () => fetchJson<JobDetail>(`/api/jobs/${enc(jid)}`),
  })
}

export function useStateRuns(enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.jobs, 'state-runs'],
    queryFn: () => fetchJson<StateRuns>('/api/jobs/state-runs'),
    enabled,
  })
}

export function useKeys() {
  return useQuery({ queryKey: queryKeys.keys, queryFn: () => fetchJson<Key[]>('/api/keys') })
}

export function useReactors(enabled: boolean) {
  return useQuery({
    queryKey: ['reactors'],
    queryFn: () => fetchJson<Reactor[]>('/api/reactors'),
    enabled,
    staleTime: 60_000,
  })
}

export function useIssues() {
  return useQuery({ queryKey: queryKeys.issues, queryFn: () => fetchJson<Issue[]>('/api/issues') })
}

/** Critical + warning issues: what "need attention" means everywhere. */
export function attentionCount(issues: Issue[] | undefined): number | undefined {
  return issues?.filter((i) => i.severity !== 'info').length
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: () => fetchJson<Settings>('/api/settings') })
}

export function useGrainValues(grain: string | null) {
  return useQuery({
    queryKey: ['grain-values', grain],
    queryFn: () => fetchJson<GrainDistribution>(`/api/grains/values?grain=${enc(grain ?? '')}`),
    enabled: !!grain,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}

export function useNodegroups(enabled: boolean) {
  return useQuery({
    queryKey: ['nodegroups'],
    queryFn: () => fetchJson<Nodegroups>('/api/nodegroups'),
    enabled,
    staleTime: 60_000,
  })
}

// Live views below run Salt functions on minions: fetch on open and on Refresh only.

export function useStateTop(enabled: boolean) {
  return useQuery({
    queryKey: ['states', 'top'],
    queryFn: () => fetchJson<StateTop>('/api/states/top'),
    enabled,
    staleTime: Infinity,
  })
}

export function useStateFiles(enabled: boolean) {
  return useQuery({
    queryKey: ['states', 'files'],
    queryFn: () => fetchJson<StateFile[]>('/api/states/files'),
    enabled,
    staleTime: 60_000,
  })
}

export function useStateFile(path: string | null) {
  return useQuery({
    queryKey: ['states', 'file', path],
    queryFn: () => fetchJson<StateFileContent>(`/api/states/file?path=${enc(path ?? '')}`),
    enabled: !!path,
    staleTime: 60_000,
  })
}

export function useAutomation(kind: 'schedules' | 'beacons') {
  return useQuery({
    queryKey: ['automation', kind],
    queryFn: () => fetchJson<FleetLiveView>(`/api/automation/${kind}`),
    staleTime: Infinity,
  })
}
