# Backlog

Short and prioritized. Top of each section is next. SaltGUI page-by-page mapping lives in
[saltgui-parity.md](saltgui-parity.md).

## Phase 0 — Environment and demo stack (now)

- [x] Repo scaffold: backend, frontend, CI, license, README
- [ ] Docker Desktop installed on the dev machine
- [ ] `docker-compose.demo.yml`: salt-master + salt-api (demo eauth user) + 4 minions with custom grains, `presence_events: True`
- [ ] Verify from the host: login, `test.ping`, `grains.items`, `/events` stream; stopping a minion is visible

## Phase 1 — Backend core (read-only)

- [x] Config loading (YAML + `${VAR}` + `BRINE__` env overrides)
- [ ] Async salt-api client: token handling, re-login on 401, timeouts
- [ ] Event listener: presence, job returns, grains refreshes; reconnect with backoff
- [ ] Presence fallback: periodic `manage.status`; report which method is active
- [ ] DB models + Alembic: minions, presence history, grains snapshots, jobs/returns, audit log
- [ ] REST: fleet list, minion detail, jobs, keys; SSE stream for live updates
- [ ] Integration test against the demo stack; survives backend and master restarts

## Phase 2 — Auth and roles

- [ ] OIDC login (Google first), secure cookie sessions, domain/email allowlists
- [ ] Role mapping (viewer / operator / admin) enforced on every endpoint
- [ ] Audit: logins and views of sensitive data (pillar)
- [ ] Docs: OIDC providers, Salt eauth ACL for the service account

## Phase 3 — Frontend v1 (SaltGUI read-only parity + brine extras)

- [ ] Fleet table (per the mockup): stat cards, status dot, last seen, OS/Salt, grain columns, search, filters, pagination
- [ ] Minion page: live/cached badge, grains with "as of" + history diff, pillar (masked), beacons, schedules, mine, jobs, presence timeline
- [ ] Jobs page + job detail; Highstate view
- [ ] Keys page (read-only)
- [ ] Events page (live) + reactors
- [ ] Issues page (SaltGUI's detectors + stale/offline)
- [ ] Settings: active config, presence method, salt-api status
- [ ] Live updates via SSE, dark/light themes, phone layout

## Phase 4 — Release polish

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
