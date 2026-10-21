# Salt on robots

Notes for running Salt minions on robots: NVIDIA Jetson boards on arm64 Ubuntu, on cellular or
Wi-Fi links that come and go. Checked against Salt 3006 to 3008 and NVIDIA's docs for JetPack 6.2.
Most of it is plain Salt; section 5 is where brine helps.

## 1. Install the minion

JetPack 6 is Jetson Linux 36 on an Ubuntu 22.04 root file system (arm64). The Salt Project
publishes arm64 packages for Ubuntu 22.04 and 24.04 from one apt repository:

```bash
sudo mkdir -m 755 -p /etc/apt/keyrings
curl -fsSL https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public \
  | gpg --dearmor | sudo tee /etc/apt/keyrings/salt-archive-keyring.pgp > /dev/null
curl -fsSL https://github.com/saltstack/salt-install-guide/releases/latest/download/salt.sources \
  | sudo tee /etc/apt/sources.list.d/salt.sources
```

Pin it to the release line your master runs (`3006.*`, `3007.*` or `3008.*`): `salt --version`
on the master says which, and brine's Fleet page shows what each minion runs. When you upgrade
later, do the master first: a minion newer than its master isn't guaranteed to work.

```bash
echo 'Package: salt-*
Pin: version 3008.*
Pin-Priority: 1001' | sudo tee /etc/apt/preferences.d/salt-pin-1001
```

The package starts the minion as soon as it's installed (and enables it at boot), so give it its
master and ID before installing (pick a scheme first: section 2). Otherwise it starts with the
defaults: a master called `salt`, and an ID guessed from the hostname.

```bash
sudo mkdir -p /etc/salt/minion.d
echo 'master: salt.example.com' | sudo tee /etc/salt/minion.d/master.conf
echo 'id: rover-0042' | sudo tee /etc/salt/minion.d/id.conf
sudo apt update
sudo apt install salt-minion
```

The minion reads its config when it starts: after changing anything in `/etc/salt/minion.d`
later, `sudo systemctl restart salt-minion`.

Then accept its key (section 6 has how) and check it answers. On the master:
`salt 'rover-0042' test.ping`.

## 2. Identity

**Give each robot its own ID** (the `id.conf` above) rather than letting Salt guess one from the
hostname. Pick a scheme that survives reflashing (a serial number, not a hostname a new image
resets) and globs well: `rover-*`, `dock-*`.

**Static grains** for what Salt can't find out itself go in `/etc/salt/grains`, as plain YAML (it
can be written before installing, too):

```yaml
site: site-a
role: rover
hw_rev: B2
```

Keep static grains only in this file. After changing them, run
`salt 'rover-0042' saltutil.refresh_grains` on the master. brine can show each as a Fleet column,
and you can target them (`G@site:site-a`).

**No grain for the JetPack version.** The package list already has it: `nvidia-l4t-core` comes
with Jetson Linux (`36.4.3-20250107174145` is JetPack 6.2), and `nvidia-jetpack` (`6.2+b77`) is
there wherever the JetPack components were installed. "Which robots run JetPack 6.2?" is a
package question.

## 3. Flaky links

A minion holds two connections to the master, to ports 4505 (jobs) and 4506 (returns). A
cellular network or NAT can drop an idle connection without telling either side, and the minion
then waits for jobs that never arrive. These settings, in `/etc/salt/minion.d/links.conf`, make
it notice and reconnect. Write the file before installing, like the others, or restart the
minion after:

```yaml
tcp_keepalive: True
tcp_keepalive_idle: 10
tcp_keepalive_cnt: 3
tcp_keepalive_intvl: 10
master_alive_interval: 60   # seconds
ping_interval: 5            # minutes
auth_timeout: 15            # seconds
```

| Setting | Default | What it does |
|---|---|---|
| `tcp_keepalive_*` | on, idle 300 s, count and interval from the OS | Keepalive probes on the minion's ZeroMQ connections, so a dead link is dropped and reconnected. The values above are the ones [Uyuni](https://uyuni-project.org/uyuni-docs/en/uyuni/specialized-guides/salt/salt-connectivity.html) recommends. |
| `master_alive_interval` | 0 (off) | Checks the minion still has a connection to the master's port 4505. If not, it reconnects, looking up the master's address again (so a DNS change is picked up too). |
| `ping_interval` | 0 (off) | Pings the master every so many minutes; Salt calls it a mitigation against minion disconnects. |
| `auth_timeout` | 5 | Seconds per authentication attempt. Salt's docs suggest raising it on high-latency links. |
| `recon_default`, `recon_max`, `recon_randomize` | 1000 ms, 10000 ms, on | How long ZeroMQ waits before reconnecting: it starts at `recon_default`, doubles up to `recon_max`, and is spread randomly so a fleet doesn't reconnect all at once. The defaults are fine. |
| `retry_dns` | 30 | Seconds between tries when the master's name doesn't resolve. 0 makes the minion stop instead. |

A job that reaches a robot just before its link drops may never report back: brine's job page
lists the minions that didn't answer.

## 4. Don't let apt upgrade JetPack

