# Permissions: brine's Salt service account

brine talks to salt-api with **one dedicated account**. People never use Salt credentials; their
access is decided by brine's own roles ([sign-in](oidc-providers.md)). This page lists exactly
what that account needs on the master, so you can grant no more than that.

Two layers decide every write: Salt's ACL (what the account may do at all) and brine's roles
(which people may ask it to). brine reads the account's ACL when it logs in and only offers what
Salt will allow, saying what's missing otherwise.

## 1. Create the account

Any eauth backend works; PAM with a local user is the simplest:

```bash
sudo useradd --no-create-home --shell /usr/sbin/nologin brine
sudo passwd brine
```

On Salt 3006+ the master runs as the `salt` user and PAM needs `/etc/shadow`: on Debian/Ubuntu,
`sudo usermod -aG shadow salt`. (Or use `file`, `ldap`, ... eauth instead.)

## 2. Enable the salt-api clients brine uses

```yaml
# /etc/salt/master.d/salt-api.conf
netapi_enable_clients:
  - local
  - local_async
  - runner
  - wheel
```

## 3. The read-only ACL

Everything brine shows needs only these, apart from checks (section 4). Paste into the master
config and adjust the account name:

```yaml
external_auth:
  pam:
    brine:
      - '*':
        - test.ping          # reachability checks
        - test.version
        - grains.items       # fleet table, minion pages, grains history
        - pkg.list_pkgs      # installed packages: Grains & packages, minion › Packages
        - pillar.obfuscate   # minion › Pillar (values masked; never pillar.items)
        - beacons.list       # minion › Beacons, Automation › Beacons
        - schedule.list      # minion › Schedules, Automation › Schedules
        - mine.valid         # minion › Mine
        - state.show_top     # States › Top file
        - saltutil.running
      - '@runner':
        - jobs.active        # jobs still running
        - jobs.list_job      # backfilling job results from the job cache
        - jobs.list_jobs
        - jobs.lookup_jid
        - manage.alived
        - manage.status      # presence polling (method: ping)
        - manage.versions
        - cache.grains       # cached grains, nodegroup membership, presence diagnostics
        - state.orchestrate_show_sls  # Orchestrations: each one's steps (renders, runs nothing)
      - '@wheel':
        - config.values      # reactors, nodegroups, saltgui_templates (only these are used)
        - key.finger         # key fingerprints
        - key.list_all       # key states
        - minions.connected  # presence polling (method: connected)
        - file_roots.list_env  # States › Files
        - file_roots.read
      - '@jobs'
```

The demo fleet uses this list plus a check, key management and a command box (below):
[demo/master.d/brine-demo.conf](../demo/master.d/brine-demo.conf).

### What brine never asks for

- `pillar.items`: brine's own Pillar tab reads pillar through `pillar.obfuscate`, so it never
  fetches secret values itself. If someone runs a pillar function (from the salt CLI or the Run
  page), its output reaches brine's job history; only admins see it there.
- Commands of its own, other than the checks you configure (section 4), which it runs exactly
  as written. Any other command runs only when a person runs it from the Run page (section 6).
- `key.accept`, `key.reject`, `key.delete`: they take a glob, so a minion ID with `*` or `?` in
  it could match others. brine uses the `_dict` versions, which match exact IDs.

### Things to know

- `config.values` returns the whole master config to brine's server. brine uses only
  `reactor`, `nodegroups` and `saltgui_templates`, and never sends the rest to browsers or
  stores it.
- `file_roots.read` lets brine read files under your `file_roots` (states, templates). Keep
  secrets in pillar, not in state files.

## 4. Optional: checks

Checks read what the package manager doesn't know about, such as container images or a binary
copied into `/opt` (`inventory.checks` in brine's config). brine runs each check with
`cmd.run_all`, so each one needs its own rule, pinned to its exact command.

You don't have to write the rules: **Settings › Packages and checks** prints the exact lines
under "Salt permissions brine needs", escaped and quoted. For a check
`jetson: "head -1 /etc/nv_tegra_release 2>/dev/null || true"` it prints:

```yaml
      - '*':
        - pkg.list_pkgs
        - cmd.run_all:
            args:
              - '^head\ \-1\ /etc/nv_tegra_release\ 2>/dev/null\ \|\|\ true$'
```

Paste them under brine's account (`pkg.list_pkgs` listed twice does no harm). Each check gets a
rule of its own: two patterns in one `args` list would be the first and second argument of a
single call. Until its rule is there, brine says it can't read that check, in Settings and on the
Issues page.

**Checks let brine's account run commands.** Salt pins the command, but it can't pin the call's
other options (`shell`, `env`, `runas`, `cwd`), and those are enough to run something else. So
in practice, an account that's allowed checks can run commands on your minions. Leave checks out
to keep brine's account read-only: packages alone need only `pkg.list_pkgs`.

## 5. Optional: key management

Lets admins accept, reject and delete minion keys on the Keys page and minion pages. Add to the
`@wheel` list:

```yaml
      - '@wheel':
        # ...the read-only entries above, then:
        - key.accept_dict
        - key.reject_dict
        - key.delete_dict
```

Leave them out and brine stays read-only for keys: the buttons don't appear, and the Keys page
says which functions are missing. With them, every change still needs:

- the **admin** role in brine;
- a confirmation: the fingerprint for accepting (brine refuses if the key changed since the page
  loaded), the minion's name typed for deleting or for rejecting an accepted key;
- brine checking the key is still where the admin saw it, right before acting.

Each change is in the audit log with who, when, and the key's fingerprint.

## 6. Optional: the Run page (commands)

The Run page runs whatever functions brine's account is allowed, so list exactly the ones your
team should be able to run through brine, for example:

```yaml
      - '*':
        - test.*
        - state.apply
        - service.restart
        - cmd.run$               # just cmd.run, not cmd.run_all or cmd.run_stdout
      - '@runner':
        - manage.*
        - state.orchestrate      # Orchestrations › Run (and Test)
```

Salt reads each name as a regular expression that only has to match the start: `cmd.run` also
allows `cmd.run_all`, `cmd.run_stdout` and the rest, with any command, and so gets round the
pinned rules of your checks. End a name with `$` to allow just that function.

Then decide who in brine may run which of them, under `commands:` in brine's config:

```yaml
commands:
  operator: ["test.*", "state.apply"]   # operators: only these
  admin: ["*"]                          # admins: anything the ACL above allows (the default)
```

Viewers never run commands. Every run shows its exact target first, needs a click to confirm,
and goes in the audit log; minion jobs are recorded under the person who ran them (brine tags
each job with Salt job metadata). If Salt refuses a function, brine says which one to add.
