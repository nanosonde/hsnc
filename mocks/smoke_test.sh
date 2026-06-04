#!/usr/bin/env bash
# Build, start, and drive both device mocks over real SSH, then tear down.
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
python3 - "$@" <<'PY'
import socket
import sys
import time

for port in (2201, 2202):
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                break
        except OSError:
            time.sleep(1)
    else:
        sys.exit(f"timeout waiting for port {port}")
print("ssh ports are open")
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

if failures:
    print("SMOKE TEST FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("SMOKE TEST PASSED")
PY

echo "--- done ---"
