<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brine-logo-light.svg">
    <img alt="brine" src="docs/assets/brine-logo-dark.svg" width="300">
  </picture>
</p>

<p align="center"><b>A modern, self-hosted web UI for Salt fleets.</b></p>

<p align="center">
  <a href="https://github.com/osamaaliarshad/brine/releases/latest">Latest release</a> ·
  <a href="#try-it">Try it</a> ·
  <a href="#install">Install</a> ·
  <a href="#pages">Pages</a> ·
  <a href="docs/saltgui-parity.md">Coming from SaltGUI</a>
</p>

<p align="center">
  <img alt="The Fleet page, in the light theme on the left and the dark theme on the right: four minions with their connection, OS and Salt version, site, app version and firmware" src="docs/assets/screenshots/fleet-hero.png">
</p>

---

brine plugs into an existing **salt-master + salt-api** and gives your team a clean, fast view of
the fleet, and a safe way to act on it:

- **Single sign-on** through any OIDC provider: Google, Okta, Microsoft Entra, Keycloak, or GitHub
  via Dex ([setup](docs/oidc-providers.md)). Viewer, operator and admin roles by email pattern.
  Nobody needs Salt credentials.
- **Live and cached, clearly told apart.** Online now, or last seen *X* ago, with grains marked
  with when they were collected.
- **Job history that outlives Salt's job cache,** each job under the person who ran it.
- **Run commands safely.** See exactly which minions a command reaches before it runs; a per-role
  allowlist decides who may run what.
- **Catch-up runs.** Tick a box, and minions that are offline get the command when they come
  back, without highstate, `startup_states` or reactors.
- **An audit log** of who did what, on which minions, and when.
- **Any grain as a column** (`app_version`, `firmware_version`, ...) in the fleet table, no code
  changes.
- **What's installed where.** Packages from each minion's own package manager, plus your own
  checks for anything else (one-line commands in `inventory.checks`), kept over time. Each change
  shows the job it was found after, when brine can tell. Compare any minion with a golden one.