The `nvidia-l4t-*` packages are the board's kernel, drivers and bootloader update. NVIDIA upgrades
them together within a release line, followed by a reboot. It advises against mixing packages
from different releases, and doesn't support apt across major releases (35.x to 36.x). A
routine `pkg.uptodate` or `apt upgrade` in a state could start that in the field, on battery,
over a link that drops. Hold them:

```sls
{# jetson/hold.sls: hold every installed nvidia-l4t-* package at its version. #}
{% set l4t = salt['pkg.list_pkgs']() | select('match', 'nvidia-l4t-') | list %}
{% if l4t %}
hold-l4t-packages:
  pkg.held:
    - pkgs:
{%- for name in l4t %}
      - {{ name }}
{%- endfor %}
{% endif %}
```

`pkg.held` takes exact names, not patterns like `nvidia-l4t-*`, hence the list from
`pkg.list_pkgs`. Don't add `replace: True`: on apt it would lift every other hold. Apply it to
the Jetsons by grain, in your top file:

```yaml
base:
  'role:rover':
    - match: grain
    - jetson.hold
```

Upgrade JetPack on purpose instead, one robot first:

1. Lift the hold on it: `pkg.unhold`, or `apt-mark unhold` on the robot. If a schedule runs a
   highstate that includes the hold state, pause it for that robot, or it holds the packages
   again in the middle of the upgrade.
2. Follow NVIDIA's apt steps for the point or minor release, then reboot.
3. Check the robot, then do the rest the same way.
4. Apply the hold state again.

Major releases go through NVIDIA's image-based OTA update (or a reflash), or your own A/B
updater, not `state.apply`.

## 5. Where brine helps

- **Presence:** online, stale or offline for every robot, when each was last seen, and an
  online/offline timeline per robot.
- **Catch-up runs:** tick "Also run it on the offline minions when they're back" on the Run page,
  and robots that are offline get the command when they reconnect (for up to 7 days, by
  default).
- **Packages and checks:** brine reads every robot's packages (so `nvidia-l4t-core` and
  `nvidia-jetpack` too) every 6 hours by default, after people's jobs, and when a robot comes
  back. Checks cover what apt doesn't know, such as the release the board reports. A check goes
  under `inventory.checks` in brine's config, like
  `jetson: "head -1 /etc/nv_tegra_release 2>/dev/null || true"`, which prints a line like
  `# R36 (release), REVISION: 4.3, ...`. Checks need more from brine's Salt account than reading
  packages does (section 6). Fleet › Grains & packages shows which robots run which version;
  Run on these opens the Run page with just them.
- **A golden robot:** set one up the way they should all be, then open its Packages tab. **How
  the fleet differs from rover-01** counts the packages and checks that are different, missing or
  extra on every other robot. **Compare with…** shows one robot's differences side by side.
- **Nothing to maintain on the robots:** brine only talks to salt-api. The robots run the stock
  minion, and brine installs nothing on them or on the master.

## 6. Security

- **The master is root on every robot.** Whoever can run jobs on it, through the CLI or
  salt-api, can do anything on every robot. Guard it like that.
- **Only the master listens,** on 4505 and 4506; robots need no open ports. Allow those two only
  from the robots' networks (their VPN or private APN), never the whole internet.
- **Accept keys by fingerprint.** Leave `auto_accept` off, and don't use `autosign_file` for
  robots: it trusts a minion by its ID alone. Accept on brine's Keys page after checking the
  fingerprint it shows against the robot's own (`sudo salt-call --local key.finger`). Setting
  `master_finger` on each robot (from `salt-key -F master`, on the master) makes it refuse any
  other master.
- **salt-api reachable only by brine,** over TLS, with brine's account limited to
  [its ACL](permissions-and-salt-acl.md). Salt matches function names in an ACL as a prefix, so
  end them with `$` (`cmd.run$`) to allow just that one. Checks let that account run any command
  ([section 4 there](permissions-and-salt-acl.md#4-optional-checks)); leave them out to keep it
  read-only.

## Sources

- Salt: [Install on Debian and Ubuntu](https://docs.saltproject.io/salt/install-guide/en/latest/topics/install-by-operating-system/linux-deb.html),
  [supported operating systems](https://docs.saltproject.io/salt/install-guide/en/latest/topics/salt-supported-operating-systems.html),
  [upgrading](https://docs.saltproject.io/salt/install-guide/en/latest/topics/upgrade.html),
  [minion configuration](https://docs.saltproject.io/en/latest/ref/configuration/minion.html),
  [grains](https://docs.saltproject.io/en/latest/topics/grains/index.html),
  [firewall](https://docs.saltproject.io/en/latest/topics/tutorials/firewall.html),
  [hardening](https://docs.saltproject.io/en/latest/topics/hardening.html).
- Uyuni: [Salt connectivity](https://uyuni-project.org/uyuni-docs/en/uyuni/specialized-guides/salt/salt-connectivity.html).
- NVIDIA: [JetPack 6.2](https://developer.nvidia.com/embedded/jetpack-sdk-62),
  [software packages and the update mechanism](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/SoftwarePackagesAndTheUpdateMechanism.html).
