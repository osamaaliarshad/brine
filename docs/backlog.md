# Backlog

Short and prioritized. Top of each section is next. SaltGUI page-by-page mapping lives in
[saltgui-parity.md](saltgui-parity.md).

## Phase 0 — Environment and demo stack ✅

- [x] Repo scaffold: backend, frontend, CI, license, README
- [x] Docker Desktop installed on the dev machine
- [x] `docker-compose.demo.yml`: salt-master + salt-api (PAM user `brine`) + 4 accepted minions with custom grains + 1 pending, `presence_events: True`
- [x] `demo/smoke_test.py`: login, `test.ping`, grains, keys, `manage.status`, `/events`; stopping a minion shows up as `salt/presence/change`. Runs in CI on Salt 3006 and 3008

## Phase 1 — Backend core (read-only) ✅

- [x] Config loading (YAML + `${VAR}` + `BRINE__` env overrides)
- [x] Async salt-api client: token handling, re-login on 401 and before expiry, error mapping
- [x] Collector: snapshot sync (keys, presence, grains, job backfill) + event stream; reconnect with backoff
- [x] Presence: `salt/presence/*` events, falling back to polling `minions.connected` (or `manage.status` in `ping` mode); active method reported
- [x] DB models + Alembic (SQLite, Postgres optional): minions, presence changes, grains snapshots, jobs/returns, audit log
- [x] REST: fleet, minion detail, grains history (diffs), jobs (paged, filtered), job detail, keys, status; SSE `/api/stream`
- [x] Integration test against the demo stack (CI, Salt 3006 + 3008): offline/online, CLI jobs, master and backend restarts

Follow-ups found along the way:

- [ ] Retention: prune old jobs/returns/presence changes (`jobs.keep_days`)
- [ ] Large fleets: the fleet endpoint loads full grains for every minion; denormalize column values if it gets slow
- [x] CI end-to-end on Salt 3006, 3007 and 3008 ([docs/salt-versions.md](salt-versions.md))
- [ ] CI: a master with minions on an older Salt release (mixed fleets)
- [ ] Keys: "Waiting since" counts from first seen; track when a key last changed state, so a re-sent key shows its own wait
- [ ] Half-open connections: the event stream has no read timeout, so a silent network partition isn't noticed until a poll fails

## Phase 2 — Auth and roles

- [x] OIDC login (Google first), signed httpOnly cookie sessions (SameSite=Lax, Secure behind https), domain allowlist
- [x] Role mapping (viewer / operator / admin) by email pattern, re-checked on every request; every API endpoint locked
- [x] Sign-in off mode (`auth.provider: none`) for the demo, with a banner; half-configured OIDC refuses to start
- [x] Audit: sign-ins, refused sign-ins (with reason), sign-outs, pillar views; admin-only Audit log page
- [x] Sign-in page, user menu with sign-out, Settings › Sign-in
- [x] Docs: OIDC providers (docs/oidc-providers.md), Salt eauth ACL for the service account
- [x] CSRF: every write needs the `X-Requested-With` header
- [ ] Audit retention and export

## Phase 3 — Frontend v1 (SaltGUI read-only parity + brine extras)

