# Salt versions

**brine aims to work with every Salt release the Salt Project still supports, and proves it in
CI.** Each push runs the end-to-end test against a real salt-master, salt-api and minions
installed from the official packages, once per release line (its latest release): currently
**3006, 3007 and 3008**. A new major release is added when it ships; one is dropped from CI
when Salt stops supporting it.

Salt 3005 and older aren't tested. brine's read-only views use functions that existed back then,
so they may well work, but those releases no longer get security fixes, and upgrading is the
better fix.

## Why brine is less fragile than browser-only UIs

- **The browser never talks to salt-api.** brine's backend does, so a difference between Salt
  versions is handled in one place, in Python, with tests, and the UI never sees it.
- **A small, stable set of Salt functions.** Everything brine calls is listed in
  [permissions-and-salt-acl.md](permissions-and-salt-acl.md): key, job and presence management,
  the master's grains cache, and the event bus. These have been around for many releases.
- **brine checks what the master offers instead of guessing from version numbers.** Presence uses
  `presence_events` when the master sends them and polls otherwise. Minions the master's presence
  detection can't see are flagged, not called offline. Write actions are offered only when the
  service account's ACL (read at login) allows them.

## What brine does about salt-api's rough edges

- **Sessions that end early.** SaltGUI's docs report Salt 3008.0 and 3008.1 ending its sessions
  after about a minute. When salt-api stops accepting brine's token, brine logs in again, once,
  and retries the request, so people don't see it.
- **The event stream failing.** SaltGUI's docs report the event API broken on 3008.2. brine's
  backend reconnects the stream with backoff and re-syncs what it may have missed; the browser
  only ever talks to brine.
- CI runs the latest release of each line (3008.3 today), not those older 3008 releases, so
  brine is built for both problems but hasn't been tested against them.
- **Bare 500s under load.** salt-api now and then fails a request when several arrive together.
  brine keeps at most four in flight and retries the ones that are safe to repeat
  ([decision 17](decisions.md)).

## Version differences worth knowing

- **3006 and newer:** salt-api refuses everything until `netapi_enable_clients` lists the clients
  it may use (brine needs `local`, `local_async`, `runner` and `wheel`). Salt now ships "onedir"
  packages with their own Python, and the master runs as the `salt` user, so PAM eauth needs that
  user in the `shadow` group, and in images without a system Python, `auth.pam.python` pointed at
  `/opt/saltstack/salt/bin/python3`.
- **3008:** hundreds of community modules were removed from Salt itself ("the great module
  migration"); some live on as separately installed extensions. Everything brine uses is still in
  core Salt, and CI would catch it if that changed.

## Mixed versions

Real fleets often have minions on an older release than the master. Most of what brine shows
comes through the master (keys, job returns, cached grains, presence), so the master's version is
what matters most. The minion page's live tabs (pillar, beacons, schedules, mine) call functions
on the minion itself; those exist in every supported release. Testing a master with older minions
in CI is on the [backlog](backlog.md).

## Trying a version locally

```bash
SALT_VERSION=3007 docker compose -f docker-compose.demo.yml up -d --build --wait
```

Switching versions needs fresh containers (`down` first); the keys and master cache volumes can
stay.
