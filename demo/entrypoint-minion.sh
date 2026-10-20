#!/bin/sh
# Demo salt-minion. Identity and custom grains come from environment variables so one image
# can play every member of the fleet.
set -eu

mkdir -p /etc/salt/minion.d
cat > /etc/salt/minion.d/demo.conf <<EOF
id: ${MINION_ID:?MINION_ID must be set}
master: ${SALT_MASTER:-salt-master}
grains:
  site: ${SITE:-unknown}
  role: ${ROLE:-robot}
  app_version: "${APP_VERSION:-0.0.0}"
  firmware_version: "${FIRMWARE_VERSION:-0.0.0}"
  # Containers report the host's hardware; pin it so demo data (and README screenshots)
  # look the same on every machine and say nothing about the one running them.
  cpu_model: Demo CPU
  num_cpus: 4
  mem_total: 4096
  disks: [vda]
  kernelrelease: 6.1.0-demo

# Something for brine's per-minion Mine, Schedules and Beacons views (and the event stream).
mine_functions:
  network.ip_addrs: []
schedule:
  refresh-grains:
    function: saltutil.refresh_grains
    minutes: 30
beacons:
  load:
    - averages:
        1m: [0.0, 2.0]
    - interval: 60
EOF

exec salt-minion -l info
