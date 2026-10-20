<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brine-wordmark-light.svg">
    <img alt="brine" src="docs/assets/brine-wordmark-dark.svg" width="260">
  </picture>
</p>

<p align="center"><b>A modern, self-hosted web UI for Salt fleets.</b></p>

---

> **Status: early development.** Nothing here is usable yet. Follow [docs/backlog.md](docs/backlog.md) for progress.

brine plugs into an existing **salt-master + salt-api** and gives your team a clean, fast view of the fleet:

- **Single sign-on** through any OIDC provider (Google, GitHub, Okta, Keycloak, Azure AD). No Salt credentials for end users.
- **Live vs. cached, clearly separated.** Online now, or last seen *X* ago, with grains marked "as of" when they were collected.
- **Per-minion pages** with grains (current and history), recent jobs, and a presence timeline.
- **Job history that outlives Salt's job cache.**
- **An audit log** of who did what, on which minions, and when.
- **Configurable columns.** Show any grain (`app_version`, `firmware_version`, ...) in the fleet table, no code changes.
- **Parity with [SaltGUI](https://github.com/erwindon/SaltGUI)** as the baseline; see [docs/saltgui-parity.md](docs/saltgui-parity.md).

v1 is read-only. Running commands and applying states come next, behind roles, a targeting preview, and a confirmation step.

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
# backend: http://localhost:8000
cd backend
uv sync
cp ../config.example.yaml ../config.yaml   # then edit
BRINE_CONFIG=../config.yaml uv run uvicorn app.main:create_app --factory --reload

# frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Checks (the same ones CI runs):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## License

[MIT](LICENSE). brine is an independent project. It is not affiliated with or endorsed by the Salt Project, VMware, or Broadcom. "Salt" and "SaltStack" are trademarks of their respective owners.
