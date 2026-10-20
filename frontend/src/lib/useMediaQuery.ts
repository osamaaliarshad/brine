import { useEffect, useState } from 'react'

/** Whether a CSS media query matches; `fallback` where matchMedia isn't available (tests). */
export function useMediaQuery(query: string, fallback = true): boolean {
  const get = () => (typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : fallback)
  const [matches, setMatches] = useState(get)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const list = window.matchMedia(query)
    const update = () => setMatches(list.matches)
    update()
    list.addEventListener('change', update)
    return () => list.removeEventListener('change', update)
  }, [query])
  return matches
}
