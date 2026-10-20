import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router'

export type TabDef<K extends string> = { key: K; label: string; badge?: ReactNode }

/** The active tab lives in `?tab=`, so tabs are linkable and survive reloads. */
export function useTab<K extends string>(tabs: readonly TabDef<K>[], fallback: K) {
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const active = tabs.find((t) => t.key === wanted)?.key ?? fallback
  const select = (key: K) => {
    const next = new URLSearchParams(params)
    if (key === fallback) next.delete('tab')
    else next.set('tab', key)
    setParams(next, { replace: true })
  }
  return [active, select] as const
}
