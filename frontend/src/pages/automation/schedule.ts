/** Reading schedule.list / beacons.list output (return_yaml=False). */

type Obj = Record<string, unknown>

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)

export type ScheduleRow = {
  minion: string
  name: string
  fun: string
  args: string
  when: string
  enabled: boolean
}

export type BeaconRow = { minion: string; name: string; config: string; enabled: boolean }

const UNITS: [string, string][] = [
  ['seconds', 'second'],
  ['minutes', 'minute'],
  ['hours', 'hour'],
  ['days', 'day'],
]

/** "every 30 minutes", "cron 0 * * * *", "at 2026-10-21 03:00", "once". */
export function describeWhen(job: Obj): string {
  const every = UNITS.filter(([key]) => typeof job[key] === 'number' && (job[key] as number) > 0).map(
    ([key, unit]) => `${job[key]} ${unit}${job[key] === 1 ? '' : 's'}`,
  )
  if (every.length) return `every ${every.join(' ')}`
  if (job.cron) return `cron ${String(job.cron)}`
  if (job.when) return `at ${Array.isArray(job.when) ? job.when.join(', ') : String(job.when)}`
  if (job.once) return `once at ${String(job.once)}`
  return '—'
}

function argsText(job: Obj): string {
  const args = Array.isArray(job.args) ? job.args.map(String) : []
  const kwargs = isObj(job.kwargs) ? Object.entries(job.kwargs).map(([k, v]) => `${k}=${JSON.stringify(v)}`) : []
  return [...args, ...kwargs].join(' ')
}

export function scheduleRows(results: Record<string, unknown>): ScheduleRow[] {
  const rows: ScheduleRow[] = []
  for (const [minion, data] of Object.entries(results)) {
    if (!isObj(data)) continue
    const schedulerOn = data.enabled !== false
    for (const [name, job] of Object.entries(data)) {
      if (name === 'enabled' || !isObj(job)) continue
      rows.push({
        minion,
        name,
        fun: String(job.function ?? '—'),
        args: argsText(job),
        when: describeWhen(job),
        enabled: schedulerOn && job.enabled !== false,
      })
    }
  }
  return rows.sort((a, b) => a.minion.localeCompare(b.minion) || a.name.localeCompare(b.name))
}

/** beacons.list gives each beacon as a list of single-key dicts: merge and summarise. */
export function beaconRows(results: Record<string, unknown>): BeaconRow[] {
  const rows: BeaconRow[] = []
  for (const [minion, data] of Object.entries(results)) {
    if (!isObj(data)) continue
    const beaconsOn = data.enabled !== false
    for (const [name, raw] of Object.entries(data)) {
      if (name === 'enabled') continue
      const merged: Obj = Array.isArray(raw)
        ? Object.assign({}, ...raw.filter(isObj))
        : isObj(raw)
          ? raw
          : {}
      const { enabled, ...rest } = merged
      rows.push({
        minion,
        name,
        config: Object.entries(rest)
          .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
          .join(' '),
        enabled: beaconsOn && enabled !== false,
      })
    }
  }
  return rows.sort((a, b) => a.minion.localeCompare(b.minion) || a.name.localeCompare(b.name))
}
