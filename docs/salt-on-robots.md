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

Pin it to the release line your master runs (`3006.*` or `3008.*`). Upgrade the master first: a
minion newer than its master isn't guaranteed to work.

```bash
echo 'Package: salt-*
Pin: version 3008.*
Pin-Priority: 1001' | sudo tee /etc/apt/preferences.d/salt-pin-1001
sudo apt update
sudo apt install salt-minion
```

Point it at the master in `/etc/salt/minion.d/master.conf` (`master: salt.example.com`), then
`sudo systemctl enable --now salt-minion`.

## 2. Identity

**Give each robot its ID** rather than letting Salt guess one from the hostname: `id: rover-0042`
in `/etc/salt/minion.d/id.conf`. Pick a scheme that survives reflashing (a serial number, not a
hostname a new image resets) and globs well: `rover-*`, `dock-*`.

**Static grains** for what Salt can't find out itself go in `/etc/salt/grains`, as plain YAML:

```yaml
site: site-a
role: rover
hw_rev: B2
```

Keep them in that one file: the `grains` option in the minion config overrides the file's grains
of the same name, and a `grains:` block in `minion.d` replaces the main config's whole block.
After changing them, `salt 'rover-0042' saltutil.refresh_grains`. brine can show each as a Fleet
column, and you can target them (`G@site:site-a`).

**No grain for the JetPack version.** The package list already has it: `nvidia-l4t-core` comes
with Jetson Linux (`36.4.3-20250107174145` is JetPack 6.2), and `nvidia-jetpack` (`6.2+b77`) is
there wherever the JetPack components were installed. "Which robots run JetPack 6.2?" is a
package question.

## 3. Flaky links

A minion holds two connections to the master, to ports 4505 (jobs) and 4506 (returns). A
cellular network or NAT can drop an idle connection without telling either side, and the minion
then waits for jobs that never arrive. These settings, in `/etc/salt/minion.d/links.conf`, make
it notice and reconnect:

```yaml
tcp_keepalive: True
tcp_keepalive_idle: 10        # seconds idle before the first keepalive probe
tcp_keepalive_cnt: 3          # unanswered probes before the connection counts as dead
tcp_keepalive_intvl: 10       # seconds between probes
master_alive_interval: 60     # seconds between checks that the master connection is up
ping_interval: 5              # minutes between pings to the master
auth_timeout: 15              # seconds to wait for each authentication attempt
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
them together within a release line, followed by a reboot, advises against mixing packages from
different releases, and doesn't support apt across major releases (35.x to 36.x). A routine
`pkg.uptodate` or `apt upgrade` in a state could start that in the field, on battery, over a link
that drops. Hold them:

```jinja
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

`pkg.held` (Salt 3005 and later) takes exact names, not patterns like `nvidia-l4t-*`, hence the
list from `pkg.list_pkgs`. Apply it to the Jetsons (by grain in your top file). Don't add
`replace: True`: on apt it would lift every other hold.

Upgrade JetPack on purpose instead: lift the hold on one robot (`pkg.unheld`, or
`apt-mark unhold`), follow NVIDIA's apt steps for the point or minor release, reboot, check it,
then the rest, and hold again. Major releases go through NVIDIA's image-based OTA update (or a
reflash), or your own A/B updater, not `state.apply`.

## 5. Where brine helps

- **Presence:** online, stale or offline for every robot, when each was last seen, and an
  online/offline timeline per robot.
- **Catch-up runs:** tick "Also run it on the offline minions when they're back" on the Run page,
  and robots that are offline get the command when they reconnect (for up to 7 days, by
  default).
- **Packages and checks:** brine reads every robot's packages (so `nvidia-l4t-core` and
  `nvidia-jetpack` too) every 6 hours by default, after people's jobs, and when a robot comes
  back. Checks
  cover what apt doesn't know, such as the release the board reports:
  `jetson: "head -1 /etc/nv_tegra_release 2>/dev/null || true"`, which prints a line like
  `# R36 (release), REVISION: 4.3, ...`. Fleet › Grains & packages shows which robots run which
  version; Run on these opens the Run page with just them.
- **A golden robot:** set one up the way they should all be, then on its Packages tab, "How the
  fleet differs from" it lists every other robot's different, missing and extra packages and
  checks. Compare opens one robot's differences side by side.
- **Nothing to maintain on the robots:** brine only talks to salt-api. The robots run the stock
  minion, and brine changes nothing on them or on the master.

## 6. Security

- **The master is root on every robot.** Whoever can run jobs on it, through the CLI or
  salt-api, can do anything on every robot. Guard it like that.
- **Only the master listens,** on 4505 and 4506; robots need no open ports. Allow those two only
  from the robots' networks (their VPN or private APN), never the whole internet.
- **Accept keys by fingerprint.** Leave `auto_accept` off, and don't use `autosign_file` for
  robots: it trusts a minion by its ID alone. Accept on brine's Keys page after checking the
  fingerprint it shows against the robot's own (`sudo salt-call --local key.finger`). Setting
  `master_finger` on each robot (from `salt-key -F master`) makes it refuse any other master.
- **salt-api reachable only by brine,** over TLS, with brine's account limited to
  [its ACL](permissions-and-salt-acl.md). Salt matches function names in an ACL as a prefix, so
  end them with `$` (`cmd.run$`) to allow just that one. Checks let that account run commands;
  leave them out to keep it read-only.

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
