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

/** One word as the Run page's shell-style parser will read it back. */
function shellWord(word: string): string {
  if (word !== '' && !/[\s'"\\#]/.test(word)) return word
  return `"${word.replace(/(["\\])/g, '\\$1')}"`
}

/** A job's command as you'd type it on the Run page, to run it again: `state.apply motd test=true`. */
export function commandLine(fun: string, args: unknown[]): string {
  const words = args.flatMap((arg) => {
    const value = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v))
    if (arg && typeof arg === 'object' && '__kwarg__' in arg)
      return Object.entries(arg)
        .filter(([k]) => k !== '__kwarg__')
        .map(([k, v]) => shellWord(`${k}=${value(v)}`))
    return [shellWord(value(arg))]
  })
  return [fun, ...words].join(' ')
}
