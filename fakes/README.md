# Mock devices

Controllable simulators of the network devices hsnc manages, each as its own
Docker container. They serve **both planes** so the real device drivers can be
developed and tested without physical hardware: the **configuration plane** over
SSH, and the **monitoring plane** over a non-SSH transport fixed per platform
(Prometheus for OpenWrt, SNMPv3 for JetStream).

| Mock | Emulates | Config plane (SSH) | Monitoring plane | Login |
| --- | --- | --- | --- | --- |
| [`openwrt/`](./openwrt) | OpenWrt router / AP | `uci` + `ubus`, port `2201` | Prometheus exporter, port `9100` | `root` / `openwrt` |
| [`jetstream/`](./jetstream) | TP-Link JetStream switch | JetStream CLI, port `2202` | SNMPv3, UDP port `1161` | `admin` / `admin` |

Each is a **device simulator**, not part of the app. They emulate exactly the
command surface emitted and consumed by the renderers, the SSH adapters, and the
monitoring providers:

- `UciConfigRenderer` / `OpenWrtSshAdapter` ⟷ `mock-openwrt` (SSH)
- `OpenWrtPrometheusMonitoringProvider` ⟷ `mock-openwrt` (`:9100/metrics`)
- `JetStreamCliRenderer` / `JetStreamCliAdapter` ⟷ `mock-jetstream` (SSH)
- `JetStreamSnmpMonitoringProvider` ⟷ `mock-jetstream` (SNMPv3 `161/udp`)

## Quickstart

```sh
# Build & start both mocks
docker compose -f fakes/docker-compose.yml up -d --build

# OpenWrt: read board info, round-trip a config change
ssh -p 2201 root@localhost 'ubus call system board'
ssh -p 2201 root@localhost 'uci set network.lan.ipaddr=10.0.0.1; uci commit; uci get network.lan.ipaddr'

# JetStream: inspect and push config
ssh -p 2202 admin@localhost 'show running-config'
printf 'enable\nconfigure\nvlan 99\nname lab\nend\ncopy running-config startup-config\nshow running-config\n' \
  | ssh -p 2202 admin@localhost

# Monitoring plane (never SSH): scrape OpenWrt metrics, poll JetStream over SNMPv3
curl -s http://localhost:9100/metrics | grep -E 'node_uname_info|mac='
docker exec mock-jetstream snmpget -v3 -l authPriv -u hsncmon \
  -a SHA -A hsncauth123 -x AES -X hsncpriv123 localhost 1.3.6.1.2.1.1.1.0

# Stop (keep state) / wipe state
docker compose -f fakes/docker-compose.yml down
docker compose -f fakes/docker-compose.yml down -v
```

> First connection prints an SSH host-key warning. For scripted access use
> `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ...`.

## How the real adapters connect

`DefaultDeviceAdapterFactory(use_mock=False)` (env `HSNC_USE_MOCK_DEVICES=0`) routes
by device kind to the SSH adapters:

- `GATEWAY` / `ACCESS_POINT` → `OpenWrtSshAdapter` (ssh user `root`, port 22) → `mock-openwrt`
- `SWITCH` → `JetStreamCliAdapter` (ssh user `admin`, port 22) → `mock-jetstream`

Within the compose network the adapters reach the mocks at hostnames `mock-openwrt`
and `mock-jetstream` on port 22; from the host they are on `localhost:2201` / `:2202`.

The adapters need the optional SSH driver (`pip install '.[ssh]'`). Per-device host,
port and username come from a `connection:` block in `config/devices.yaml`; passwords
are resolved only from the environment (`HSNC_OPENWRT_SSH_PASSWORD`,
`HSNC_JETSTREAM_SSH_PASSWORD`, or `HSNC_DEVICE_<ID>_PASSWORD`). The SSH adapters
run inside the **REST backend** (the web app only talks to it over HTTP), so drive the
mocks through the backend:

```sh
HSNC_USE_MOCK_DEVICES=0 \
HSNC_SSH_HOST_OVERRIDE=127.0.0.1 \
HSNC_OPENWRT_SSH_PASSWORD=openwrt \
HSNC_JETSTREAM_SSH_PASSWORD=admin \
  hsnc-ctl api   # set connection.port 2201/2202 per device, or override per run
```

The backend reads the live baseline on start and polls the devices; run
`hsnc-web serve` in another shell to use the UI against it.

## Mapping to the sample inventory (`config/devices.yaml`)

| Sample device | Kind | Mock |
| --- | --- | --- |
| `gateway-1` (ER605) | gateway | mock-openwrt |
| `ap-1` (EAP245) | access point | mock-openwrt |
| `switch-1` (TL-SG2210P) | switch | mock-jetstream (seed matches its VLANs/ports) |
| `switch-2` (GS1900-OWRT) | switch | mock-openwrt (OpenWrt-based) |

## Credentials & keys

Set via env in `docker-compose.yml` (or `.env`):

- `MOCK_OPENWRT_PASSWORD`, `MOCK_JETSTREAM_PASSWORD` — override default SSH passwords
- `MOCK_SSH_PUBKEY` per service — enable public-key auth
- `MOCK_SNMP_USER`, `MOCK_SNMP_AUTH_KEY`, `MOCK_SNMP_PRIV_KEY` — the SNMPv3 USM
  user the JetStream mock accepts (defaults `hsncmon` / `hsncauth123` /
  `hsncpriv123`, SHA auth + AES priv, `authPriv`). The controller must match
  these via `HSNC_SNMP_USER` / `HSNC_SNMP_AUTH_KEY` / `HSNC_SNMP_PRIV_KEY`.
- `MOCK_PROMETHEUS_TOKEN` on the OpenWrt mock — when set, `/metrics` requires an
  `Authorization: Bearer <token>` header (matching `HSNC_PROMETHEUS_TOKEN`).

## The two planes

The **configuration plane** is SSH only (`uci`/`ubus`, JetStream CLI). The
**monitoring plane** never uses SSH:

- **OpenWrt** runs a fake `prometheus-node-exporter`-style endpoint on `:9100`
  exposing `node_*` metrics (uptime, `node_uname_info`) and per-station
  `wifi_stations_*` metrics derived from the same DHCP leases the SSH `ubus`
  surface reports — so both planes stay coherent.
- **JetStream** runs `snmpd` (SNMPv3, `authPriv`) answering MIB-II scalars
  (`sysDescr`/`sysUpTime`/`sysName`) and a BRIDGE-MIB forwarding table
  (`dot1dTpFdbPort`) that mirrors `show mac address-table`.

## Verifying the mocks

`smoke_test.sh` builds, starts, and drives both mocks across both planes — the
configuration plane over real SSH (using paramiko) and the monitoring plane via
Prometheus (`/metrics`) and SNMPv3 (`snmpget`/`snmpwalk`) — then tears everything
down:

```sh
fakes/smoke_test.sh
```

It requires Docker + Docker Compose and `pip install paramiko`.
