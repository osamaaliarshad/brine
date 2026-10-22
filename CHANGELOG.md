# Changelog

## [0.1.0] - 2026-10-22

The first release: a web UI for an existing salt-master and salt-api, covering what SaltGUI does,
plus sign-in, history, an audit log, catch-up runs, and what's installed on each minion.

- **Fleet:** every minion online, stale or offline with last seen, any grains as columns, the
  spread of any grain across the fleet, nodegroups.
- **Minion pages:** grains with when they were collected and their history, jobs, an online and
  offline timeline, and pillar (masked), beacons, schedules and mine asked live.
- **Packages and checks:** what each minion has installed, from its own package manager, plus
  your own checks for anything else (container images, binaries in `/opt`), kept over time. See
  which minions have which version, or don't have it, add any package or check as a column, and
  see each change with the job it was found after, when brine can tell. Compare a minion with a
  golden one, or the whole fleet with it.
- **Jobs:** history kept in brine's database, each minion's latest state run, and a page per job
  with state-by-state results, Run again, and stop or kill.
- **Run:** commands like the salt CLI, showing the exact minions they'll reach before anything
  runs; a per-role allowlist; templates (including SaltGUI's `saltgui_templates`) with fill-in
  fields; shareable links.
- **Catch-up runs:** minions that are offline get a command when they're back, one at a time,
  for up to 7 days, cancellable.
- **Orchestrations:** every orchestration step by step, including ones that take pillar at run
  time; running them records each step's job under the person who ran it.
- **Issues:** what needs a human, most serious first. Mark one as read and it's out of your way
  until it changes; once it's fixed it's gone, and if it comes back it's new.
- **States** (the top file grouped by folder, and the state files, colored as in an editor),
  **Automation** (every schedule and beacon), **Events** (the live event bus and reactors).
- **Keys:** accept, reject and delete, for admins, with a fingerprint check and a typed name.
- **Sign-in and roles:** any OIDC provider (Google, Okta, Microsoft Entra, Keycloak, GitHub via
  Dex); viewer, operator and admin by email pattern; an audit log.
- **Light and dark themes,** following the system or your choice.
- **Runs anywhere that can reach salt-api:** one Docker image (amd64 and arm64), SQLite or
  PostgreSQL, tested end to end against Salt 3006, 3007 and 3008.
