# hsnc

*A self-hosted **h**ome & **s**mall-**n**etwork **c**ontroller.*

An open-source, self-hosted network controller UI for **OpenWrt-based gateways &
access points** and **JetStream managed switches** (with VLANs).

- **Backend:** Python 3 + Flask
- **Frontend:** server-rendered Jinja2 + HTMX + checked-in CSS (no Node toolchain)
- **Config storage:** YAML files
- **Runtime/telemetry storage:** SQLite3 (with retention pruning)
- **Apply history:** append-only JSONL
- **Backup:** export/import a single ZIP (config + runtime + history)
- **Architecture:** two standalone packages in one repo — a REST **backend**
  (`hsnc/`) and a server-rendered web **frontend** (`hsncweb/`) that share no code
- **Packaging:** Docker container running supervised processes (web + REST backend) via s6-overlay

> **Status:** The real device drivers (OpenWrt SSH/UCI and JetStream SSH/CLI) are
> **fully implemented** and exercised by the test suite against the throwaway fake
> SSH containers in [`fakes/`](fakes/). The bundled `docker-compose.yml` targets
> real hardware (`HSNC_USE_MOCK_DEVICES=0`) and requires your own
> `config/devices.yaml`. For a hardware-free trial, set `HSNC_USE_MOCK_DEVICES=1`
> to serve the runtime/monitoring plane from a built-in **mock provider** with a
> sample inventory — VLAN, port and wireless editing plus the review/apply
> workflow then work end-to-end without any devices.

## Architecture

The repository contains **two independent Python packages that share no source code**:

- **`hsnc/`** — the REST **backend**. It owns all device I/O, polling and
  persistence and exposes a JSON `/api` surface. It keeps a clean
  dependency direction (entities and ports → use cases → adapters → the `backend`
  delivery layer) in a flat module layout; the composition root in
  `hsnc/src/hsnc/container.py` is the only place that wires concrete
  implementations to the abstract ports.
- **`hsncweb/`** — the **frontend**. A pure presentation tier (Flask + Jinja2 +
  HTMX): it holds no device connections, database or use-case logic and reaches
  the backend over HTTP for every read and write.

```
hsncweb (Flask routes, Jinja2, HTMX)
        v HTTP /api
hsnc backend (REST delivery: api / app / runtime / cli)
        v calls
use cases (+ DTOs, services)
        v depend on
entities, value objects, ports (interfaces)
        ^ implemented by
adapters (YAML config, SQLite, device drivers, security)
```

