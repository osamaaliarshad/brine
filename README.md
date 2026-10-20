<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brine-wordmark-light.svg">
    <img alt="brine" src="docs/assets/brine-wordmark-dark.svg" width="260">
  </picture>
</p>

<p align="center"><b>A modern, self-hosted web UI for Salt fleets.</b></p>

---

> **Status: early development.** The backend and the Fleet page work against the demo fleet; sign-in and the other pages are next. Follow [docs/backlog.md](docs/backlog.md) for progress.

brine plugs into an existing **salt-master + salt-api** and gives your team a clean, fast view of the fleet:

- **Single sign-on** through any OIDC provider (Google, GitHub, Okta, Keycloak, Azure AD). No Salt credentials for end users.
- **Live vs. cached, clearly separated.** Online now, or last seen *X* ago, with grains marked "as of" when they were collected.
- **Per-minion pages** with grains (current and history), recent jobs, and a presence timeline.
- **Job history that outlives Salt's job cache.**
- **An audit log** of who did what, on which minions, and when.
- **Configurable columns.** Show any grain (`app_version`, `firmware_version`, ...) in the fleet table, no code changes.
- **Parity with [SaltGUI](https://github.com/erwindon/SaltGUI)** as the baseline; see [docs/saltgui-parity.md](docs/saltgui-parity.md).

v1 is read-only. Running commands and applying states come next, behind roles, a targeting preview, and a confirmation step.

## Pages

Screenshots follow your light/dark preference and come from the [demo fleet](#demo-salt-fleet),
regenerated with `node scripts/screenshots.mjs --stop-minion rover-03`.

### Fleet

Every minion at a glance: online now or last seen when, OS and Salt version, and any grains you
choose as columns. Search, filter by status or site, sort, and pick columns (add any grain the
fleet reports, reorder, remove; saved per browser, with the config's `fleet.columns` as the team
default). Updates live as minions come and go.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/fleet-dark.png">
  <img alt="The Fleet page: three minions online, one offline, with site, app version and firmware columns" src="docs/assets/screenshots/fleet-light.png">
</picture>

### Minion

Everything about one minion: connection and how long it's been that way, every grain with when
it was collected, grains history as diffs, recent jobs, and an online/offline timeline. Pillar
(values masked), beacons, schedules and mine are fetched live from the minion on demand.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/minion-dark.png">
  <img alt="A minion page: connection facts, tabs for grains, history, jobs, timeline, pillar, beacons, schedules and mine" src="docs/assets/screenshots/minion-light.png">
</picture>

### Jobs

Every job the master runs, recorded as it happens and kept after the master's job cache forgets
it (plus a backfill of whatever the cache still holds when brine connects). Search by function,
target, user or job ID; filter minion jobs and runners.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/jobs-dark.png">
  <img alt="The Jobs page: recent jobs with target, user, start time and per-minion results" src="docs/assets/screenshots/jobs-light.png">
</picture>

**State runs** shows each minion's latest `state.apply`/highstate as one square per state, like
SaltGUI's Highstate page:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/state-runs-dark.png">
  <img alt="State runs: each minion's latest state run, with a failed state on dock-01" src="docs/assets/screenshots/state-runs-light.png">
</picture>

### Job

One job in full: the command, who ran it, how long it took, which minions never answered, and each
minion's result. State runs are broken down state by state; anything else is shown as a tree.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/job-dark.png">
  <img alt="A state.apply job: dock-01's calibration state failed, the rovers succeeded" src="docs/assets/screenshots/job-light.png">
</picture>

### Keys

Every minion key the master knows, with its fingerprint and whether that minion is around. Keys
waiting for approval come first. (Accepting and rejecting from brine arrives with roles and the
audit log.)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/keys-dark.png">
  <img alt="The Keys page: rover-04 waiting for approval, four accepted keys with fingerprints" src="docs/assets/screenshots/keys-light.png">
</picture>

## How it fits

```
YOUR EXISTING SETUP                 BRINE (docker compose up)
┌──────────────────────┐            ┌────────────────────────────────┐
│ salt-master          │            │ backend (FastAPI)              │
│ salt-api  ◀──────────┼── HTTPS ───┤  ├─ OIDC login + sessions      │
│ minions (untouched)  │            │  ├─ salt-api client            │
└──────────────────────┘            │  ├─ event listener → database  │
                                    │  ├─ roles + audit log          │
┌──────────────────────┐            │  └─ serves the web UI          │
│ OIDC provider        │◀── login ──┤ database (SQLite / Postgres)   │
└──────────────────────┘            └────────────────────────────────┘
```

- **Nothing to install on minions**, and brine doesn't need to run on the master host. It's just another salt-api client.
- **salt-api is never exposed to browsers.** Only the backend talks to it, with a dedicated least-privilege service account.

## Quickstart

*Coming with v0.1.0:* a 10-minute guide to connect brine to your own Salt setup, plus a demo mode that runs with no real infrastructure.

## Development

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22+, and Docker (for the demo Salt stack).

### Demo Salt fleet

A salt-master with salt-api, four minions with custom grains, and one minion waiting for key
approval. Nothing to configure:

```bash
docker compose -f docker-compose.demo.yml up -d --build --wait
uv run --project backend python demo/smoke_test.py --presence   # checks salt-api end to end
```

salt-api listens on `http://127.0.0.1:8001` (user `brine`, password `brine-demo`, eauth `pam`).
Use `SALT_VERSION=3008` to run a newer Salt. Stop a minion to watch it go offline:
`docker compose -f docker-compose.demo.yml stop rover-03`.

### brine

```bash
# backend: http://localhost:8000 (against the demo fleet; use your own config.yaml for real ones)
cd backend
uv sync
BRINE_CONFIG=../demo/brine.yaml uv run uvicorn app.main:create_app --factory --reload

# frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Checks (the same ones CI runs):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
BRINE_DEMO_SALT_API=http://127.0.0.1:8001 uv run pytest tests/test_demo_integration.py  # needs the demo fleet
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## License

[MIT](LICENSE). brine is an independent project. It is not affiliated with or endorsed by the Salt Project, VMware, or Broadcom. "Salt" and "SaltStack" are trademarks of their respective owners.
