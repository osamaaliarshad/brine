# Packages and checks: design

Approved 2026-10-21. Goal: a month after installing a versioned .deb on a group of minions, see at
a glance which minions have it, which don't, and which versions, without creating grains. The
minion stays the source of truth; brine keeps what each minion said, and when.

## Sources

- **Packages** (always on): `pkg.list_pkgs`, the minion's own package manager (dpkg, rpm, apk,
  Windows). Covers anything installed as a package, however it got there: Salt, apt by hand,
  `dpkg -i`, or before Salt existed.
- **Checks** (optional, `inventory.checks` in brine's config): a name and a read-only command run
  with `cmd.run_all`, for software the package manager doesn't know (container images, binaries
  in /opt). Output lines `name=value` become one entry each; any other output is one value.
  Defined only in config, never from the UI.

Not real Salt grains: no module to deploy, `grains.items` on the CLI stays the same size, and
nothing goes stale between grains refreshes.

## Collection

brine asks connected minions:

- every `inventory.refresh_hours` (default 6), fleet-wide; the schedule survives restarts;
- when a minion starts or comes back;
- about a minute after a job a person ran returns from a minion (debounced; brine's own calls
  don't count), so a change can be credited to that job;
- on **Ask now** (anyone signed in; fleet-wide at most once a minute).

Answers arrive as job returns on the event bus, like grains. A `pkg.list_pkgs` someone runs from
the CLI or the Run page (no extra arguments) counts too. An answer older than what's stored is
ignored.

## Storage

- **Current entries:** (minion, source, name) → value, and when that value was first seen.
- **Reads:** (minion, source) → when it last answered, ok or the error.
- **Changes:** minion, source, name, old → new, at; the job and person when the change was first
  seen in the re-read after that job, otherwise the window between the two reads.

The first read records everything as "already there when brine first looked". **Unknown** (never
answered, or the last read failed with nothing before it) is never shown as **not installed**
(answered without it). Offline minions keep their last answer, shown with its time. A failed read
keeps the last good values. Checks are capped at 500 entries / 64 KB, marked truncated beyond.
Changes follow `retention.history_days`; current entries live as long as the minion.

## UI

- **Fleet › Grains & packages:** one explorer for grains, packages and checks, each labelled with
  its kind. A package shows its version spread, then **Not installed** and **Unknown** rows,
  **Run on these** (the Run page with exactly those minions, previewed, not run), **Add as
  column** (version, `—` not installed, `?` unknown), and **Changes** across the fleet.
- **A grain and a package for the same thing stay side by side,** each labelled; columns next to
  each other show disagreement. No linking.
- **Minion › Packages:** every package with its version and since when, searchable, plus each
  check; read time and **Ask now**.
- **Minion › History** (was Grains history): grains, package and check changes in one timeline.
- **Settings:** cadence, checks and their commands, last fleet read; any missing ACL entry with
  the exact lines to paste. **Issues:** one entry when packages can't be read at all.

## Added after comparing with Uyuni

- **Compare with a golden robot** (from Uyuni's package profiles): pick a reference robot; see
  how every robot's packages and checks differ from it (different, missing, extra), and drill
  into one robot's differences. On the minion's Packages tab.
- **Guide: Salt on robots** (`docs/salt-on-robots.md`): arm64 minions on Jetson, settings for
  flaky links, holding JetPack/L4T packages, and how brine's features apply.
- Then a hands-on test pass with the user over every feature in the demo, for reliability and
  intuitiveness, before tagging 0.1.0.

## Salt account

`pkg.list_pkgs` joins the read-only ACL. Each check needs `cmd.run_all` limited to its exact
command with Salt's argument matching (`args: ['^<escaped command>$']`); brine prints the lines.
The permissions doc says which commands brine runs for itself instead of "never".

## Testing

Unit (parsing, caps, diffs, attribution, unknown vs not installed, late answers), collector
(schedule, start, after jobs, debounce, throttle), API, frontend, and end to end on the demo
fleet across Salt 3006/3007/3008: a demo `rover-agent` .deb (2.3.0 and 2.4.1) installed by a
demo state on some minions plus one check; applying the state from brine is credited to that job.
README screenshots, ACL doc, example config and the 0.1.0 changelog are updated.
