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
- [ ] Half-open connections: the event stream has no read timeout, so a silent network partition isn't noticed until a poll fails

## Phase 2 — Auth and roles

- [ ] OIDC login (Google first), secure cookie sessions, domain/email allowlists
- [ ] Role mapping (viewer / operator / admin) enforced on every endpoint
- [ ] Audit: logins and views of sensitive data (pillar)
- [ ] Docs: OIDC providers, Salt eauth ACL for the service account

## Phase 3 — Frontend v1 (SaltGUI read-only parity + brine extras)

- [x] Fleet table (per the mockup): stat cards, status dot, last seen + cached/stale badges, OS/Salt, grain columns (show/hide), search, status tabs, site filter, sort, pagination; view state in the URL
- [x] Fleet columns are customisable: add any grain the fleet reports (autocomplete), reorder, remove, reset; saved per browser; `fleet.columns` is the team default
- [ ] Admins save a column layout as the team default from the UI (needs roles, Phase 2)
- [ ] Fleet: "Run command" and row selection (with Phase 5)
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
- [ ] Phone layout: works (table scrolls sideways); a card list would read better on small screens

## Phase 4 — Release polish

- [x] `scripts/screenshots.mjs`: README screenshots per page, light + dark, from the demo fleet
- [ ] Dockerfile (frontend build → backend image), `docker-compose.yml`, GHCR publish in CI
- [ ] README screenshots/GIF (from the demo stack, never real fleet data) and 10-minute quickstart
- [ ] Docs: setup, presence, permissions; tag v0.1.0

## Phase 5 — Commands (SaltGUI write parity)

- [ ] Run command box: local / async / runner / wheel, glob / list / compound / nodegroup targeting
- [ ] Targeting preview (exact minion list) + confirmation step; operator role; every run audited
- [ ] Key accept / reject / delete
- [ ] Grains, beacons, schedules, mine actions; job re-run / terminate / kill
- [ ] Templates, orchestrations

## Later

- Pillar / desired-config views and desired-vs-reported diffs
- Alerts and webhooks ("minion offline for 1 hour")
- Helm chart, multi-master workspaces (the mockup's workspace switcher)
- Keyboard shortcuts, MOTD banner
