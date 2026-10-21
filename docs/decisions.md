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

## 11. Pillar, beacons, schedules and mine are fetched live, not stored

They change rarely and are needed one minion at a time, so the minion page asks the minion when a
tab is opened (`/api/minions/{id}/live/{kind}`) and shows when it asked. Pillar goes through
`pillar.obfuscate`, so values never reach the browser; revealing them will need an admin role.

## 12. Don't call a minion offline when presence can't see it

Salt's presence detection matches TCP peers against IP grains in the master's minion data cache.
A minion missing from that cache is invisible to presence even while it answers jobs. brine
notes such minions whenever it reads the cache, shows them as stale instead of offline, and
raises an issue with the fix. Found on the demo fleet when a recreated master lost its cache.

## 13. Sessions are signed cookies; roles come from the config on every request

The session cookie holds only who signed in (email, name, picture), signed with a secret from
the config or, if none is set, one brine generates once and keeps in its database, so restarts
don't sign everyone out. There's no users table: the role is worked out from `roles` on every
request. Editing the config and restarting is how you grant or take away access, and it applies
to people who are already signed in. The cost is that a session can't be revoked on its own
before it expires; removing the person from `roles` does the same job.

## 14. Sign-in off has to be asked for

`auth.provider` defaults to `oidc`, and an OIDC block that's missing its issuer, client ID or
secret stops brine at startup with a pointer to the setup guide. Running with no sign-in takes an
explicit `provider: none`, and then every page shows a banner saying who everyone is treated as.
A typo in the config should never leave a fleet view open to the network.

## 15. Key actions re-check, match exactly, and follow the Salt ACL

Accepting the wrong key hands a machine your fleet's states and pillar, so key actions are
careful: brine re-reads the key from the master right before acting and refuses if it moved, or
(when accepting) if its fingerprint isn't the one the admin was shown. It calls Salt's
`key.*_dict` functions, which take exact IDs within one key state, because `key.accept` and
friends take a glob. Deleting a key, or rejecting an accepted one, takes typing the minion's name,
checked by the server as well as the UI.

brine's roles decide which people may ask; Salt's ACL decides what brine's account may do at all.
brine reads that ACL from the salt-api login and offers only what it allows, so a read-only
install never shows buttons that would fail.

## 16. Commands: preview first, allowlist per role, jobs belong to the person

The Run page never runs anything on Enter: it previews the exact minions a target matches (from
brine's key list for glob, list and regex targets; from the master's cache for grain, compound
and nodegroup ones) and running is a separate click. If the target matches other minions by
then, the run is refused and the preview shown again.

Two layers decide what runs. Salt's external_auth limits brine's account; `commands:` in brine's
config lists what each role may run (fnmatch, `runners.`/`wheel.` prefixes for master-side
functions). Admins default to everything the ACL allows, operators to nothing, viewers never.

Salt sees brine's service account as every job's user. brine tags the jobs it starts with
`metadata: {"brine": {"actor": <email>}}`, which Salt copies into every return event and the job
cache, so the jobs are recorded under the person even when a return arrives before brine has
written the job down, or while brine was restarting.

Words after the function are sent as typed, so Salt parses `key=value` and YAML values exactly as
the salt CLI does, rather than brine guessing.

## 17. salt-api is called a few requests at a time, and safe calls are retried

salt-api (rest_cherrypy) sometimes answers a request with a bare 500, "An unexpected error
occurred", when several arrive at once: on the demo, about 1 in 30 at four in flight, none at
two. brine keeps at most four requests in flight and retries a 500 twice for calls that are safe
to repeat (reads, and key changes, which match exact IDs). Starting a job and a person's runner
are never retried: the 500 may come after Salt started it, and it mustn't run twice.

## 18. Orchestrations belong to the person who ran them

Salt records a runner by the account that called salt-api (brine's), and the jobs an
orchestration's steps start as "salt". brine asks for the runner's jid (`full_return`), records
the run under the person, and imports each step's job from the job cache under them too. The
orchestration's job page lists its steps like a state run, each linked to the job it started.

## 19. Catch-up runs live in brine, and only run what someone asked for

Salt can make a minion do something when it starts (`startup_states`, a reactor on
`salt/minion/*/start`), but only as a blanket rule for every start, configured on the master.
brine's catch-up runs are per command: someone ticks the box on the Run page, brine stores the
command for each offline minion, and a sweep every 15 seconds sends each minion that's back (by a
fresh presence check) the oldest command it missed, waiting for its answer before the next.

Choices that keep it predictable:

- Nothing on the master or minions changes, and commands from the salt CLI are never repeated:
  people working on the master directly aren't affected. The jobs carry Salt metadata naming the
  person and the job they catch up on.
- Identical commands for the same minion collapse into the newest; different ones all run, in
  order. Runs expire (7 days by default).
- The person's allowlist is checked again at delivery, so a role change takes effect.
- Only minions a fresh presence check calls offline are queued. Without fresh presence, nothing
  is queued and nothing is sent, rather than guessing.
