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
- **Grains must be cached** (`minion_data_cache: True`, the default).
- Quick check: `salt-run manage.present` should list your minions.

## Fallback: periodic status checks

Without presence events, brine periodically runs `manage.status` (a `test.ping` behind the scenes)
and records who answered. This works everywhere but costs a job on every minion per check, and
"last seen" is only as precise as the check interval.

brine shows which method is active on the Settings page.

## What brine shows

| State | Meaning |
|---|---|
| **Online** | Seen connected in the most recent presence check |
| **Stale** | Not seen for longer than `fleet.stale_after_minutes` but not yet confirmed gone, or brine has lost contact with salt-api and can't tell |
| **Offline** | Reported lost, or missing from presence checks |
| **Unknown** | Accepted key, but brine has never seen the minion report |

Grains are always shown with the time they were collected ("as of"), because cached grains can
be days old even while the minion is online.
