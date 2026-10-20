import { useEffect, useRef, useState } from 'react'
import type { SaltEventEntry } from '@/api/types'

export const MAX_EVENTS = 500

/**
 * Raw Salt events from /api/events/stream, newest first. While paused, new events are counted
 * but not shown; resuming shows them. Reconnects re-send the backlog; `seq` dedupes it.
 */
// One stream per open Events page; the server keeps the backlog, so nothing is lost on reload.
export function useEventStream(url = '/api/events/stream') {
  const [paused, setPaused] = useState(false)
  const [events, setEvents] = useState<SaltEventEntry[]>([])
  const [waiting, setWaiting] = useState(0)
  const [connected, setConnected] = useState(false)
  const buffer = useRef<SaltEventEntry[]>([])
  const seen = useRef(new Set<number>())
  const pausedRef = useRef(false)

  const flush = () => {
    const incoming = buffer.current
    buffer.current = []
    setWaiting(0)
    if (incoming.length) setEvents((prev) => [...incoming.reverse(), ...prev].slice(0, MAX_EVENTS))
  }

  useEffect(() => {
    const source = new EventSource(url)
    let timer: ReturnType<typeof setTimeout> | undefined
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.onmessage = (message: MessageEvent<string>) => {
      let entry: SaltEventEntry
      try {
        entry = JSON.parse(message.data) as SaltEventEntry
      } catch {
        return
      }
      if (seen.current.has(entry.seq)) return
      seen.current.add(entry.seq)
      buffer.current.push(entry)
      if (pausedRef.current) {
        setWaiting(buffer.current.length)
        return
      }
      // Batch bursts (the backlog arrives all at once) into one render.
      timer ??= setTimeout(() => {
        timer = undefined
        if (!pausedRef.current) flush()
      }, 100)
    }
    return () => {
      clearTimeout(timer)
      source.close()
    }
  }, [url])

  const clear = () => {
    buffer.current = []
    setWaiting(0)
    setEvents([])
  }

  const togglePause = () => {
    pausedRef.current = !pausedRef.current
    if (!pausedRef.current) flush()
    setPaused(pausedRef.current)
  }

  return { events, waiting, connected, paused, togglePause, clear }
}
