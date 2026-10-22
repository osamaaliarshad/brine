import { useId } from 'react'
import artwork from '@/assets/brine-logo.svg?raw'
import { cn } from '@/lib/cn'

// The logo as drawn in src/assets/brine-logo.svg: a gradient wave beside near-white letters. It's
// read once and drawn inline, so the letters can take the current text color (legible in both
// themes) while the wave keeps its gradient.
const drawing = new DOMParser().parseFromString(artwork, 'image/svg+xml').documentElement
const gradient = drawing.querySelector('linearGradient')
const shapes = [...drawing.querySelectorAll('path')]
const isWave = (path: Element) => path.getAttribute('fill')?.startsWith('url(') ?? false

const VIEW_BOX = drawing.getAttribute('viewBox') ?? undefined
const WAVE = shapes.find(isWave)?.getAttribute('d') ?? undefined
const LETTERS = shapes.find((path) => !isWave(path))?.getAttribute('d') ?? undefined
const ENDS = Object.fromEntries(['x1', 'y1', 'x2', 'y2'].map((end) => [end, gradient?.getAttribute(end) ?? undefined]))
const STOPS = [...(gradient?.querySelectorAll('stop') ?? [])].map((stop) => ({
  offset: stop.getAttribute('offset') ?? undefined,
  color: stop.getAttribute('stop-color') ?? undefined,
}))
// Just the wave, for tight spots: its box in the artwork (x 20 to 329, y 20 to 233), made square.
const MARK_VIEW_BOX = '10 -38 329 329'

/** The brine logo, or just its wave (`mark`) where the letters won't fit. */
export function Logo({ className, mark = false }: { className?: string; mark?: boolean }) {
  // Each copy gets its own gradient id: the sidebar and the phone header both draw one, and a
  // shared id would point the visible copy at the hidden one's gradient.
  const tide = `tide${useId().replace(/[^\w-]/g, '')}`
  return (
    <svg
      viewBox={mark ? MARK_VIEW_BOX : VIEW_BOX}
      role="img"
      aria-label="brine"
      className={cn('w-auto shrink-0', className)}
    >
      <defs>
        <linearGradient id={tide} {...ENDS}>
          {STOPS.map((stop) => (
            <stop key={stop.offset} offset={stop.offset} stopColor={stop.color} />
          ))}
        </linearGradient>
      </defs>
      <path fill={`url(#${tide})`} fillRule="evenodd" d={WAVE} />
      {!mark && <path fill="currentColor" fillRule="evenodd" d={LETTERS} />}
    </svg>
  )
}
