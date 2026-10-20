import { cn } from '@/lib/cn'

/**
 * The brine wordmark, tinted with the current text color.
 *
 * The SVG ships with a fixed light fill, so it is used as a CSS mask and painted with
 * `currentColor` — that keeps it legible in both light and dark themes.
 */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      role="img"
      aria-label="brine"
      className={cn('inline-block aspect-[1115/368] bg-current', className)}
      style={{
        mask: 'url(/brine-wordmark.svg) center / contain no-repeat',
        WebkitMask: 'url(/brine-wordmark.svg) center / contain no-repeat',
      }}
    />
  )
}
