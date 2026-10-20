import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { queryKeys } from '@/api/queries'
import type { LiveMessage } from '@/api/types'

const DEBOUNCE_MS = 250

/**
 * Turns /api/stream hints into query invalidations. Bursts (a job returning on 50 minions)
 * are coalesced so each query refetches at most once per DEBOUNCE_MS.
 */
export function createLiveInvalidator(queryClient: QueryClient, debounceMs = DEBOUNCE_MS) {
  const pending = new Set<string>()
  let timer: ReturnType<typeof setTimeout> | undefined

  const flush = () => {
    timer = undefined
    for (const key of pending) {
      void queryClient.invalidateQueries({ queryKey: JSON.parse(key) as unknown[] })
    }
    pending.clear()
  }

  const queue = (key: readonly unknown[]) => {
    pending.add(JSON.stringify(key))
    timer ??= setTimeout(flush, debounceMs)
  }

  return (message: LiveMessage) => {
    switch (message.type) {
      case 'fleet':
        queue(queryKeys.fleet)
        queue(queryKeys.keys)
        queue(queryKeys.issues)
        break
      case 'status':
        queue(queryKeys.status)
        queue(queryKeys.fleet)
        queue(queryKeys.issues)
        break
      case 'minion':
        queue(queryKeys.minion(message.id))
        break
      case 'job':
        queue(queryKeys.jobs)
        queue(queryKeys.issues)
        break
      case 'hello':
      case 'resync':
        // (Re)connected or we fell behind: anything could have changed.
        void queryClient.invalidateQueries()
        break
    }
  }
}

/** Keep every query on screen fresh while the app is open. */
export function useLiveUpdates(url = '/api/stream') {
  const queryClient = useQueryClient()

  useEffect(() => {
    const handle = createLiveInvalidator(queryClient)
    // EventSource reconnects by itself after errors; each reconnect sends "hello" again.
    const source = new EventSource(url)
    source.onmessage = (event: MessageEvent<string>) => {
      try {
        handle(JSON.parse(event.data) as LiveMessage)
      } catch {
        // ignore malformed messages
      }
    }
    return () => source.close()
  }, [queryClient, url])
}