- [x] Fleet table (per the mockup): stat cards, status dot, last seen + cached/stale badges, OS/Salt, grain columns (show/hide), search, status tabs, site filter, sort, pagination; view state in the URL
- [x] Fleet columns are customisable: add any grain the fleet reports (autocomplete), reorder, remove, reset; saved per browser; `fleet.columns` is the team default
- [ ] Admins save a column layout as the team default from the UI (needs roles, Phase 2)
- [x] Fleet: "Run command" button
- [ ] Fleet: row selection to run on the selected minions
- [x] Collapsible sidebar (button or `[`), "b" mark when collapsed; Configuration group
- [x] Fleet › Grains explorer (distribution of any grain, add as column) and Fleet › Nodegroups
- [x] States page (top file per state, state files) and Automation page (schedules, beacons fleet-wide)
- [x] Live views ask only minions presence says are online (offline ones listed as not asked)
- [x] docs/permissions-and-salt-acl.md: the read-only ACL brine needs
- [x] Minion page: connection facts, grains with "as of" (searchable), grains history as diffs, recent jobs, presence timeline; pillar (masked via pillar.obfuscate), beacons, schedules, mine fetched live
- [ ] Pillar: reveal values (admin role, audited)
- [ ] Mask returns of `pillar.*` functions run from the CLI (jobs and events) for non-admins: they contain real secrets
- [x] Jobs page (search, minion/runner filter, load older) + job detail (state-by-state results, missing minions); State runs view (SaltGUI's Highstate)
- [x] Keys page (read-only): states, fingerprints (`wheel key.finger`, second migration), pending first
- [x] Events page: live bus with summaries, pause, filter, presence toggle, expandable data; Reactors tab (only the `reactor` key leaves the server)
- [x] Issues page: failed states, offline/never-seen minions, pending keys, failed jobs, missing returns, version drift, salt-api/presence problems, presence-blind minions; feeds the Fleet card and a sidebar badge
- [ ] Issues: disabled beacons/schedules and CVE warnings (need live calls / a CVE list)
- [x] Settings: salt-api connection, configured vs active presence method, fleet/jobs defaults, database (password hidden), sign-in; theme (light/dark/system) and column reset
- [x] Live updates via SSE (debounced refetch), dark/light themes
- [x] Phone layout: the Fleet page switches to cards below 640px; other pages stack and scroll their tables

## Phase 4 — Release polish

- [x] `scripts/screenshots.mjs`: README screenshots per page, light + dark, from the demo fleet
- [ ] Dockerfile (frontend build → backend image), `docker-compose.yml`, GHCR publish in CI
- [ ] README screenshots/GIF (from the demo stack, never real fleet data) and 10-minute quickstart
- [ ] Docs: setup, presence, permissions; tag v0.1.0

## Phase 5 — Commands (SaltGUI write parity)

- [x] Key management: accept / reject / delete from the Keys page and minion pages; admin-only, fingerprint check to accept, typed name to delete or cut off an accepted minion, audited; exact-match `key.*_dict`; offered only when the Salt ACL allows (read at login); end-to-end test on the demo master
- [x] Run page: minion functions (async, results on the job page) and `runners.` / `wheel.` on the master; glob, list, compound, grain, nodegroup and regex targets; recent commands (per browser); shareable links that open previewed
- [x] Target preview (exact minion list, offline ones marked) before a separate Run click; the run is refused if the target matches other minions by then
- [x] Who may run what: `commands:` allowlist per role (admins default to anything the Salt ACL allows; viewers never); every run audited; jobs recorded under the person via Salt job metadata (end-to-end test on the demo)
- [ ] Function help in the command box (`sys.doc`) and autocomplete
- [ ] Long runners (orchestrations) as async jobs with live progress (`runner_async`), instead of waiting on the request
- [ ] Grains, beacons, schedules, mine actions; job re-run / terminate / kill
- [x] Templates: SaltGUI's `saltgui_templates` from the master and `templates:` in brine's config, by category, on the Run page
- [x] Orchestrations page: every orchestration SLS with its steps; Test / Run through the Run page; the runner and each step's job recorded under the person (Salt runs steps as "salt")
- [x] Runner commands recorded as jobs (`full_return` gives their jid)
- [x] salt-api returns bare 500s under concurrent requests: at most 4 in flight, safe calls retried
- [ ] Templates with parameters (fill-in fields), and SaltGUI's single-key template shortcuts
- [ ] Orchestrations: cache the listing for big file roots; other saltenvs

## Later

- Pillar / desired-config views and desired-vs-reported diffs
- Alerts and webhooks ("minion offline for 1 hour")
- Helm chart, multi-master workspaces (the mockup's workspace switcher)
- Keyboard shortcuts, MOTD banner
