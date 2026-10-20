# Design decisions

Short records of choices that aren't obvious from the code. Newest last.

## 1. Own config loader instead of pydantic-settings

The brief proposed pydantic-settings. Its YAML and env sources work, but `${VAR}` placeholders
need a custom source anyway, and nested env overrides are hard to explain. `app/config.py` is
about 100 lines and does three explicit steps: parse YAML, expand `${VAR}` in string values, apply
`BRINE__A__B` overrides, then validate with Pydantic. Placeholders are expanded *after* parsing,
so comments are ignored and an env value can never change the YAML structure.

Unknown keys are rejected, so a typo in `config.yaml` fails at startup instead of being silently
ignored. Secrets are `SecretStr` and never show up in logs or reprs.

## 2. React Router instead of TanStack Router

Fewer concepts for a small app with flat routes. TanStack Query still handles all server state.

## 3. Self-hosted fonts

Geist and Geist Mono ship through Fontsource, so a self-hosted brine makes no third-party
requests at runtime.

## 4. Wordmark as a CSS mask

The wordmark SVG has a fixed light fill. In the app it's used as a mask painted with
`currentColor`, so one file works in both themes. The README uses light and dark copies in
`docs/assets/`.

## 5. Node 24 LTS in CI and images

Local development works on newer Node versions, but CI and the container build pin the current
LTS line.

## 6. Demo fleet runs the official Salt packages

The demo image installs the Salt Project's own Debian packages from packages.broadcom.com, not pip,
so it behaves like real fleets: the master runs as the `salt` user and Salt brings its own
Python. It defaults to 3006 LTS, the most widely deployed line, and CI also runs it on the newest
release (3008). Three things the slim base image needed, each found the hard way:

- `usermod -aG shadow salt`: PAM eauth runs inside the unprivileged master and must read `/etc/shadow`.
- `auth.pam.python` pointed at Salt's bundled Python, because there's no `/usr/bin/python3`.
- `iproute2`: without it minions report no IP grains and presence detection sees nobody
  (see [presence-and-status.md](presence-and-status.md)).

The autosign file is copied in at startup rather than bind-mounted. Mounts from Windows hosts look
world-writable, and Salt ignores world-writable autosign files.

salt-api is published on `127.0.0.1:8001` so it doesn't collide with brine's own port 8000 in
development.

## 7. Presence times use brine's clock; job times use Salt's

"Is this observation fresh?" has to be answered by brine, so presence observations and "last
seen" are stamped with brine's own clock when they arrive. That way a master with a wrong clock
can't make the fleet look online forever. Job start/return times come from Salt's `_stamp`,
which records when things actually happened, even for jobs backfilled hours later.

## 8. The live stream sends hints, not data

`/api/stream` sends messages like `{"type": "minion", "id": "rover-03"}`. The browser re-fetches
what it shows through the normal REST API. One source of truth, no second serialization of every
object, and a dropped or reordered message can only make a view briefly old, never wrong. A slow
client whose queue overflows gets `{"type": "resync"}`.

## 9. brine doesn't record its own housekeeping jobs

The collector's own calls (grains refreshes, presence polls, backfill lookups) and the pings the
master runs for `manage.status` aren't stored as jobs. In polling mode they'd add over a
thousand rows a day of noise. Their effects still count: a `grains.items` return updates grains
and "last seen". Master-side wheel/runner calls that show up as `salt/job` events or in the job
cache aren't minion jobs either, so they're skipped. Runner jobs started by people (`salt/run/*`)
are recorded, with `kind: runner`.

## 10. One writer, idempotent writes

All database writes go through `Ingest`, which serializes them with a lock and is idempotent:
the same event twice, or a job seen both live and in a backfill, leaves the database unchanged.
That's what makes "re-sync everything after every reconnect" safe, and reconnect logic simple.
