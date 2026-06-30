#!/bin/sh
# Entrypoint for the mock OpenWrt device.
# - seeds the persisted UCI/DHCP state on first boot (idempotent)
# - (re)applies SSH credentials from env
# - starts the Prometheus node-exporter (monitoring plane) in the background
# - runs sshd in the foreground (configuration plane)
set -eu

STATE_DIR="${MOCK_STATE_DIR:-/var/lib/mockdev}"
SSH_USER="${MOCK_SSH_USER:-root}"
SSH_PASSWORD="${MOCK_SSH_PASSWORD:-openwrt}"

mkdir -p "$STATE_DIR"

# Seed state only if the volume is empty (first boot). Re-seed by deleting the files.
if [ ! -f "$STATE_DIR/uci.conf" ]; then
    cp /usr/share/mockdev-seed/uci.conf "$STATE_DIR/uci.conf"
fi
if [ ! -f "$STATE_DIR/dhcp.leases" ]; then
    cp /usr/share/mockdev-seed/dhcp.leases "$STATE_DIR/dhcp.leases"
fi
# ubus/uci read the leases from /tmp by convention; expose a stable symlink.
ln -sf "$STATE_DIR/dhcp.leases" /tmp/dhcp.leases

# Ensure the login user exists with the requested password.
if [ "$SSH_USER" = "root" ]; then
    echo "root:${SSH_PASSWORD}" | chpasswd
else
    if ! id "$SSH_USER" >/dev/null 2>&1; then
        adduser -D -s /bin/sh "$SSH_USER"
    fi
    echo "${SSH_USER}:${SSH_PASSWORD}" | chpasswd
fi

# The fake uci writes state; make sure the login user owns the state dir.
chown -R "$SSH_USER" "$STATE_DIR"

# Optional public-key auth.
if [ -n "${MOCK_SSH_PUBKEY:-}" ]; then
    home_dir="$(getent passwd "$SSH_USER" | cut -d: -f6)"
    mkdir -p "$home_dir/.ssh"
    echo "$MOCK_SSH_PUBKEY" > "$home_dir/.ssh/authorized_keys"
    chmod 700 "$home_dir/.ssh"
    chmod 600 "$home_dir/.ssh/authorized_keys"
    chown -R "$SSH_USER" "$home_dir/.ssh"
fi

# Allow password + root login for the mock.
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Record a fresh boot time so the exporter reports a sane uptime, then start the
# monitoring plane (Prometheus node-exporter on :9100) in the background.
date +%s > "$STATE_DIR/boot_time"
chown "$SSH_USER" "$STATE_DIR/boot_time"
node-exporter &

exec /usr/sbin/sshd -D -e
