#!/bin/sh
# Entrypoint for the mock TP-Link JetStream switch.
# - seeds the persisted running/startup config on first boot (idempotent)
# - sets the admin user's login shell to the fake CLI
# - (re)applies SSH credentials from env
# - runs sshd in the foreground
set -eu

STATE_DIR="${MOCK_STATE_DIR:-/var/lib/mockdev}"
SSH_USER="${MOCK_SSH_USER:-admin}"
SSH_PASSWORD="${MOCK_SSH_PASSWORD:-admin}"

mkdir -p "$STATE_DIR"

if [ ! -f "$STATE_DIR/running.json" ]; then
    cp /usr/share/mockdev-seed/running.json "$STATE_DIR/running.json"
fi
if [ ! -f "$STATE_DIR/startup.json" ]; then
    cp "$STATE_DIR/running.json" "$STATE_DIR/startup.json"
fi

# Create the admin user with the CLI as its login shell.
if ! id "$SSH_USER" >/dev/null 2>&1; then
    adduser -D -s /usr/bin/jetstream-cli "$SSH_USER"
else
    sed -i "s#^\(${SSH_USER}:.*:\)[^:]*\$#\1/usr/bin/jetstream-cli#" /etc/passwd
fi
echo "${SSH_USER}:${SSH_PASSWORD}" | chpasswd

# The CLI runs as $SSH_USER and must be able to persist state.
chown -R "$SSH_USER" "$STATE_DIR"

if [ -n "${MOCK_SSH_PUBKEY:-}" ]; then
    home_dir="$(getent passwd "$SSH_USER" | cut -d: -f6)"
    mkdir -p "$home_dir/.ssh"
    echo "$MOCK_SSH_PUBKEY" > "$home_dir/.ssh/authorized_keys"
    chmod 700 "$home_dir/.ssh"
    chmod 600 "$home_dir/.ssh/authorized_keys"
    chown -R "$SSH_USER" "$home_dir/.ssh"
fi

# Force the CLI for both interactive shells and `ssh host "command"` exec sessions.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
if ! grep -q "ForceCommand /usr/bin/jetstream-cli" /etc/ssh/sshd_config; then
    cat >> /etc/ssh/sshd_config <<EOF

Match User ${SSH_USER}
    ForceCommand /usr/bin/jetstream-cli
EOF
fi

exec /usr/sbin/sshd -D -e
