#!/bin/sh
# Demo salt-master + salt-api in one container.
set -eu

# The service account brine logs in with (PAM eauth). Demo only: the password comes from the
# compose file and the account can't log in to a shell.
if ! id brine >/dev/null 2>&1; then
  useradd --no-create-home --shell /usr/sbin/nologin brine
fi
echo "brine:${SALT_API_PASSWORD:?SALT_API_PASSWORD must be set}" | chpasswd

# Salt ignores autosign files that others can write to, and bind mounts from Windows hosts
# always look world-writable, so install a private copy.
install -m 0644 -o root -g root /demo/autosign.conf /etc/salt/autosign.conf

# salt-api runs in the background; salt-master stays in the foreground so the container
# exits (and compose restarts it) if the master dies.
salt-api -d -l info --log-file=/var/log/salt/api
exec salt-master -l info
