/** Salt CLI-style rendering of a job's arguments: `pkg.install curl refresh=True`. */
export function formatArgs(args: unknown[]): string {
  return args
    .map((arg) => {
      if (arg && typeof arg === 'object' && '__kwarg__' in arg) {
        return Object.entries(arg)
          .filter(([k]) => k !== '__kwarg__')
          .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
          .join(' ')
      }
      return typeof arg === 'string' ? arg : JSON.stringify(arg)
    })
    .join(' ')
}
