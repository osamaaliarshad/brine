import { cn } from '@/lib/cn'

/**
 * The brine wordmark (or just its "b", for tight spots), tinted with the current text color.
 *
 * The SVGs ship with a fixed light fill, so they're used as CSS masks and painted with
 * `currentColor`. That keeps them legible in both light and dark themes.
 */
export function Wordmark({ className, mark = false }: { className?: string; mark?: boolean }) {
  const src = mark ? '/brine-mark.svg' : '/brine-wordmark.svg'
  return (
    <span
      role="img"
      aria-label="brine"
      className={cn('inline-block bg-current', mark ? 'aspect-square' : 'aspect-[1115/368]', className)}
      style={{
        mask: `url(${src}) center / contain no-repeat`,
        WebkitMask: `url(${src}) center / contain no-repeat`,
      }}
    />
  )
}
