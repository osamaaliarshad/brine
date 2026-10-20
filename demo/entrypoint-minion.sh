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
EOF

exec salt-minion -l info
