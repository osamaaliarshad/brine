# Coming from SaltGUI

brine covers what [SaltGUI](https://github.com/erwindon/SaltGUI) does and adds its own features
on top. This maps each SaltGUI page to where it lives in brine. Inventory taken from SaltGUI
`master` @ `c76b1fd` (v1.35.0-SNAPSHOT, October 2026).

SaltGUI is MIT licensed (© 2016–2026 Oliver Dunk, Martijn Jacobs, Erwin Dondorp). brine uses it
as a reference for salt-api calls and contains none of its code.

## The big difference

SaltGUI runs in the browser and talks to salt-api directly, with each person's own Salt eauth
login. brine has a backend: people sign in with your identity provider, the backend talks to
salt-api with one least-privilege service account, records what happens in its own database, and
decides who may do what with its own roles. That's what makes job history, presence, the audit
log and catch-up runs possible.

Your `saltgui_templates` keep working: brine reads them from the master config as they are.

## Page by page

| SaltGUI | brine | Notes |
|---|---|---|
| Login (eauth user and password) | OIDC sign-in | People never see Salt credentials |
| `saltgui_pages` (menus per user) | Roles: viewer, operator, admin | Enforced by the server, not just hidden in the menu |
| Minions | Fleet | Online / stale / offline with last seen, your choice of grain or package columns |
| Grains (+ `saltgui_preview_grains`) | Fleet columns, Fleet › Grains & packages | Each grain's spread across the fleet; add it as a column in one click |
| Grains of one minion | Minion › Grains | When they were collected, and their history as diffs |
| Pillars (masked) | Minion › Pillar | Values masked; showing them isn't built yet |
| Mine | Minion › Mine | |
| Beacons, Schedules | Minion tabs, plus Automation for the whole fleet | Read-only for now; enable / disable isn't built yet |
| Nodegroups | Fleet › Nodegroups | Members from the master's cache, so offline members count |
| Keys | Keys (and each minion page) | Accept / reject / delete: admins, fingerprint check, typed name, audited |
| Jobs | Jobs | History kept in brine's database, longer than the master's job cache |
| Job | Job | Run again; stop or kill it on minions still running it |
| Highstate | Jobs › State runs | Each minion's latest state run, one square per state |
| Events | Events | Reconnects by itself; a Reactors tab shows the master's reactor config |
| Issues | Issues | Plus stale and never-seen minions, and minions presence can't see; each person can mark them as read until they change |
| Options, `/stats` | Settings | |
| Command box | Run | Shows the exact minions before anything runs; per-role allowlist; audited |
| Templates (`saltgui_templates`) | Run › Templates | Plus `templates:` in brine's config, with fill-in fields |
| Orchestrations | Orchestrations | Steps in run order; ones that take pillar at run time ask for it |
| Search, sort | Every table | |
| Row selection | Not built yet | Use a list target on the Run page |
| Keyboard shortcuts, MOTD | Not built yet | |
| Popup / new-tab mode | Not needed | Every view has its own URL |

## Only in brine

- Single sign-on with roles, checked on every request
- Presence: online, stale, offline and last seen, using `presence_events` with a polling fallback
- What's live and what's cached, said everywhere
- Grains history with timestamps
- Job history that outlives the master's job cache, with each job under the person who ran it
- An audit log
- Catch-up runs: offline minions get a command when they're back
- Packages and checks: what's installed on each minion, over time, as columns and in an explorer,
  with each change shown next to the job it was found after; compare minions with a golden one
- Live updates without refreshing, and a layout that works on a phone