The dependency direction above is preserved, but the modules live in a **flat
layout** under `hsnc/src/hsnc/` rather than in nested layer folders — see the
[package README](hsnc/README.md#layout).

### Config plane vs monitoring plane

Device access is split into two independent planes, and **all device I/O happens
in the backend, never in a web request** (see *Processes & storage*):

- **Config plane (SSH only).** A `DeviceAdapter` (`supports` / `fetch_config` /
  `push_config`) reads and writes declarative configuration over SSH only —
  OpenWrt UCI and JetStream CLI. SSH is never used for anything but configuration.
- **Monitoring plane (pluggable).** A `MonitoringProvider`
  (`fetch_status` / `fetch_clients`) supplies runtime data. The provider is
  selected per device by a `MonitoringProviderFactory`. The shipped providers are
  an **SSH-scrape fallback** (OpenWrt `ubus`, JetStream CLI), a **mock** provider
  (demo data), and a **null** provider. Richer sources (Prometheus node/OpenWrt
  exporter, SNMPv3 for switches) are intended future providers that slot in behind
  the same port without touching the config plane.

The **web frontend** never opens either plane directly: every read and write is an
HTTP call to the backend, which serves runtime data from its latest monitoring
snapshot and performs all configuration reads/writes itself.

If a device has no working runtime source (e.g. a JetStream switch with no SNMP
provider yet), it simply reports **no runtime data** rather than failing.

### Reachability

Runtime polling is best-effort and degrades gracefully:

| Monitoring result            | Device status displayed |
| ---------------------------- | ----------------------- |
| reachable, device up         | `CONNECTED`             |
| reachable, device down       | `DISCONNECTED`          |
| unreachable / no source      | `UNKNOWN`               |

A failed poll for one device never affects the others or the web UI.

### Processes & storage

The container runs **two long-running processes** under s6-overlay that share
`/data`:

- **web** (`gunicorn hsncweb.wsgi:app`) — serves the UI. It holds **no device
  connections** and no database: every read and write is an HTTP call to the
  backend.
- **api / backend** (`gunicorn hsnc.backend.wsgi:app`) — the always-on owner of
  **all device I/O**. It keeps a persistent SSH connection warm to every device
  (each on its own thread, reconnecting independently on loss), serves the `/api`
  surface the web app calls, and is the **only writer** of the runtime database
  (`runtime.db`, SQLite in WAL mode), the apply history (`history.jsonl`), the
  staged configuration (`desired_config.json`) and the baseline
  (`current_config.json`). On each poll cycle it records a snapshot and prunes
  rows older than `HSNC_RETENTION_DAYS`. On startup, gated by
  `HSNC_BASELINE_ON_START` (default on), it reads each device's live
  configuration into `current_config.json` and records an `action="baseline"`
  event so the starting point is visible and survives restarts.

Keeping connections in the backend — warm and out of the request path — is what
makes the web UI fast: an unreachable device can never slow down or block a page.

## CLI

Two console scripts, one per package:

```bash
hsnc-web serve                # run the web frontend (development)

hsnc-ctl api              # run the REST backend (owns device I/O; used by the container)
hsnc-ctl poll             # run one device poll cycle and exit
hsnc-ctl backup export ./backup.zip
hsnc-ctl backup import ./backup.zip
```

## Quick start (Docker)

The bundled `docker-compose.yml` runs against **real devices** and will refuse to
start until you supply your own inventory. Create it from the template first:

```bash
cp config/devices.yaml.example config/devices.yaml   # then edit for your network
cp .env.example .env                                 # then set secrets/passwords
docker compose up --build                            # or: make up
# open http://<host>:8080
```

`config/devices.yaml` is bind-mounted into the container (read-only); SSH
passwords come from the environment (see the env table and `.env.example`), never
from the YAML. If `config/devices.yaml` is missing the container exits with a
clear error.

For a **hardware-free demo**, build the image and run it with mock devices
instead (seeds a sample inventory automatically):

```bash
docker build -t hsnc:latest .
docker run --rm -p 8080:8080 -e HSNC_USE_MOCK_DEVICES=1 hsnc:latest
```

Default logins (change immediately): `admin` / `admin` and `viewer` / `viewer`.

Data (YAML config, `desired_config.json`, `current_config.json`, `runtime.db` and
`history.jsonl`) persists in the `controller-data` Docker volume.

## Quick start (local dev)

The two packages install separately into the same virtualenv. The web frontend
needs the backend running (the web test harness also imports it), so install both:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e "./hsnc[dev,ssh]" -e "./hsncweb[dev]"

hsnc-ctl api                    # REST backend on http://localhost:8081 (owns device I/O)
hsnc-web serve --debug              # web UI on http://localhost:8080, in a second shell
```

In mock mode (`HSNC_USE_MOCK_DEVICES=1`, the default) the backend uses the demo
providers, so no real hardware is needed. Point the frontend at a non-default
backend with `HSNC_API_BASE_URL` (and `HSNC_API_TOKEN` when set).

## Developer tasks

A [`Makefile`](Makefile) wraps the common workflows (run `make help` for the full
list):

```bash
make check        # fast syntax compile-check of all sources
make lint         # ruff
make unit         # unit tests (pytest)
make integration  # smoke test against the fake SSH containers (needs docker)
make test         # unit + integration
make all          # check + lint + test
make fakes-up     # build & start the fake SSH devices (detached)
make fakes-down   # stop and remove the fake devices
make docker-build # build the production image
make docker-clean # remove the production image
```

The targets use the project virtualenv (`.venv`) automatically when present;
override the interpreter with `make PYTHON=/path/to/python <target>`.

Or run the tools directly in either package:

```bash
(cd hsnc && pytest && ruff check src tests)
(cd hsncweb && pytest && ruff check src tests)
```

## Pending changes & apply

The controller is the source of truth: edits to VLANs, ports and wireless are
staged as **pending changes** rather than pushed immediately. From
**Devices → Review & Apply** (`/config/pending`) you can:

- review each device's changes grouped by section (General / VLANs / Ports /
  Wireless) as a **Current → New** diff;
- inspect the concrete commands that will be sent, plus a LuCI-style
  **UCI field diff** for OpenWrt devices;
- **Apply** or **Revert** per device, or **Apply All** / **Revert All Changes**.

Nothing is sent to a device until you apply. Each apply is recorded in the
history (`/config/history`).

> **Read-only mode (default on):** as a safety default the controller starts in
> read-only mode, where applying to devices is blocked. An admin enables applying
> by switching off the **Read-only mode** toggle in the top bar. Editing config and
> reverting pending changes stay available either way.

## Backups

From the UI (admin only): **Backup → Download / Import**.

From the CLI:

```bash
hsnc-ctl backup export ./backup.zip
hsnc-ctl backup import ./backup.zip
```

## Configuration

YAML files live in `HSNC_CONFIG_DIR` (default `./config`, or `/data/config` in Docker):

| File                   | Purpose                                   |
| ---------------------- | ----------------------------------------- |
| `site.yaml`            | Single site definition                    |
| `users.yaml`           | Controller users (hashed passwords, roles)|
| `devices.yaml`         | Device inventory — **connection profiles only** (how to reach each device) |
| `devices.yaml.example` | Template inventory; copy to `devices.yaml`|

`devices.yaml` holds only *how to reach* each device (id, name, kind, site, IP,
SSH `connection` block and optional `monitoring` block). The actual device
configuration (VLANs, ports, SSIDs, model/firmware) is **not** stored in YAML:

- **`desired_config.json`** (in `HSNC_DATA_DIR`) — the staged/intended
  configuration written by the web app. Reads merge it onto the connection
  profile from `devices.yaml`.
- **`current_config.json`** (in `HSNC_DATA_DIR`) — the last configuration read
  back from the devices by the backend (the baseline / live state).

`devices.yaml` is environment-specific and ignored by git. Create it from the
shipped template before running locally:

```bash
cp config/devices.yaml.example config/devices.yaml
```

In Docker this copy happens automatically: the seed step writes `devices.yaml`
from the baked-in template on first run if one does not already exist.

### Environment variables

| Variable                  | Default | Description                              |
| ------------------------- | ------- | ---------------------------------------- |
| `HSNC_CONFIG_DIR`        | `config`| Path to YAML config directory            |
| `HSNC_DATA_DIR`          | `data`  | Path to runtime data directory (`desired_config.json`, `current_config.json`, `runtime.db`, `history.jsonl`) |
| `HSNC_USE_MOCK_DEVICES`  | `1`     | `1` mock providers, `0` real SSH drivers |
| `HSNC_POLL_INTERVAL`     | `30`    | Backend poll-cycle interval (seconds)    |
| `HSNC_RETENTION_DAYS`    | `30`    | Drop runtime rows older than N days (`0` disables pruning) |
| `HSNC_BASELINE_ON_START` | `1`     | `1` read each device's live config into `current_config.json` at startup and record it as the history baseline; `0` skip |
| `HSNC_LOG_LEVEL`         | `info`  | Application log verbosity: `debug`, `info`, `warning`, `error`, `critical` (case-insensitive; unknown values fall back to `info`) |
| `HSNC_API_BASE_URL`      | `http://127.0.0.1:8081` | Backend URL the web frontend calls |
| `HSNC_API_TOKEN`         | _(unset)_ | Bearer token the backend requires and the frontend sends (empty = no auth) |
| `HSNC_SECRET_KEY`        | `dev-insecure-change-me` | Flask session secret (set in production) |

### Logging

Three independent controls govern what ends up in the logs (`make logs`, i.e. the
container's stdout/stderr). They compose freely and can be combined.

1. **`HSNC_LOG_LEVEL`** — the verbosity of the application's *own* loggers
   (`hsnc.*` in the backend, `hsncweb` in the frontend). Accepts `debug`, `info`,
   `warning`, `error`, `critical` (case-insensitive; unknown values fall back to
   `info`). This is the normal knob for everyday logging and applies to **both**
   services. Third-party libraries (Werkzeug, urllib3, paramiko) are left at their
   own defaults so raising this to `debug` does not drown you in library noise.

2. **`HSNC_SSH_TRANSCRIPT_DEBUG`** (+ per-device) — mirrors the full SSH
   *transcript* to the logs: every command the controller sends, the output each
   device returns, and connection lifecycle notes. This is the same content as the
   per-device **View SSH connection** popup in the web UI, streamed to the log on a
   dedicated `hsnc.ssh.transcript` logger. It is **independent of
   `HSNC_LOG_LEVEL`** — enabled transcript lines appear even when `HSNC_LOG_LEVEL`
   is `error`.

3. **`HSNC_SSH_DEBUG`** (+ per-device) — turns on paramiko's *own* SSH
   transport/wire-level `DEBUG` logging (key exchange, channel management,
   keepalives, etc.). Also independent of `HSNC_LOG_LEVEL`.
   - With the **global** flag on, paramiko logs at `DEBUG` for **every** device,
     including the connection **handshake**.
   - With only a **per-device** flag on (global off), that device's
     **post-handshake** transport activity is logged on its own
     `paramiko.transport.<id>` channel; the handshake itself is captured **only**
     when the global flag is enabled.

**Per-device overrides.** Both SSH-debug flags support a per-device form,
`HSNC_DEVICE_<ID>_SSH_TRANSCRIPT_DEBUG` and `HSNC_DEVICE_<ID>_SSH_DEBUG`, where
`<ID>` is the device id upper-cased with non-alphanumeric characters replaced by
`_` (e.g. `gateway-1` → `HSNC_DEVICE_GATEWAY_1_SSH_DEBUG`). An explicit per-device
value **overrides the global default in either direction** — it can force
debugging *off* for one noisy device while a global flag is on, or *on* for a
single device while the global default is off. All flags accept `1`/`true`/`yes`/
`on` as truthy (case-insensitive); anything else is false.

Example `.env` for maximum debugging of a single device:

```bash
HSNC_LOG_LEVEL=info                              # leave the rest of the app calm
HSNC_DEVICE_GATEWAY_1_SSH_TRANSCRIPT_DEBUG=1     # mirror its SSH transcript
HSNC_DEVICE_GATEWAY_1_SSH_DEBUG=1                # + paramiko post-handshake detail
HSNC_SSH_DEBUG=1                                 # (optional) also capture handshakes
```

> **Security warning.** The SSH transcript and paramiko debug logs can contain
> sensitive data — Wi-Fi pre-shared keys, device passwords typed into a CLI,
> key-exchange details — written in clear text to the container logs. Enable them
> only while actively diagnosing, prefer the per-device flags, and turn them off
> afterwards.
>
> Devices that share the same host, port and username share a single warm
> connection (and therefore one transcript and one paramiko channel); the first
> device resolved wins the debug flags for that shared connection.

#### Real-device SSH (when `HSNC_USE_MOCK_DEVICES=0`)

Passwords are resolved only from the environment and are never stored in
`config/devices.yaml`. Install the optional driver with `pip install '.[ssh]'`.

| Variable                          | Default        | Description                                            |
| --------------------------------- | -------------- | ----------------------------------------------------- |
| `HSNC_SSH_HOST_OVERRIDE`        | _(unset)_      | Force a host/IP for every device (e.g. `127.0.0.1`)   |
| `HSNC_SSH_ACCEPT_UNKNOWN_HOSTS` | `1`            | `1` auto-accept unknown host keys, `0` reject         |
| `HSNC_OPENWRT_SSH_PASSWORD`     | `openwrt`      | Effective fallback password for OpenWrt devices (the env var itself is unset; `openwrt` is applied when no per-device password is set) |
| `HSNC_JETSTREAM_SSH_PASSWORD`   | `admin`        | Effective fallback password for JetStream switches (the env var itself is unset; `admin` is applied when no per-device password is set) |
| `HSNC_DEVICE_<ID>_PASSWORD`     | _(unset)_      | Per-device password (id upper-cased, non-alnum → `_`); takes precedence over the platform fallback |
| `HSNC_SSH_DEBUG`                | `0`            | Global paramiko transport `DEBUG` logging (handshake + all devices). See [Logging](#logging) |
| `HSNC_DEVICE_<ID>_SSH_DEBUG`    | _(unset)_      | Per-device paramiko transport `DEBUG` (post-handshake); overrides the global flag either direction |
| `HSNC_SSH_TRANSCRIPT_DEBUG`     | `0`            | Global: mirror the full SSH transcript (commands + output) to the log; independent of `HSNC_LOG_LEVEL` |
| `HSNC_DEVICE_<ID>_SSH_TRANSCRIPT_DEBUG` | _(unset)_ | Per-device transcript mirroring; overrides the global flag either direction |

Per-device host, port and username come from the `connection` block in
`config/devices.yaml`:

```yaml
  - id: gateway-1
    # ...
    connection:
      host: ""        # blank -> use the device's management IP
      port: 22
      username: root
```

## Frontend (no build step)

The UI is server-rendered, with **no Node/JavaScript build pipeline** — the browser
loads exactly what is checked into the repo:

- **Jinja2 templates** (`hsncweb/src/hsncweb/templates/`) render full HTML pages on
  the server. `base.html` is the shared layout (top bar, left sidebar, content
  area); each page does `{% extends "base.html" %}` and fills in the content block.
- **HTMX** (`static/js/htmx.min.js`) adds the few dynamic bits without hand-written
  JavaScript. You annotate an element with attributes like
  `hx-get="/clients?..."` and `hx-target="#client-table"`: HTMX fetches that URL and
  swaps the returned HTML into the target element. The matching route
  (`blueprints/clients_bp.py`) notices the `HX-Request` header and returns just the
  table partial instead of the whole page. This powers the live client search and
  pagination — the only HTMX on the site.
- **`static/js/ui.js`** is a tiny hand-written script whose only job is to
  collapse/expand the sidebar and remember that choice in `localStorage`.
- **CSS** is one hand-written file, `static/css/app.css` (no Tailwind). Colours,
  spacing, radius and fonts are declared once as **CSS variables** (custom
  properties) in the `:root` block at the top — e.g. `--accent`, `--panel`,
  `--radius-card` — and reused everywhere via `var(--accent)`. Change a value in
  `:root` to restyle the whole app. The rest of the file is grouped into labelled
  sections (e.g. `/* ---------- Tables ---------- */`).

## Roadmap

- Multi-site support.

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE).

This is free software: you may use, modify and redistribute it (including
commercially) under the terms of the GNU Affero General Public License. Because of
the AGPL's network-interaction clause (section 13), if you run a modified version
as a network service you must offer its complete source code to the users of that
service. It is provided **as is**, without any warranty.
