import {
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { fetchJson, postJson } from '@/api/client'
import type {
  AskResult,
  AuditPage,
  AuthInfo,
  Capabilities,
  CatchUpRun,
  CommandPreview,
  CommandRequest,
  CommandResult,
  CommandTemplate,
  Fleet,
  FleetComparison,
  FleetLiveView,
  GrainDistribution,
  GrainKey,
  GrainsChange,
  InventoryChange,
  InventoryDistribution,
  InventoryKey,
  Issue,
  JobDetail,
  JobPage,
  Key,
  KeyAction,
  KeyActionRequest,
  KeyActionResult,
  LiveKind,
  LiveView,
  MarkReadResult,
  MinionComparison,
  MinionDetail,
  MinionInventory,
  Nodegroups,
  Orchestrations,
  Reactor,
  Settings,
  StateFile,
  StateFileContent,
  StateRuns,
  StateTop,
  SystemStatus,
  User,
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
  // Packages and checks across the fleet; one minion's are under ['minion', id].
  inventory: ['inventory'] as const,
  // The fleet against one minion: apart from ['inventory'], so fleet updates don't redo it.
  inventoryCompare: ['inventory-compare'] as const,
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

/**
 * How many grains changes, and package and check changes, a minion's History shows. It asks for
 * one more of each: getting it means the list was cut there.
 */
export const GRAINS_HISTORY_LIMIT = 20
export const MINION_CHANGES_LIMIT = 500

export function useGrainsHistory(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.minion(id), 'grains-history'],
    queryFn: () =>
      fetchJson<GrainsChange[]>(`/api/minions/${enc(id)}/grains/history?limit=${GRAINS_HISTORY_LIMIT + 1}`),
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

/** What the signed-in person may run, and what Salt lets brine's account do. */
export function useCapabilities(enabled: boolean) {
  return useQuery({
    queryKey: ['capabilities'],
    queryFn: () => fetchJson<Capabilities>('/api/capabilities'),
    enabled,
    staleTime: 60_000,
  })
}

export function useTemplates(enabled: boolean) {
  return useQuery({
    queryKey: ['command-templates'],
    queryFn: () => fetchJson<CommandTemplate[]>('/api/commands/templates'),
    enabled,
    staleTime: 60_000,
  })
}

export function useOrchestrations() {
  return useQuery({
    queryKey: ['orchestrations'],
    queryFn: () => fetchJson<Orchestrations>('/api/orchestrations'),
    staleTime: 60_000,
  })
}

/** Have brine read the master's .sls files again now, instead of its kept copy. */
export function useRefreshOrchestrations() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => fetchJson<Orchestrations>('/api/orchestrations?refresh=true'),
    onSuccess: (fresh) => client.setQueryData(['orchestrations'], fresh),
  })
}

export function useCommandPreview() {
  return useMutation({
    mutationFn: (request: CommandRequest) => postJson<CommandPreview>('/api/commands/preview', request),
  })
}

export function useRunCommand() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (request: CommandRequest) => postJson<CommandResult>('/api/commands/run', request),
    onSettled: () => {
      for (const queryKey of [queryKeys.jobs, ['audit']]) void client.invalidateQueries({ queryKey })
    },
  })
}

export function useCancelCatchUp() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => postJson<CatchUpRun>(`/api/commands/catch-up/${id}/cancel`, {}),
    onSettled: () => {
      for (const queryKey of [queryKeys.jobs, ['minion'], ['audit']]) void client.invalidateQueries({ queryKey })
    },
  })
}

export function useKeyAction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action, ...body }: KeyActionRequest & { id: string; action: KeyAction }) =>
      postJson<KeyActionResult>(`/api/keys/${encodeURIComponent(id)}/${action}`, body),
    onSettled: () => {
      for (const queryKey of [queryKeys.keys, queryKeys.fleet, queryKeys.issues, queryKeys.status, ['minion'], ['audit']])
        void client.invalidateQueries({ queryKey })
    },
  })
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

/** Critical + warning issues not marked as read: what "need attention" means everywhere. */
export function attentionCount(issues: Issue[] | undefined): number | undefined {
  return issues?.filter((i) => i.severity !== 'info' && !i.read).length
}

/** Marks on their way: live updates hold off refreshing issues meanwhile (it'd undo them). */
export const MARK_ISSUES = ['issues', 'mark'] as const

/**
 * `readBefore`: how many read issues the page listed when the button was pressed, for what it
 * says afterwards. It travels with the mark because the callbacks below run with the state of
 * later renders (the list already without the issue).
 */
export type MarkIssues = { issues: Issue[]; read: boolean; readBefore: number }

/**
 * Mark issues read, as the page showed them (one that has changed since stays unread), or unread
 * again. Only for the signed-in person. The page changes straight away.
 *
 * `on` hears how every mark ends, even when another started since (mutate's own callbacks only
 * hear about the latest).
 */
