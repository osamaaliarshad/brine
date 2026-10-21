# Contributing to brine

Thanks for helping. Issues and pull requests are welcome; for anything big, open an issue first
so we can agree on the shape before you spend time on it.

## Set up

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22+, and Docker for the demo
Salt fleet.

### The demo Salt fleet

A salt-master with salt-api, four minions with custom grains, one minion waiting for key
approval, two orchestrations and a few templates. Nothing to configure:

```bash
docker compose -f docker-compose.demo.yml up -d --build --wait
uv run --project backend python demo/smoke_test.py --presence   # checks salt-api end to end
```

salt-api listens on `http://127.0.0.1:8001` (user `brine`, password `brine-demo`, eauth `pam`).
`SALT_VERSION=3007` or `3008` runs a newer Salt ([docs/salt-versions.md](docs/salt-versions.md)).
Stop a minion to watch it go offline: `docker compose -f docker-compose.demo.yml stop rover-03`.

### brine

```bash
# backend: http://localhost:8000, against the demo fleet
cd backend
uv sync
BRINE_CONFIG=../demo/brine.yaml uv run uvicorn app.main:create_app --factory --reload

# frontend: http://localhost:5173, proxying /api to the backend
cd frontend
npm install
npm run dev
```

The demo config runs with sign-in off: everyone is an admin, and a banner says so. To try real
sign-in, register an OIDC client ([docs/oidc-providers.md](docs/oidc-providers.md)), put its ID
and secret in `.env` (see `.env.example`) and point a `config.yaml` at it; both files are
git-ignored:

```bash
BRINE_CONFIG=../config.yaml uv run --env-file ../.env uvicorn app.main:create_app --factory --reload
```

## Checks

CI runs these on every push; run them before opening a pull request:

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
BRINE_DEMO_SALT_API=http://127.0.0.1:8001 uv run pytest tests/test_demo_integration.py  # needs the demo fleet
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
docker build -t brine:dev .
```

The README screenshots come from the demo fleet: with the backend running against it and the
frontend built, `node scripts/screenshots.mjs --stop-minion rover-03`. Never take them from a
real fleet: they're committed to a public repository.

## How the code is laid out

- `backend/app`: FastAPI. `salt/` talks to salt-api and keeps brine's database current from the
  event bus (`collector.py`); every database write goes through `ingest.py`; `api/` is the REST
  and SSE API; `auth/` is sign-in, sessions and roles.
- `frontend/src`: React and TypeScript. `pages/` has one folder per page; `api/` has the typed
  client and the TanStack Query hooks.
- `docs/decisions.md` explains the design choices that aren't obvious from the code. Read it
  before changing how presence, sessions, commands or catch-up runs work.

## Releasing

Add the version's notes under a `## [x.y.z]` heading in `CHANGELOG.md`, then push a `vx.y.z` tag.
The Release workflow publishes `ghcr.io/osamaaliarshad/brine:x.y.z` (and `latest`) and creates the
GitHub release with those notes.
