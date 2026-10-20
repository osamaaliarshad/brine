import type { TargetType } from '@/api/types'

/** Recent commands, kept in this browser only (like a shell history). */
export type HistoryItem = { command: string; target: string; target_type: TargetType }

const KEY = 'brine-command-history'
const MAX = 10

function isItem(value: unknown): value is HistoryItem {
  const v = value as Partial<HistoryItem> | null
  return !!v && typeof v.command === 'string' && typeof v.target === 'string' && typeof v.target_type === 'string'
}

export function loadHistory(): HistoryItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter(isItem).slice(0, MAX) : []
  } catch {
    return []
  }
}

/** Puts `item` first (once) and saves; returns the new history. */
export function remember(item: HistoryItem, history: HistoryItem[]): HistoryItem[] {
  const same = (h: HistoryItem) =>
    h.command === item.command && h.target === item.target && h.target_type === item.target_type
  const next = [item, ...history.filter((h) => !same(h))].slice(0, MAX)
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // storage unavailable: remembered for this page load only
  }
  return next
}
