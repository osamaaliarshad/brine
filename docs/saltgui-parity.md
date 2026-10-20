# SaltGUI parity

brine aims to cover everything [SaltGUI](https://github.com/erwindon/SaltGUI) does, then add its own
features. This maps each SaltGUI page to where it lives in brine and in which phase it lands.
Inventory taken from SaltGUI `master` @ `c76b1fd` (v1.35.0-SNAPSHOT, October 2026).

SaltGUI is MIT licensed (© 2016–2026 Oliver Dunk, Martijn Jacobs, Erwin Dondorp). brine uses it as a
reference for salt-api calls. If any code is ever copied, its copyright notice goes in
`THIRD_PARTY_NOTICES.md`.

## How SaltGUI works, in short

- The browser talks to salt-api directly, using the user's own Salt eauth credentials.
- Every row or panel action only **pre-fills the command box**; nothing runs until "Run command".
- Pages read from: `wheel key.list_all`, `wheel minions.connected`, `local grains.items` (or
  `runner cache.grains`), `runner manage.versions`, `runner jobs.list_jobs` / `jobs.active` /
  `jobs.list_job`, `local pillar.obfuscate` / `pillar.items`, `local beacons.list`,
  `local schedule.list`, `local mine.valid` / `mine.get`, `wheel config.values`, `/events`.
- Online/offline = "in `minions.connected`" and "answered `grains.items`". There is no last-seen
  time and no presence tracking. The event stream doesn't reconnect after an error.

## Page mapping

| SaltGUI | brine | Phase | Notes |
|---|---|---|---|
| Login (eauth user/password) | OIDC single sign-on | 2 | Users never see Salt credentials; the backend uses one service account |
| Session expiry countdown | Cookie session + re-auth | 2 | |
| `saltgui_pages` (per-user menus) | Roles (viewer / operator / admin) | 2 | Enforced server-side, unlike SaltGUI's cosmetic filter |
| Minions | Fleet table | 3 | Adds stat cards, live/stale/offline, last seen, grain columns, pagination |
| Minions: version / CVE warnings | Fleet + Issues | 3 | From `manage.versions` |
| Grains (+ `saltgui_preview_grains`) | Fleet columns (`fleet.columns` in config) | 3 | |
| Grains per minion | Minion › Grains | 3 | Adds "as of" timestamp and history diff |
| Pillars (masked, `saltgui_public_pillars`) | Minion › Pillar | 3 | Masked by default; unmasking is audited |
| Mine | Minion › Mine | 3 | |
| Beacons | Minion › Beacons | 3 | Live values from `salt/beacon/*` events |
| Schedules | Minion › Schedules | 3 | |
| Nodegroups | Fleet filter / group-by | 3 | |
| Keys | Keys page | 3 / 5 | View in 3; accept / reject / delete in 5 |
| Jobs | Jobs page | 3 | From brine's own DB, so history outlives the master's job cache |
| Job detail | Job page | 3 / 5 | Re-run / terminate / kill in 5 |
| Highstate | Jobs › Highstate | 3 | Latest state run per minion, one dot per state |
| Events | Events page | 3 | Auto-reconnecting SSE |
| Reactors | Events › Reactors | 3 | Read-only |
| Issues | Issues page | 3 | SaltGUI's detectors (below) plus stale / never-reported minions |
| Options + `/stats` | Settings | 3 | Active config, presence method, salt-api health |
| Command box | Run command | 5 | Adds targeting preview, confirmation, role check, audit |
| Grains / beacons / schedules / mine actions | Minion page actions | 5 | |
| Templates (`saltgui_templates`) | Run command › Templates | 5 | |
| Orchestrations | Run command › Orchestrations | 5 | |
| Search (regex / invert / case), sort, row selection | Tables | 3 | |
| Dark mode (system only) | Light / dark with manual toggle | 3 | |
| Keyboard shortcuts | | Later | |
| MOTD banners | | Later | |
| Popup / new-tab mode | Not needed | — | Every brine view has its own URL |

### SaltGUI Issues detectors to match

Unaccepted keys · minions not connected · jobs running > 60 s · disabled beacons · disabled
schedulers / schedule jobs · failed states in recent state runs · minion/master version mismatch
and known CVEs · `full_return` not enabled.

## brine-only features

- OIDC SSO with role mapping and a server-side permission layer on top of Salt's eauth ACL
- Presence tracking (`presence_events`, with a `manage.status` fallback): online, stale, offline, last seen
- Live vs. cached vs. unknown shown explicitly everywhere
- Grains snapshots with timestamps and history diffs
- Job history kept in brine's database
- Audit log
- Live updates without refresh, and a phone-friendly layout
- Demo mode with no real infrastructure