export function useMarkIssues(
  on: {
    onSuccess?: (result: MarkReadResult | undefined, vars: MarkIssues) => void
    onError?: (error: Error, vars: MarkIssues) => void
  } = {},
) {
  const client = useQueryClient()
  // Set each of these issues' read flag in the list on screen.
  const setRead = (read: Map<string, boolean>) =>
    client.setQueryData<Issue[]>(queryKeys.issues, (old) =>
      old?.map((i) => (read.has(i.key) ? { ...i, read: read.get(i.key)! } : i)),
    )
  return useMutation({
    mutationKey: MARK_ISSUES,
    mutationFn: ({ issues, read }: MarkIssues): Promise<MarkReadResult | undefined> =>
      read
        ? postJson<MarkReadResult>('/api/issues/read', { issues: issues.map(({ key, fingerprint }) => ({ key, fingerprint })) })
        : postJson<undefined>('/api/issues/unread', { keys: issues.map((i) => i.key) }),
    onMutate: async ({ issues, read }) => {
      await client.cancelQueries({ queryKey: queryKeys.issues })
      const keys = new Set(issues.map((i) => i.key))
      const shown = client.getQueryData<Issue[]>(queryKeys.issues) ?? []
      const was = new Map(shown.filter((i) => keys.has(i.key)).map((i) => [i.key, i.read]))
      setRead(new Map(issues.map((i) => [i.key, read])))
      return { was }
    },
    onSuccess: (result, vars) => {
      if (result?.changed.length) setRead(new Map(result.changed.map((key) => [key, false])))
      on.onSuccess?.(result, vars)
    },
    onError: (error, vars, context) => {
      // Only these issues go back: other marks may be on their way.
      if (context) setRead(context.was)
      on.onError?.(error, vars)
    },
    // The last one to finish fetches the list again, with whatever live updates held off.
    onSettled: () =>
      client.isMutating({ mutationKey: MARK_ISSUES }) === 1
        ? client.invalidateQueries({ queryKey: queryKeys.issues })
        : undefined,
  })
}

export function useSettings() {
  // Comes from the config file, which only changes with a restart; lists ask for it too.
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => fetchJson<Settings>('/api/settings'),
    staleTime: 5 * 60_000,
  })
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

/** How many packages and checks the explorer's picker lists at once. */
export const INVENTORY_KEYS_LIMIT = 50

/**
 * Every check's entries and the packages that differ across the fleet, or with `q`, the packages
 * and checks whose name contains it. (As options, to fetch an answer outright: queryClient.fetchQuery.)
 */
export function inventoryKeysQuery(q: string) {
  return queryOptions({
    queryKey: [...queryKeys.inventory, 'keys', q],
    queryFn: () =>
      fetchJson<InventoryKey[]>(`/api/inventory/keys?${new URLSearchParams({ q, limit: String(INVENTORY_KEYS_LIMIT) })}`),
    staleTime: 60_000,
  })
}

export function useInventoryKeys(q: string) {
  return useQuery({ ...inventoryKeysQuery(q), placeholderData: keepPreviousData })
}

export function useInventoryValues(key: string | null) {
  return useQuery({
    queryKey: [...queryKeys.inventory, 'values', key],
    queryFn: () => fetchJson<InventoryDistribution>(`/api/inventory/values?key=${enc(key ?? '')}`),
    enabled: !!key,
  })
}

/**
 * What appeared, changed or went away, newest first: for one package or check entry, or one
 * minion (MINION_CHANGES_LIMIT and one more, so one big upgrade fits).
 */
export function useInventoryChanges(filter: { key: string } | { minion: string }, enabled = true) {
  const params = new URLSearchParams(filter)
  if ('minion' in filter) params.set('limit', String(MINION_CHANGES_LIMIT + 1))
  return useQuery({
    queryKey:
      'minion' in filter
        ? [...queryKeys.minion(filter.minion), 'inventory-changes']
        : [...queryKeys.inventory, 'changes', filter.key],
    queryFn: () => fetchJson<InventoryChange[]>(`/api/inventory/changes?${params}`),
    enabled,
  })
}

export function useMinionInventory(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.minion(id), 'inventory'],
    queryFn: () => fetchJson<MinionInventory>(`/api/minions/${enc(id)}/inventory`),
    enabled,
  })
}

/**
 * How every other accepted minion's packages and checks differ from `reference`'s. Heavy across
 * a big fleet, so not under ['inventory'], which every fleet update redoes. It's kept a minute,
 * and redone when the reference's packages or checks move (an 'inventory' hint), on Read now,
 * or when asked.
 */
export function useFleetComparison(reference: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.inventoryCompare, reference],
    queryFn: () => fetchJson<FleetComparison>(`/api/inventory/compare?${new URLSearchParams({ reference })}`),
    enabled,
    staleTime: 60_000,
  })
}

/** Where `minion`'s packages and checks differ from `reference`'s. */
export function useComparison(reference: string, minion: string | null) {
  return useQuery({
    queryKey: [...queryKeys.inventory, 'compare', reference, minion],
    queryFn: () =>
      fetchJson<MinionComparison>(
        `/api/inventory/compare/${enc(minion ?? '')}?${new URLSearchParams({ reference })}`,
      ),
    enabled: !!minion,
  })
}

/** Read now: every online minion (null), or one, for its packages and checks. */
export function useAskInventory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (minion: string | null) => postJson<AskResult>('/api/inventory/ask', { minion }),
    onSuccess: (_, minion) => {
      for (const queryKey of [queryKeys.inventory, queryKeys.inventoryCompare])
        void client.invalidateQueries({ queryKey })
      if (minion !== null) void client.invalidateQueries({ queryKey: [...queryKeys.minion(minion), 'inventory'] })
    },
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

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => fetchJson<User>('/api/auth/me'), staleTime: 60_000 })
}

export function useAuthInfo() {
  return useQuery({
    queryKey: ['auth-info'],
    queryFn: () => fetchJson<AuthInfo>('/api/auth/info'),
    staleTime: Infinity,
  })
}

export function useAuditLog(action: string | null) {
  return useInfiniteQuery({
    queryKey: ['audit', action],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: '100' })
      if (action) params.set('action', action)
      if (pageParam) params.set('before', String(pageParam))
      return fetchJson<AuditPage>(`/api/audit?${params}`)
    },
    getNextPageParam: (last) => last.next_before,
  })
}
