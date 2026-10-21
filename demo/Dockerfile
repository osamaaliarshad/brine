# One image for the whole demo fleet: salt-master, salt-api and salt-minion, installed from the
# official Salt Project packages (the same "onedir" builds real fleets run).
FROM debian:bookworm-slim

ARG SALT_VERSION=3006

RUN set -eux; \
    apt-get update; \
    # iproute2: Salt's ipv4/ipv6 grains come from `ip addr`, and presence detection matches
    # minions by those addresses.
    apt-get install -y --no-install-recommends ca-certificates curl gnupg iproute2 procps; \
    mkdir -m 755 -p /etc/apt/keyrings; \
    curl -fsSL https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public \
      | gpg --dearmor -o /etc/apt/keyrings/salt-archive-keyring.pgp; \
    curl -fsSL https://github.com/saltstack/salt-install-guide/releases/latest/download/salt.sources \
      -o /etc/apt/sources.list.d/salt.sources; \
    printf 'Package: salt-*\nPin: version %s.*\nPin-Priority: 1001\n' "$SALT_VERSION" \
      > /etc/apt/preferences.d/salt-pin-1001; \
    apt-get update; \
    apt-get install -y --no-install-recommends salt-master salt-minion salt-api; \
    # The master runs as the unprivileged `salt` user; PAM eauth needs it to read /etc/shadow.
    usermod -aG shadow salt; \
    apt-get purge -y gnupg; apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*; \
    salt-call --version

# A tiny versioned package for the Packages demo: rover-agent 2.3.0 and 2.4.1. The master serves
# them from their own saltenv, debs (demo/states/agent.sls installs one), and some minions have
# one installed before Salt starts, like software that was there first.
RUN set -eux; \
    mkdir -p /srv/debs; \
    for v in 2.3.0 2.4.1; do \
      d="/tmp/rover-agent_$v"; \
      mkdir -p "$d/DEBIAN" "$d/opt/rover-agent"; \
      printf 'Package: rover-agent\nVersion: %s\nArchitecture: all\nMaintainer: brine demo <demo@example.com>\nDescription: brine demo agent\n' "$v" \
        > "$d/DEBIAN/control"; \
      echo "$v" > "$d/opt/rover-agent/VERSION"; \
      dpkg-deb --build --root-owner-group "$d" "/srv/debs/rover-agent_${v}_all.deb"; \
      rm -rf "$d"; \
    done

COPY --chmod=0755 entrypoint-master.sh entrypoint-minion.sh /usr/local/bin/
