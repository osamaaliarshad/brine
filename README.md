<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brine-wordmark-light.svg">
    <img alt="brine" src="docs/assets/brine-wordmark-dark.svg" width="260">
  </picture>
</p>

<p align="center"><b>A modern, self-hosted web UI for Salt fleets.</b></p>

---

> **Status: early development.** Every SaltGUI view has a brine page, and commands and key management work, all behind OIDC sign-in and roles. Still to come: SaltGUI's templates, orchestrations and job re-run/kill, and packaging (a Docker image and a quickstart). Follow [docs/backlog.md](docs/backlog.md) for progress.

brine plugs into an existing **salt-master + salt-api** and gives your team a clean, fast view of the fleet:

- **Single sign-on** through any OIDC provider: Google, Okta, Microsoft Entra, Keycloak, or GitHub via Dex ([setup](docs/oidc-providers.md)). Viewer, operator and admin roles by email pattern. No Salt credentials for end users.
- **Live vs. cached, clearly separated.** Online now, or last seen *X* ago, with grains marked "as of" when they were collected.
- **Per-minion pages** with grains (current and history), recent jobs, and a presence timeline.
- **Job history that outlives Salt's job cache.**
- **Run commands safely.** See exactly which minions a command reaches before it runs; a per-role allowlist decides who may run what.
- **An audit log** of who did what, on which minions, and when.
- **Configurable columns.** Show any grain (`app_version`, `firmware_version`, ...) in the fleet table, no code changes.
- **Parity with [SaltGUI](https://github.com/erwindon/SaltGUI)** as the baseline; see [docs/saltgui-parity.md](docs/saltgui-parity.md).
- **Least privilege.** brine needs only a read-only Salt account (plus three functions if you want key management); the exact ACL is in [docs/permissions-and-salt-acl.md](docs/permissions-and-salt-acl.md).
- **Every supported Salt release**, tested end to end in CI against a real master: [docs/salt-versions.md](docs/salt-versions.md).

Commands run from the Run page, behind roles, an exact target preview and a confirmation click.

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

**Grains** shows how any grain is spread across the fleet (which robots run which app or firmware
version) and adds it as a column in one click:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/grains-dark.png">
  <img alt="Grains explorer: app_version values across the fleet with counts and shares" src="docs/assets/screenshots/grains-light.png">
</picture>

**Nodegroups** lists the master's nodegroups with their members and how many are online:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/nodegroups-dark.png">
  <img alt="Nodegroups: docks, rovers and site-a with member minions and online counts" src="docs/assets/screenshots/nodegroups-light.png">
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

### Run

SaltGUI's command box, with a safety catch. Type a target and a command the way you would after
`salt` on the master (`state.apply motd test=True`), or `runners.` / `wheel.` ones for the master
itself. brine first shows exactly which minions it reaches, and which of those are offline;
running is a separate click, and the results land on the job page as they arrive. Who may run
what is a per-role allowlist in brine's config, every run is in the audit log, and links like
`/run?target=rover-*&command=test.ping` open already previewed.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/run-dark.png">
  <img alt="The Run page: state.apply motd test=True previewed on rover-01, rover-02 and rover-03" src="docs/assets/screenshots/run-light.png">
</picture>

### Keys

Every minion key the master knows, with its fingerprint and whether that minion is around. Keys
waiting for approval come first. Admins accept, reject and delete keys here (or from a minion's
page): accepting shows the fingerprint to check, deleting takes typing the minion's name, and
every change lands in the audit log. Needs [three more Salt functions](docs/permissions-and-salt-acl.md#4-optional-key-management);
without them brine stays read-only for keys and says so.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/keys-dark.png">
  <img alt="The Keys page: rover-04 waiting for approval, four accepted keys with fingerprints" src="docs/assets/screenshots/keys-light.png">
</picture>

### States

What the master tells each minion to be: which states the top file assigns to which minions
(asked live, skipping minions that are offline), and the state files themselves.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/states-dark.png">
  <img alt="States: motd and dock states with the minions they apply to" src="docs/assets/screenshots/states-light.png">
</picture>

### Automation

What runs on its own: every minion's schedules and beacons in one place, asked live.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/automation-dark.png">
  <img alt="Automation: a refresh-grains schedule on each minion" src="docs/assets/screenshots/automation-light.png">
</picture>

### Events

The Salt event bus as it happens: each event with a plain-language summary, expandable to its
full data. Pause, filter, and hide the presence heartbeat. A Reactors tab lists the master's
reactor configuration.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/events-dark.png">
  <img alt="The Events page: job, auth and wheel events with one-line summaries" src="docs/assets/screenshots/events-light.png">
</picture>

### Issues

What needs a human, most serious first: failed states, minions gone offline, keys waiting for
approval, recent jobs with failures or missing returns, Salt version drift, and problems with
brine's own view (salt-api unreachable, stale presence, minions presence can't see). Each links
to the minion or job. The count also appears on the Fleet page and in the sidebar.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/issues-dark.png">
  <img alt="The Issues page: a failed state on dock-01, rover-03 offline, rover-04 waiting for approval" src="docs/assets/screenshots/issues-light.png">
</picture>

### Audit log

Admins only. Every sign-in (and every refused one, with the reason), sign-out, and look at
sensitive data such as a minion's pillar, with who, when and from where. Commands will land here
too.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/audit-dark.png">
  <img alt="The Audit log page: sign-ins, refused sign-ins and pillar views" src="docs/assets/screenshots/audit-light.png">
</picture>

### Settings

What this brine is running with: the salt-api connection and service account, which presence
method is active, fleet defaults, database, and how sign-in and roles are set up (pattern
counts, not who holds them). Secrets never leave the server. Plus
per-browser choices: theme (light, dark or follow the system) and resetting custom columns.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/settings-dark.png">
  <img alt="The Settings page: connection, presence, fleet and server settings" src="docs/assets/screenshots/settings-light.png">
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
Use `SALT_VERSION=3007` or `3008` to run a newer Salt ([docs/salt-versions.md](docs/salt-versions.md)). Stop a minion to watch it go offline:
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

The demo config runs with sign-in off: everyone is an admin, and a banner says so. To try real
sign-in, register an OIDC client ([docs/oidc-providers.md](docs/oidc-providers.md)), put its ID
and secret in a git-ignored `.env` (see `.env.example`), and point a git-ignored `config.yaml` at
it:

```bash
BRINE_CONFIG=../config.yaml uv run --env-file ../.env uvicorn app.main:create_app --factory --reload
```

Checks (the same ones CI runs):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
BRINE_DEMO_SALT_API=http://127.0.0.1:8001 uv run pytest tests/test_demo_integration.py  # needs the demo fleet
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## License

[MIT](LICENSE). brine is an independent project. It is not affiliated with or endorsed by the Salt Project, VMware, or Broadcom. "Salt" and "SaltStack" are trademarks of their respective owners.
