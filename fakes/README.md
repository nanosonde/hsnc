# Mock devices

Controllable simulators of the network devices hsnc manages, each as its own
Docker container reachable over **SSH**. They exist so the real device adapters can be
developed and tested against realistic SSH targets without physical hardware.

| Mock | Emulates | Transport | Host port | Login |
| --- | --- | --- | --- | --- |
| [`openwrt/`](./openwrt) | OpenWrt router / AP | `uci` + `ubus` over SSH | `2201` | `root` / `openwrt` |
| [`jetstream/`](./jetstream) | TP-Link JetStream switch | JetStream CLI over SSH | `2202` | `admin` / `admin` |

Each is a **device simulator**, not part of the app. They emulate exactly the command
surface emitted and consumed by the renderers and the SSH adapters:

- `UciConfigRenderer` / `OpenWrtSshAdapter` ⟷ `mock-openwrt`
- `JetStreamCliRenderer` / `JetStreamCliAdapter` ⟷ `mock-jetstream`

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

- `MOCK_OPENWRT_PASSWORD`, `MOCK_JETSTREAM_PASSWORD` — override default passwords
- `MOCK_SSH_PUBKEY` per service — enable public-key auth

## Verifying the mocks

`smoke_test.sh` builds, starts, and drives both mocks over real SSH (using paramiko),
then tears everything down:

```sh
fakes/smoke_test.sh
```

It requires Docker + Docker Compose and `pip install paramiko`.
