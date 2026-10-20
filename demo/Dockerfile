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

COPY --chmod=0755 entrypoint-master.sh entrypoint-minion.sh /usr/local/bin/
