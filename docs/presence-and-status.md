# Presence and minion status

brine shows each minion as **online**, **stale**, or **offline**, with a "last seen" time. This
page explains where that comes from and what your master needs.

## Preferred: presence events

Add this to the master config and restart the master:

```yaml
presence_events: True
# loop_interval: 60   # how often presence is checked (seconds); default 60
```

Every `loop_interval` seconds the master fires:

- `salt/presence/present` with `{"present": [...]}`, every minion currently connected.
- `salt/presence/change` with `{"new": [...], "lost": [...]}`, but only when that set changes.

brine listens for these on salt-api's event stream. In the demo stack (`loop_interval: 15`), a
stopped minion is reported lost after about 11 s and back about 14 s after it restarts.

### How the master decides who is "present"

The master doesn't ping anyone for this. It reads its own open TCP connections on the publish
port (4505) and matches each remote address against the **`ipv4` / `ipv6` grains it has cached**
for every minion. Consequences:

- **Minions need populated IP grains.** Salt gets these from the `ip` command (iproute2). A
  minion without it, such as a slim container image, reports empty `ipv4` and is never
  "present", even though it answers `test.ping`. Check with `salt-run cache.grains tgt=<id>`.
- **NAT or proxies between minions and master break it**, because the address the master sees
  isn't one the minion reports. Use the fallback below for those setups.
- **Grains must be cached** (`minion_data_cache: True`, the default). The cache lives in
  `/var/cache/salt/master`; if it's wiped (e.g. a master container without a volume), connected
  minions stay invisible until they restart or refresh their pillar.
- Quick check: `salt-run manage.present` should list your minions.

**brine watches for this.** Whenever it reads the master's cache (on connect and with each
grains refresh) it notes accepted minions with no cached IP address. Those minions are shown as
*stale* rather than *offline* (being absent from a presence check proves nothing for them), and
the Issues page explains why and how to fix it. The warning clears when the minion restarts.

## Fallbacks: polling

Without presence events, brine polls every `presence.poll_seconds` (default 60):

- **`connected`** (default fallback): `wheel minions.connected`. Same TCP-based detection as
  presence events, so same requirements, but it works without `presence_events: True`. Cheap: no
  jobs on minions.
- **`ping`**: `runner manage.status`, which pings every minion. Works through NAT, but costs a
  job on every minion per check.

```yaml
presence:
  method: auto        # auto | events | connected | ping
  poll_seconds: 60
```

`auto` uses presence events whenever the master sends them, and polls `minions.connected`
otherwise (including at startup, before the first event arrives). `/api/status` and the Settings
page show which method provided the latest observation.

## What brine shows

A status is only *observed* while brine's latest presence observation is fresh, meaning newer
than `fleet.stale_after_minutes` (default 15). After that, brine says what it last knew.

| State | Meaning |
|---|---|
| **Online** | Connected in the latest presence observation, which is fresh |
| **Offline** | Missing from the latest presence observation, which is fresh. "Last seen" says when brine last had evidence it was alive |
| **Stale** | No fresh observation (salt-api unreachable, master down, presence not working). Shows the last known state and "last seen" |
| **Unknown** | No fresh observation, and brine has never seen this minion at all |

"Last seen" moves forward whenever brine gets evidence a minion is alive: present in a
presence observation, a job return, or a minion start event.

Grains are always shown with the time they were collected ("as of"), because cached grains can
be days old even while the minion is online.
