import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'
import { type ReactNode, useEffect, useId, useState } from 'react'
import { useLocation } from 'react-router'
import { useMe, useSettings, useSystemStatus } from '@/api/queries'
import type { Role, Settings } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Card, Pill, StatusDot } from '@/components/ui'
import { cn } from '@/lib/cn'
import { describeSource, INVENTORY_SETTINGS_ID } from '@/lib/inventoryKey'
import { getThemePreference, setThemePreference, type ThemePreference } from '@/lib/theme'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { DEFAULT_PREFS, loadPrefs, savePrefs } from '@/pages/fleet/columnPrefs'

function Section({
  id,
  title,
  description,
  children,
}: {
  /** For links to it: /settings#<id>. */
  id?: string
  title: string
  description?: string
  children: ReactNode
}) {
  const heading = useId()
  return (
    <section id={id} aria-labelledby={heading} className="scroll-mt-4">
      <Card className="overflow-hidden">
        <div className="border-b px-5 py-4 sm:px-6">
          <h2 id={heading} className="font-semibold">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
        </div>
        <dl className="divide-y">{children}</dl>
      </Card>
    </section>
  )
}

function Row({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="grid gap-1 px-5 py-3 sm:grid-cols-[14rem_1fr] sm:gap-4 sm:px-6">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="min-w-0 text-sm">
        {children}
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </dd>
    </div>
  )
}

const THEMES: { value: ThemePreference; label: string; icon: LucideIcon }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

function ThisBrowser() {
  const [theme, setTheme] = useState(getThemePreference)
  const [prefs, setPrefs] = useState(loadPrefs)
  return (
    <Section title="This browser" description="Personal choices, saved only on this device.">
      <Row label="Theme">
        <div role="radiogroup" aria-label="Theme" className="inline-flex gap-1 rounded-lg border p-1">
          {THEMES.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={theme === value}
              onClick={() => {
                setThemePreference(value)
                setTheme(value)
              }}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm',
                theme === value ? 'bg-surface-2 font-medium' : 'text-muted hover:text-fg',
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </button>
          ))}
        </div>
      </Row>
      <Row
        label="Fleet columns"
        hint="Change them from the Columns menu on the Fleet page."
      >
        {prefs.grains === null ? (
          'Team default'
        ) : (
          <span className="inline-flex flex-wrap items-center gap-2">
            Customised: {prefs.grains.length ? prefs.grains.map((g) => <Pill key={g}>{g}</Pill>) : 'no grain columns'}
            <button
              type="button"
              className="text-accent hover:underline"
              onClick={() => {
                const next = { ...prefs, grains: DEFAULT_PREFS.grains }
                savePrefs(next)
                setPrefs(next)
              }}
            >
              Reset to team default
            </button>
          </span>
        )}
      </Row>
    </Section>
  )
}

const ROLE_LABEL: Record<Role, string> = { viewer: 'Viewer', operator: 'Operator', admin: 'Admin' }

function SignIn({ auth }: { auth: Settings['auth'] }) {
  const me = useMe()
  const counts = (['admin', 'operator', 'viewer'] as const)
    .filter((r) => auth.role_patterns[r] > 0)
    .map((r) => `${ROLE_LABEL[r]}: ${auth.role_patterns[r]}`)
  return (
    <Section title="Sign-in" description="Who can open brine and what they can do. See docs/oidc-providers.md.">
      {auth.provider === 'none' ? (
        <Row label="Method" hint="Set auth.provider: oidc before letting anyone else reach brine.">
          <span className="text-warn">Off</span>: everyone is treated as {ROLE_LABEL[auth.anonymous_role]}
        </Row>
      ) : (
        <>
          <Row label="Method">
            {auth.display_name} <span className="text-muted">(OpenID Connect)</span>
          </Row>
          <Row label="Issuer">
            <code className="font-mono break-all">{auth.issuer}</code>
          </Row>
          <Row label="Allowed domains" hint="Accounts outside these can't sign in, whatever their role.">
            {auth.allowed_domains.length ? auth.allowed_domains.join(', ') : 'Any'}
          </Row>
          <Row label="Roles" hint="Email patterns per role, under roles: in the config. Checked on every request.">
            {counts.length ? counts.join(' · ') : 'None set, so nobody can sign in'}
          </Row>
          <Row label="Session length">{auth.session_hours} hours</Row>
        </>
      )}
      {me.data && (
        <Row label="You">
          {me.data.provider === 'oidc' ? `${me.data.email} · ` : ''}
          {ROLE_LABEL[me.data.role]}
        </Row>
      )}
    </Section>
  )
}

/** "6 hours", "hour", "30 minutes": how often, after "every". */
function every(hours: number): string {
  if (hours === 1) return 'hour'
  if (hours < 1) return `${Math.round(hours * 60)} minutes`
  return `${hours} hours`
}

