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

Everything brine shows today needs only these. Paste into the master config and adjust the
account name:

```yaml
external_auth:
  pam:
    brine:
      - '*':
        - test.ping          # reachability checks
        - test.version
        - grains.items       # fleet table, minion pages, grains history
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
      - '@wheel':
        - config.values      # reactors and nodegroups (only those keys leave brine's server)
        - key.finger         # key fingerprints
        - key.list_all       # key states
        - minions.connected  # presence polling (method: connected)
        - file_roots.list_env  # States › Files
        - file_roots.read
      - '@jobs'
```

The demo fleet uses this list plus key management (below):
[demo/master.d/brine-demo.conf](../demo/master.d/brine-demo.conf).

### What brine never asks for

- `pillar.items`: pillar is only read through `pillar.obfuscate`, so secret values never reach
  brine, let alone a browser. (Revealing values, for admins and audited, is planned.)
- Any execution or state function (`cmd.*`, `state.apply`, ...): there's no command box yet.
- `key.accept`, `key.reject`, `key.delete`: they take a glob, so a minion ID with `*` or `?` in
  it could match others. brine uses the `_dict` versions, which match exact IDs.

### Things to know

- `config.values` returns the whole master config to brine's server. brine keeps only
  `reactor` and `nodegroups` and never sends the rest to browsers or stores it.
- `file_roots.read` lets brine read files under your `file_roots` (states, templates). Keep
  secrets in pillar, not in state files.

## 4. Optional: key management

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

## 5. Optional: the Run page (commands)

The Run page runs whatever functions brine's account is allowed, so list exactly the ones your
team should be able to run through brine, for example:

```yaml
      - '*':
        - test.*
        - state.apply
        - service.restart
      - '@runner':
        - manage.*
```

Then decide who in brine may run which of them, under `commands:` in brine's config:

```yaml
commands:
  operator: ["test.*", "state.apply"]   # operators: only these
  admin: ["*"]                          # admins: anything the ACL above allows (the default)
```

Viewers never run commands. Every run shows its exact target first, needs a click to confirm,
and goes in the audit log; minion jobs are recorded under the person who ran them (brine tags
each job with Salt job metadata). If Salt refuses a function, brine says which one to add.
