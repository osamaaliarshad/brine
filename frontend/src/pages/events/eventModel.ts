import type { SaltEventEntry } from '@/api/types'

export type EventKind = 'job' | 'runner' | 'presence' | 'key' | 'minion' | 'beacon' | 'other'

export function eventKind(tag: string): EventKind {
  if (tag.startsWith('salt/job/')) return 'job'
  if (tag.startsWith('salt/run/') || tag.startsWith('salt/wheel/')) return 'runner'
  if (tag.startsWith('salt/presence/')) return 'presence'
  if (tag === 'salt/auth' || tag === 'salt/key') return 'key'
  if (tag.startsWith('salt/minion/') || tag === 'minion_start') return 'minion'
  if (tag.startsWith('salt/beacon/')) return 'beacon'
  return 'other'
}

const str = (v: unknown) => (typeof v === 'string' ? v : v === undefined ? '' : JSON.stringify(v))
const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : [])

/** A human one-liner for the event list. */
export function summarize(event: Pick<SaltEventEntry, 'tag' | 'data'>): string {
  const { tag, data } = event
  const parts = tag.split('/')
  if (/^salt\/job\/[^/]+\/new$/.test(tag)) {
    const minions = list(data.minions)
    return `${str(data.fun)} → ${str(data.tgt)}${minions.length ? ` (${minions.length} minion${minions.length === 1 ? '' : 's'})` : ''}`
  }
  if (/^salt\/job\/[^/]+\/ret\//.test(tag)) {
    const outcome = data.success === false ? 'failed' : data.success === true ? 'ok' : 'returned'
    return `${str(data.id)}: ${str(data.fun)} ${outcome}`
  }
  if (/^salt\/(run|wheel)\/[^/]+\/(new|ret)$/.test(tag)) {
    return `${str(data.fun)} ${parts[3] === 'new' ? 'started' : data.success === false ? 'failed' : 'finished'}`
  }
  if (tag === 'salt/presence/present') return `${list(data.present).length} minions present`
  if (tag === 'salt/presence/change') {
    const changes = [...list(data.new).map((m) => `+${m}`), ...list(data.lost).map((m) => `−${m}`)]
    return changes.join(' ') || 'no change'
  }
  if (tag === 'salt/auth') return `${str(data.id)} authenticating (${str(data.act)})`
  if (tag === 'salt/key') return `${str(data.id)} key ${str(data.act)}`
  if (/^salt\/minion\/[^/]+\/start$/.test(tag)) return `${parts[2]} started`
  if (tag.startsWith('salt/beacon/')) return `${parts[3] ?? 'beacon'} beacon on ${parts[2] ?? '?'}`
  if (/^\d{20}$/.test(tag)) return `job ${tag} published`
  const keys = Object.keys(data).filter((k) => k !== '_stamp')
  return keys.slice(0, 4).join(', ')
}

export function matchesFilter(event: SaltEventEntry, needle: string): boolean {
  const q = needle.trim().toLowerCase()
  if (!q) return true
  return event.tag.toLowerCase().includes(q) || JSON.stringify(event.data).toLowerCase().includes(q)
}