function PackagesAndChecks({ inventory, saltApi }: { inventory: Settings['inventory']; saltApi: Settings['salt_api'] }) {
  const refused = Object.entries(inventory.refused)
  return (
    <Section
      id={INVENTORY_SETTINGS_ID}
      title="Packages and checks"
      description="What brine reads from each minion and keeps the history of: its packages, and what each check prints."
    >
      <Row label="When">
        Read every {every(inventory.refresh_hours)}, after people's jobs, when a minion comes back, and on Read now
      </Row>
      <Row
        label="Checks"
        hint={
          inventory.checks.length
            ? 'Commands are sent exactly as written and shown to everyone signed in; keep secrets out of them.'
            : undefined
        }
      >
        {inventory.checks.length ? (
          <ul className="flex flex-col gap-1">
            {inventory.checks.map((c) => (
              <li key={c.name}>
                <code className="font-mono break-all">
                  {c.name}: {c.command}
                </code>
              </li>
            ))}
          </ul>
        ) : (
          'None, so brine reads only packages. Add checks under inventory › checks in the config.'
        )}
      </Row>
      <Row label="Salt permissions">
        {refused.length > 0 && (
          <ul className="mb-2 flex flex-col gap-1 text-warn">
            {refused.map(([source, why]) => (
              <li key={source}>
                brine can't read {describeSource(source)}: {why}
              </li>
            ))}
          </ul>
        )}
        <details open={refused.length > 0}>
          <summary className="cursor-pointer text-accent hover:underline">Salt permissions brine needs</summary>
          <p className="mt-2 text-muted">
            Add these under external_auth › {saltApi.eauth} › {saltApi.username} in the master's config.
          </p>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs">{inventory.acl}</pre>
        </details>
      </Row>
    </Section>
  )
}

const keptFor = (days: number) => (days ? `${days} days` : 'forever')

export function SettingsPage() {
  const now = useNow()
  const settings = useSettings()
  const status = useSystemStatus()
  const s = settings.data
  const api = status.data?.salt_api
  // A link to a section (/settings#packages-and-checks): go there once it's on the page.
  const { hash } = useLocation()
  const loaded = !!s
  useEffect(() => {
    if (loaded && hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.({ block: 'start' })
  }, [loaded, hash])

  return (
    <>
      <PageHeader title="Settings" subtitle="How this brine is set up. Server settings come from its config file." />
      <div className="flex flex-col gap-4 sm:gap-6">
        <ThisBrowser />

        {settings.isPending ? (
          <p className="text-muted">Loading settings…</p>
        ) : settings.isError ? (
          <Card className="px-6 py-10 text-center text-muted">Couldn't load settings: {settings.error.message}</Card>
        ) : (
          s && (
            <>
              <Section title="salt-api" description="brine's connection to the Salt master.">
                <Row label="Status">
                  {api ? (
                    <span className="inline-flex items-center gap-2">
                      <StatusDot status={api.connected ? 'online' : 'offline'} />
                      {api.connected ? 'Connected' : 'Not connected'}
                      {api.since && (
                        <span className="text-muted" title={formatAbsolute(api.since)}>
                          since {formatRelative(api.since, now)}
                        </span>
                      )}
                    </span>
                  ) : (
                    '…'
                  )}
                  {api?.error && <p className="mt-1 text-xs text-danger">{api.error}</p>}
                </Row>
                <Row label="URL">
                  <code className="font-mono">{s.salt_api.url}</code>
                  {!s.salt_api.verify_tls && s.salt_api.url.startsWith('https') && (
                    <Badge tone="warn">TLS not verified</Badge>
                  )}
                </Row>
                <Row label="Service account" hint="Its permissions come from external_auth on the master.">
                  <code className="font-mono">{s.salt_api.username}</code> via {s.salt_api.eauth}
                </Row>
                <Row label="Last event">
                  {api?.last_event_at ? (
                    <span title={formatAbsolute(api.last_event_at)}>{formatRelative(api.last_event_at, now)}</span>
                  ) : (
                    'none yet'
                  )}
                </Row>
              </Section>

              <Section title="Presence" description="How brine learns who is online. See docs/presence-and-status.md.">
                <Row label="Method" hint="auto uses presence events when the master sends them and polls otherwise.">
                  {s.presence.method}
                  {s.presence.active_method && (
                    <span className="text-muted"> · currently {s.presence.active_method}</span>
                  )}
                </Row>
                <Row label="Last check">
                  {status.data?.presence.checked_at ? (
                    <span title={formatAbsolute(status.data.presence.checked_at)}>
                      {formatRelative(status.data.presence.checked_at, now)}
                    </span>
                  ) : (
                    'never'
                  )}
                </Row>
                <Row label="Polling interval">{s.presence.poll_seconds}s (when polling)</Row>
                <Row label="Stale after" hint="With no fresh presence check this long, statuses show as stale.">
                  {s.fleet.stale_after_minutes} minutes
                </Row>
              </Section>

              <Section title="Fleet and jobs">
                <Row label="Default columns" hint="fleet.columns in the config: what everyone sees until they customise.">
                  <span className="inline-flex flex-wrap gap-2">
                    {s.fleet.columns.length ? s.fleet.columns.map((c) => <Pill key={c.grain}>{c.label}</Pill>) : 'none'}
                  </span>
                </Row>
                <Row label="Grains refresh">every {s.fleet.grains_refresh_minutes} minutes</Row>
                <Row label="Job backfill" hint="Jobs imported from the master's job cache on each connect.">
                  up to {s.jobs_backfill_limit}
                </Row>
                <Row label="History kept" hint="retention: in the config. Older history is pruned hourly.">
                  {[
                    `jobs ${keptFor(s.retention.jobs_days)}`,
                    `presence and grains ${keptFor(s.retention.history_days)}`,
                    `audit log ${keptFor(s.retention.audit_days)}`,
                  ].join(' · ')}
                </Row>
              </Section>

              <PackagesAndChecks inventory={s.inventory} saltApi={s.salt_api} />

              <Section title="Server">
                <Row label="Version">{s.version}</Row>
                <Row label="Database">
                  {s.database.backend} · <code className="font-mono break-all">{s.database.url}</code>
                </Row>
              </Section>

              <SignIn auth={s.auth} />
            </>
          )
        )}
      </div>
    </>
  )
}