- **Everything [SaltGUI](https://github.com/erwindon/SaltGUI) does,** and your
  `saltgui_templates` keep working ([coming from SaltGUI](docs/saltgui-parity.md)).
- **Least privilege.** brine needs a read-only Salt account, plus a few functions for keys,
  commands and checks if you want them ([the exact ACL](docs/permissions-and-salt-acl.md)).
- **Every supported Salt release** (3006, 3007, 3008), tested end to end in CI against a real
  master ([salt-versions](docs/salt-versions.md)).

Nothing is installed on the master or the minions, and brine doesn't have to run on the master:
it's one container that talks to salt-api like any other client.

## Try it

A demo Salt fleet (a master with salt-api and five minions) and brine, on your machine, with
nothing to configure. You need Docker and git:

```bash
git clone https://github.com/osamaaliarshad/brine.git
cd brine
docker compose -f docker-compose.demo.yml --profile brine up -d --build --wait
```

Open <http://localhost:8080> (port taken? Start it with `BRINE_PORT=8090` in front). Sign-in
is off in the demo, so you're an admin. Stop a minion to watch it go offline
(`docker compose -f docker-compose.demo.yml stop rover-03`), and remove it all with
`docker compose -f docker-compose.demo.yml --profile brine down -v`.

## Install

You need a salt-master with salt-api (`rest_cherrypy`), Docker on a machine that can reach
salt-api (the master itself is fine), and an OIDC provider for sign-in.

**1. Give brine a Salt account.** On the master, create the account, enable the salt-api clients
brine uses, and paste in its ACL: [docs/permissions-and-salt-acl.md](docs/permissions-and-salt-acl.md).
The read-only ACL is enough to start; keys, commands and checks are optional extras.

**2. Register brine with your sign-in provider.** One "web application" client with the redirect
URI `<where people open brine>/api/auth/callback`: [docs/oidc-providers.md](docs/oidc-providers.md)
has Google, Okta, Entra, Keycloak and GitHub.

**3. Get the compose file and the example config** from the
[latest release](https://github.com/osamaaliarshad/brine/releases/latest):

```bash
mkdir brine && cd brine
curl -fsSLO https://github.com/osamaaliarshad/brine/releases/latest/download/docker-compose.yml
curl -fsSL -o config.yaml https://github.com/osamaaliarshad/brine/releases/latest/download/config.example.yaml
```

**4. Fill in `config.yaml`:** `salt_api.url`, `public_url`, `auth.issuer` and `roles` at least.
Every setting is explained in the file. Secrets stay out of it, as `${VAR}` placeholders, in a
`.env` file next to it:

```bash
SALT_API_PASSWORD=...
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
```

**5. Start it:**

```bash
docker compose up -d
```

brine listens on port 8080 (`BRINE_PORT` in `.env` changes it). Settings shows what it's
connected to; Issues says if something's off.

### Good to know

- **Changing the config:** edit `config.yaml` and run `docker compose restart`; brine reads it
  when it starts. Any setting can also be set in `.env` as `BRINE__SECTION__KEY` (e.g.
  `BRINE__INVENTORY__REFRESH_HOURS=2`), which wins over `config.yaml`. After changing `.env`, run
  `docker compose up -d` instead: a restart keeps the old values.
- **On the master itself,** point `salt_api.url` at `https://host.docker.internal:8000` (the
  compose file maps that name to the host). salt-api has to listen on more than `127.0.0.1` for
  a container to reach it.
- **salt-api with a self-signed certificate:** set `salt_api.verify_tls: false`, or give salt-api
  a certificate the container trusts.
- **For your team,** put brine behind a reverse proxy with HTTPS, and set `public_url` to the
  address people use, so session cookies are marked Secure.
- **Data** lives in the `brine-data` volume (SQLite). For PostgreSQL, set
  `database: postgresql://user:pass@host/brine`. History is pruned after 90 days (`retention`).
- **Upgrading:** `docker compose pull && docker compose up -d`. brine updates its database by
  itself on start. Pin a version with `image: ghcr.io/osamaaliarshad/brine:0.1.0`.
- **Without Docker:** brine is a Python app with a built frontend; [CONTRIBUTING.md](CONTRIBUTING.md)
  runs it from source.
- **Robots and other machines on flaky links:** [docs/salt-on-robots.md](docs/salt-on-robots.md)
  covers installing the minion on Jetson boards, settings that help it reconnect, holding JetPack
  packages, and keeping the master safe.

## Pages

Screenshots follow your light/dark preference and come from the demo fleet.

### Fleet

Every minion at a glance: online now or last seen when, OS and Salt version, and any grain,
package or check you choose as a column. Search, filter by status, sort, and pick columns (find
any grain, package or check the fleet reports and add it, reorder, remove; saved per browser,
with the config's `fleet.columns` as the team default). Updates live as minions come and go.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/fleet-dark.png">
  <img alt="The Fleet page: three minions online, one offline, with site, app version and firmware columns" src="docs/assets/screenshots/fleet-light.png">
</picture>

**Grains & packages** shows how any grain, package or check is spread across the fleet: which
machines run which version, which don't have it at all, and which haven't answered yet. It
lists the checks and the packages that differ across the fleet; type to find any other package.
Open a version to see its minions; if you may run commands, **Run on these** opens the Run page
with just them (nothing runs until you click Run). Add any of them as a column in one click.
Open **Changes** to see each change with the job it was found after, or the time between two
reads when brine can't tell.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/grains-dark.png">
  <img alt="Grains & packages: the rover-agent package at 2.4.1 on three minions and not installed on dock-01; rover-03's upgrade from 2.3.0, found after a job run by local" src="docs/assets/screenshots/grains-light.png">
</picture>

**Nodegroups** lists the master's nodegroups with their members and how many are online:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/nodegroups-dark.png">
  <img alt="Nodegroups: docks, rovers and site-a with member minions and online counts" src="docs/assets/screenshots/nodegroups-light.png">
</picture>

### Minion

Everything about one minion: connection and how long it's been that way, every grain with when
it was collected, its packages and checks, recent jobs, and an online/offline timeline. History
shows grain, package and check changes on one timeline. Pillar (values masked), beacons,
schedules and mine are fetched live from the minion on demand.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/minion-dark.png">
  <img alt="A minion page: connection facts, tabs for grains, packages, history, jobs, timeline, pillar, beacons, schedules and mine" src="docs/assets/screenshots/minion-light.png">
</picture>

**Packages** lists every package the minion has, and what each check printed, with when it last
changed. Compare it with another minion, such as a golden robot, to see every difference, or see
how the whole fleet differs from it:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/packages-dark.png">
  <img alt="rover-01's Packages tab compared with dock-01: rover-agent 2.4.1 against not installed, and the rover-cli check, rover-cli 1.2.0 against not reported" src="docs/assets/screenshots/packages-light.png">
</picture>

### Jobs

Every job the master runs, recorded as it happens and kept after the master's job cache forgets
it (plus whatever the cache still holds when brine first connects). Search by function, target,
user or job ID; filter minion jobs and runners.

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
Run it again, or stop it on the minions still running it.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/job-dark.png">
  <img alt="A state.apply job: dock-01's calibration state failed, the rovers succeeded" src="docs/assets/screenshots/job-light.png">
</picture>

### Run

SaltGUI's command box, with a safety catch. Type a target and a command the way you would after
`salt` on the master (`state.apply motd test=True`), or `runners.` / `wheel.` ones for the master
itself. brine first shows exactly which minions it reaches, and which of those are offline;
running is a separate click, it runs on exactly those minions, and the results land on the job
page as they arrive. Who may run what is a per-role allowlist in brine's config, every run is in
the audit log, and links like `/run?target=rover-*&command=test.ping` open already previewed.
Templates (brine's own, or SaltGUI's `saltgui_templates` from the master config, unchanged) fill
it in with one click, and `{{ name }}` anywhere in a template becomes a field to fill in first:
"Deploy branch `{{ branch }}` to `{{ minion }}`" is one click and two answers.

When some targeted minions are offline, you can have them **catch up**: tick "Also run it on the
offline minions when they're back" and brine remembers the command and runs it on each one as it
reconnects, one command at a time, newest wins for repeats, giving up after 7 days. The job page
shows who's still waiting (and lets you cancel), and each one's result once it has caught up;
each catch-up is also its own job, under your name.
It all lives in brine: nothing is installed on the master, and commands run from the salt CLI are
never repeated.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/run-dark.png">
  <img alt="The Run page: state.apply motd test=True previewed on rover-01, rover-02 and rover-03" src="docs/assets/screenshots/run-light.png">
</picture>

### Keys

Every minion key the master knows, with its fingerprint and whether that minion is around. Keys
waiting for approval come first. Admins accept, reject and delete keys here (or from a minion's
page): accepting shows the fingerprint to check, deleting takes typing the minion's name, and
every change lands in the audit log. Needs [three more Salt functions](docs/permissions-and-salt-acl.md#5-optional-key-management);
without them brine stays read-only for keys and says so.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/keys-dark.png">
  <img alt="The Keys page: rover-04 waiting for approval, four accepted keys with fingerprints" src="docs/assets/screenshots/keys-light.png">
</picture>

### States

What the master tells each minion to be: the top file, grouped by folder and foldable, with the
minions each state applies to (asked live, skipping minions that are offline), and the state
files themselves in a folder tree, colored as in an editor (keys, state functions, Jinja).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/states-dark.png">
  <img alt="States: the dock and motd states with the minions they apply to, rover-03 offline and not asked" src="docs/assets/screenshots/states-light.png">
</picture>

### Orchestrations

Every orchestration on the master, step by step: what each step does, on which minions, and what
it waits for. Orchestrations that take their inputs from pillar at run time (the way reactors pass
them) still show their steps, with `<minion_id>`-style placeholders, and running one asks for
each input. Test and Run go through the Run page, so they're previewed, confirmed and audited
like any command. The run, and the job each step starts, are recorded under whoever ran it, and
the orchestration's job page links every step to its minions' results.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/orchestrations-dark.png">
  <img alt="Orchestrations: orch.health and orch.rollout with their steps, targets and requisites" src="docs/assets/screenshots/orchestrations-light.png">
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
brine's own view (salt-api unreachable, stale presence, minions presence can't see, packages or
checks Salt won't let it read). Each links to the minion, job or setting. The count also appears
on the Fleet page and in the sidebar.

Issues aren't stored: each is worked out from the fleet as it is, so once it's fixed it's gone.
Mark an issue as read (or all of them at once) and it's out of your way, and out of your count,
until it changes: a minion going offline again, other states failing, a state failing again
after a clean run. Your mark goes when the issue does, so if it comes back, it's new. It's only
for you; everyone else still sees it. With sign-in off everyone is the same person, so marks are
shared. Read issues are a click away, to mark as unread.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/issues-dark.png">
  <img alt="The Issues page: a failed state on dock-01, rover-03 offline, rover-04 waiting for key approval, each with Mark as read" src="docs/assets/screenshots/issues-light.png">
</picture>

### Audit log

Admins only. Every sign-in (and every refused one, with the reason), sign-out, command run, key
change, catch-up and look at sensitive data such as a minion's pillar, with who, when and from
where.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/audit-dark.png">
  <img alt="The Audit log page: a test.ping run on rover-* and pillar views, with filters for sign-ins, commands, keys and data access" src="docs/assets/screenshots/audit-light.png">
</picture>

### Settings

What this brine is running with: the salt-api connection and service account, which presence
method is active, fleet defaults, packages and checks (how often, which checks, and the Salt
lines they need), retention, database, and how sign-in and roles are set up (pattern counts, not
who holds them). Secrets never leave the server. Plus per-browser choices: theme (light, dark or
follow the system) and resetting custom columns.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/settings-dark.png">
  <img alt="The Settings page: connection, presence, fleet and server settings" src="docs/assets/screenshots/settings-light.png">
</picture>

## How it fits

```
YOUR EXISTING SETUP                 BRINE (docker compose up)
┌──────────────────────┐            ┌────────────────────────────────┐
│ salt-master          │            │ backend (FastAPI)              │
│ salt-api  ◀──────────┼── HTTPS ───┤  ├─ OIDC sign-in + sessions    │
│ minions (untouched)  │            │  ├─ salt-api client            │
└──────────────────────┘            │  ├─ event listener → database  │
                                    │  ├─ roles + audit log          │
┌──────────────────────┐            │  └─ serves the web UI          │
│ OIDC provider        │◀── login ──┤ database (SQLite / Postgres)   │
└──────────────────────┘            └────────────────────────────────┘
```

- **salt-api is never exposed to browsers.** Only the backend talks to it, with one
  least-privilege service account.
- **People who use the salt CLI on the master aren't affected.** brine reads the same event bus
  and job cache; it never changes the master's config, and never repeats their commands.
- **Roles are checked on every request,** so removing someone from the config takes effect on
  their next click.

[SECURITY.md](SECURITY.md) has what brine protects, the limits worth knowing, and how to report a
problem privately. [docs/decisions.md](docs/decisions.md) explains the design choices.

## What's next

Enabling and disabling schedules and beacons, revealing pillar values to admins, selecting minions
in the fleet table to run something on them, and testing older minions under a newer master in
CI. Ideas and issues are welcome.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) has the development setup (backend, frontend and the demo
fleet), the checks CI runs, and how releases are made.

## License

[MIT](LICENSE). brine is an independent project. It is not affiliated with or endorsed by the Salt Project, VMware, or Broadcom. "Salt" and "SaltStack" are trademarks of their respective owners.
