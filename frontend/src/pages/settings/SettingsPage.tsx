import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { useSettings, useSystemStatus } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Card, Pill, StatusDot } from '@/components/ui'
import { cn } from '@/lib/cn'
import { getThemePreference, setThemePreference, type ThemePreference } from '@/lib/theme'
import { formatAbsolute, formatRelative, useNow } from '@/lib/time'
import { DEFAULT_PREFS, loadPrefs, savePrefs } from '@/pages/fleet/columnPrefs'

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b px-5 py-4 sm:px-6">
        <h2 className="font-semibold">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      <dl className="divide-y">{children}</dl>
    </Card>
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

export function SettingsPage() {
  const now = useNow()
  const settings = useSettings()
  const status = useSystemStatus()
  const s = settings.data
  const api = status.data?.salt_api

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
              </Section>

              <Section title="Server">
                <Row label="Version">{s.version}</Row>
                <Row label="Database">
                  {s.database.backend} · <code className="font-mono break-all">{s.database.url}</code>
                </Row>
                <Row label="Sign-in" hint="Single sign-on and roles are next on the roadmap.">
                  {s.auth.configured ? `OIDC via ${s.auth.issuer}` : 'Not configured yet'}
                </Row>
              </Section>
            </>
          )
        )}
      </div>
    </>
  )
}
