#!/usr/bin/env bash
# Build, start, and drive both device mocks across BOTH planes, then tear down:
#   * configuration plane over real SSH (paramiko)
#   * monitoring plane over Prometheus (OpenWrt) and SNMPv3 (JetStream)
# Requires: docker + docker compose, and `pip install paramiko`.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE=("docker" "compose" "-f" "$HERE/docker-compose.yml")

cleanup() {
    echo "--- tearing down ---"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "--- building & starting mocks ---"
"${COMPOSE[@]}" up -d --build

echo "--- waiting for sshd ---"
python3 - <<'PY'
import socket
import sys
import time

for port in (2201, 2202, 9100):
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                break
        except OSError:
            time.sleep(1)
    else:
        sys.exit(f"timeout waiting for port {port}")
print("ssh + metrics ports are open")
PY

echo "--- driving mocks (paramiko) ---"
python3 - <<'PY'
import sys
import time

import paramiko


def connect(port, user, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    last = None
    for _ in range(20):
        try:
            client.connect(
                "127.0.0.1", port=port, username=user, password=password,
                look_for_keys=False, allow_agent=False, timeout=5,
            )
            return client
        except Exception as exc:  # noqa: BLE001 - retry until sshd is ready
            last = exc
            time.sleep(1)
    raise SystemExit(f"could not connect to port {port}: {last}")


def run(client, command):
    _stdin, stdout, _stderr = client.exec_command(command)
    return stdout.read().decode()


failures = []

# --- OpenWrt mock -----------------------------------------------------------
ow = connect(2201, "root", "openwrt")
board = run(ow, "ubus call system board")
if '"distribution": "OpenWrt"' not in board:
    failures.append("openwrt: system board missing OpenWrt marker")

run(ow, "uci set network.lan.ipaddr=10.0.0.1; uci commit")
ip = run(ow, "uci get network.lan.ipaddr").strip()
if ip != "10.0.0.1":
    failures.append(f"openwrt: uci roundtrip got {ip!r}")
ow.close()

# --- JetStream mock ---------------------------------------------------------
js = connect(2202, "admin", "admin")
push = "enable\nconfigure\nvlan 99\nname lab\nend\ncopy running-config startup-config\n"
run(js, push)
running = run(js, "show running-config")
if "vlan 99" not in running:
    failures.append("jetstream: pushed vlan 99 not in running-config")
js.close()

# --- OpenWrt monitoring plane (Prometheus, never SSH) -----------------------
import urllib.request

try:
    metrics = urllib.request.urlopen(
        "http://127.0.0.1:9100/metrics", timeout=10
    ).read().decode()
except Exception as exc:  # noqa: BLE001 - report as a smoke failure
    failures.append(f"openwrt: prometheus scrape failed: {exc}")
    metrics = ""
if "node_uname_info" not in metrics:
    failures.append("openwrt: /metrics missing node_uname_info")
if "mac=" not in metrics:
    failures.append("openwrt: /metrics missing wifi station mac labels")

if failures:
    print("SMOKE TEST FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("config + prometheus checks passed")
PY

echo "--- driving monitoring plane: jetstream SNMPv3 ---"
SNMP_USER="${MOCK_SNMP_USER:-hsncmon}"
SNMP_AUTH="${MOCK_SNMP_AUTH_KEY:-hsncauth123}"
SNMP_PRIV="${MOCK_SNMP_PRIV_KEY:-hsncpriv123}"
SNMP_ARGS=(-v3 -l authPriv -u "$SNMP_USER" -a SHA -A "$SNMP_AUTH" -x AES -X "$SNMP_PRIV" localhost)

sys_descr="$(docker exec mock-jetstream snmpget "${SNMP_ARGS[@]}" 1.3.6.1.2.1.1.1.0 2>&1 || true)"
echo "$sys_descr"
if ! grep -q "TL-SG2210P" <<<"$sys_descr"; then
    echo "SMOKE TEST FAILED: jetstream SNMP sysDescr missing TL-SG2210P"
    exit 1
fi

fdb="$(docker exec mock-jetstream snmpwalk "${SNMP_ARGS[@]}" 1.3.6.1.2.1.17.4.3.1.2 2>&1 || true)"
echo "$fdb"
if [ "$(grep -c "INTEGER" <<<"$fdb")" -lt 1 ]; then
    echo "SMOKE TEST FAILED: jetstream SNMP FDB walk returned no entries"
    exit 1
fi

echo "SMOKE TEST PASSED"
echo "--- done ---"
