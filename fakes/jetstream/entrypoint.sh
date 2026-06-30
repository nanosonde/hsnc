#!/bin/sh
# Entrypoint for the mock TP-Link JetStream switch.
# - seeds the persisted running/startup config on first boot (idempotent)
# - sets the admin user's login shell to the fake CLI
# - (re)applies SSH credentials from env
# - configures + starts the SNMPv3 agent (monitoring plane) in the background
# - runs sshd in the foreground (configuration plane)
set -eu

STATE_DIR="${MOCK_STATE_DIR:-/var/lib/mockdev}"
SSH_USER="${MOCK_SSH_USER:-admin}"
SSH_PASSWORD="${MOCK_SSH_PASSWORD:-admin}"
SNMP_USER="${MOCK_SNMP_USER:-hsncmon}"
SNMP_AUTH_KEY="${MOCK_SNMP_AUTH_KEY:-hsncauth123}"
SNMP_PRIV_KEY="${MOCK_SNMP_PRIV_KEY:-hsncpriv123}"
SNMP_MODEL="${MOCK_MODEL:-TL-SG2210P}"

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

# --- Monitoring plane: SNMPv3 agent (never SSH) -----------------------------
# sysName mirrors the switch hostname; sysDescr mirrors the CLI device model so
# the config and monitoring planes stay coherent. The FDB (MAC table) subtree is
# delegated to the fake `pass` backend.
SNMP_SYSNAME="$(python3 -c "import json;print(json.load(open('$STATE_DIR/running.json')).get('hostname','Switch'))" 2>/dev/null || echo Switch)"
cat > /etc/snmp/snmpd.conf <<EOF
rouser ${SNMP_USER} priv
sysDescr ${SNMP_MODEL}
sysName ${SNMP_SYSNAME}
sysServices 2
pass .1.3.6.1.2.1.17.4.3.1.2 /usr/bin/fdb-pass
EOF

# Create the SNMPv3 USM user once; snmpd consumes the createUser line on start
# and persists the resulting key material in this file.
mkdir -p /var/lib/net-snmp
if ! grep -qs "\"${SNMP_USER}\"" /var/lib/net-snmp/snmpd.conf 2>/dev/null \
    && ! grep -qs "createUser ${SNMP_USER} " /var/lib/net-snmp/snmpd.conf 2>/dev/null; then
    echo "createUser ${SNMP_USER} SHA \"${SNMP_AUTH_KEY}\" AES \"${SNMP_PRIV_KEY}\"" \
        >> /var/lib/net-snmp/snmpd.conf
fi

# Background the agent (the listen address is given only here to avoid a double
# bind); sshd then runs in the foreground as the container's main process.
snmpd -Lo -f udp:161 &

exec /usr/sbin/sshd -D -e
