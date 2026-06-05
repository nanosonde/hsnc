# sdn-manager

An open-source, self-hosted network controller UI for **OpenWrt-based gateways &
access points** and **JetStream managed switches** (with VLANs).

- **Backend:** Python 3 + Flask
- **Frontend:** server-rendered Jinja2 + HTMX + checked-in CSS (no Node toolchain)
- **Config storage:** YAML files
- **Runtime/telemetry storage:** SQLite3 (with retention pruning)
- **Apply history:** append-only JSONL
- **Backup:** export/import a single ZIP (config + runtime + history)
- **Architecture:** Clean Architecture (domain / application / infrastructure / presentation)
- **Packaging:** Docker container running supervised processes (web + Device Broker) via s6-overlay

> **Status:** By default the runtime/monitoring plane is served by a built-in
> **mock provider**, so the UI is fully usable without hardware. VLAN, port and
> wireless editing plus the review/apply workflow work end-to-end. The real device
> drivers (OpenWrt SSH/UCI and JetStream SSH/CLI) are **fully implemented** and
> exercised by the test suite against the throwaway mock SSH containers in
> [`mocks/`](mocks/); switch to them by setting `SDNMAN_USE_MOCK_DEVICES=0`.

## Architecture

```
presentation (Flask routes, Jinja2, HTMX)
        v depends on
application (use cases, DTOs, services)
        v depends on
domain (entities, value objects, ports)
        ^ implemented by
infrastructure (YAML config, SQLite, device adapters, security)
```

The composition root in `infrastructure/container.py` is the only place that wires
concrete implementations to the abstract ports.

### Config plane vs monitoring plane

Device access is split into two independent planes, and **all device I/O happens
in the Device Broker, never in a web request** (see *Processes & storage*):

- **Config plane (SSH only).** A `DeviceAdapter` (`supports` / `fetch_config` /
  `push_config`) reads and writes declarative configuration over SSH only —
  OpenWrt UCI and JetStream CLI. SSH is never used for anything but configuration.
- **Monitoring plane (pluggable).** A `MonitoringProvider`
  (`fetch_status` / `fetch_clients`) supplies runtime data. The provider is
  selected per device by a `MonitoringProviderFactory`. In the broker the shipped
  providers are an **SSH-scrape fallback** (OpenWrt `ubus`, JetStream CLI), a
  **mock** provider (demo data), and a **null** provider. Richer sources
  (Prometheus node/OpenWrt exporter, SNMPv3 for switches) are intended future
  providers that slot in behind the same port without touching the config plane.

The **web process** never opens either plane directly: it reads the latest
monitoring snapshot from the runtime database and proxies any configuration
read/write to the broker over a Unix socket.

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
`/data`, plus a one-shot baseline step:

- **web** (`gunicorn`) — serves the UI. It holds **no device connections**: it
  reads the runtime database and proxies configuration reads/writes to the
  broker. It is the only writer of the apply history (`history.jsonl`) and of the
  staged configuration (`desired_config.json`).
- **Device Broker** (`sdnman-ctl broker`) — the always-on owner of **all device
  I/O**. It keeps a persistent SSH connection warm to every device (each on its
  own thread, reconnecting independently on loss), serves the Unix-socket IPC API
  the web app calls, and is the **only writer** of the runtime database
  (`runtime.db`, SQLite in WAL mode) and the baseline (`current_config.json`). On
  each poll cycle it records a snapshot and prunes rows older than
  `SDNMAN_RETENTION_DAYS`.
- **baseline** (`sdnman-ctl baseline`, one-shot) — after the broker is up, reads
  the live configuration from every device into `current_config.json` and records
  an `action="baseline"` event in the history, so the starting point is visible
  and survives restarts. Gated by `SDNMAN_BASELINE_ON_START` (default on).

Keeping connections in the broker — warm and out of the request path — is what
makes the web UI fast: an unreachable device can never slow down or block a page.
The single-writer-per-store split (history/desired in the web, runtime/baseline
in the broker) means neither process contends with the other for writes.

## CLI

```bash
sdnman-ctl serve            # run the web app (development)
sdnman-ctl broker           # run the Device Broker (owns device I/O; used by the container)
sdnman-ctl baseline         # read the live baseline from all devices (needs the broker)
sdnman-ctl poll             # run one poll cycle and exit (broker profile)
sdnman-ctl backup export ./backup.zip
sdnman-ctl backup import ./backup.zip
```

## Quick start (Docker)

```bash
docker compose up --build
# open http://<host>:8080
```

Default logins (change immediately): `admin` / `admin` and `viewer` / `viewer`.

Data (YAML config, `desired_config.json`, `current_config.json`, `runtime.db`,
`history.jsonl` and the broker socket `broker.sock`) persists in the
`controller-data` Docker volume.

## Quick start (local dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
sdnman-ctl serve --debug          # http://localhost:8080
```

## Developer tasks

A [`Makefile`](Makefile) wraps the common workflows (run `make help` for the full
list):

```bash
make check        # fast syntax compile-check of all sources
make lint         # ruff
make unit         # unit tests (pytest)
make integration  # smoke test against the mock SSH containers (needs docker)
make test         # unit + integration
make all          # check + lint + test
make mocks-up     # build & start the mock SSH devices (detached)
make mocks-down   # stop and remove the mock devices
make docker-build # build the production image
make docker-clean # remove the production image
```

The targets use the project virtualenv (`.venv`) automatically when present;
override the interpreter with `make PYTHON=/path/to/python <target>`.

Or run the tools directly:

```bash
pytest
ruff check src tests
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
sdnman-ctl backup export ./backup.zip
sdnman-ctl backup import ./backup.zip
```

## Configuration

YAML files live in `SDNMAN_CONFIG_DIR` (default `./config`, or `/data/config` in Docker):

| File                   | Purpose                                   |
| ---------------------- | ----------------------------------------- |
| `site.yaml`            | Single site definition                    |
| `users.yaml`           | Controller users (hashed passwords, roles)|
| `devices.yaml`         | Device inventory — **connection profiles only** (how to reach each device) |
| `devices.yaml.example` | Template inventory; copy to `devices.yaml`|

`devices.yaml` holds only *how to reach* each device (id, name, kind, site, IP,
SSH `connection` block and optional `monitoring` block). The actual device
configuration (VLANs, ports, SSIDs, model/firmware) is **not** stored in YAML:

- **`desired_config.json`** (in `SDNMAN_DATA_DIR`) — the staged/intended
  configuration written by the web app. Reads merge it onto the connection
  profile from `devices.yaml`.
- **`current_config.json`** (in `SDNMAN_DATA_DIR`) — the last configuration read
  back from the devices by the broker (the baseline / live state).

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
| `SDNMAN_CONFIG_DIR`        | `config`| Path to YAML config directory            |
| `SDNMAN_DATA_DIR`          | `data`  | Path to runtime data directory (`desired_config.json`, `current_config.json`, `runtime.db`, `history.jsonl`, `broker.sock`) |
| `SDNMAN_USE_MOCK_DEVICES`  | `1`     | `1` mock providers, `0` real SSH drivers |
| `SDNMAN_POLL_INTERVAL`     | `30`    | Broker poll-cycle interval (seconds)     |
| `SDNMAN_RETENTION_DAYS`    | `30`    | Drop runtime rows older than N days (`0` disables pruning) |
| `SDNMAN_BASELINE_ON_START` | `1`     | `1` read each device's live config into `current_config.json` at startup and record it as the history baseline; `0` skip |
| `SDNMAN_BROKER_SOCKET`     | `<data>/broker.sock` | Unix socket the broker listens on and the web app dials |
| `SDNMAN_SECRET_KEY`        | `dev-insecure-change-me` | Flask session secret (set in production) |

#### Real-device SSH (when `SDNMAN_USE_MOCK_DEVICES=0`)

Passwords are resolved only from the environment and are never stored in
`config/devices.yaml`. Install the optional driver with `pip install '.[ssh]'`.

| Variable                          | Default        | Description                                            |
| --------------------------------- | -------------- | ----------------------------------------------------- |
| `SDNMAN_SSH_HOST_OVERRIDE`        | _(unset)_      | Force a host/IP for every device (e.g. `127.0.0.1`)   |
| `SDNMAN_SSH_ACCEPT_UNKNOWN_HOSTS` | `1`            | `1` auto-accept unknown host keys, `0` reject         |
| `SDNMAN_OPENWRT_SSH_PASSWORD`     | `openwrt`      | Effective fallback password for OpenWrt devices (the env var itself is unset; `openwrt` is applied when no per-device password is set) |
| `SDNMAN_JETSTREAM_SSH_PASSWORD`   | `admin`        | Effective fallback password for JetStream switches (the env var itself is unset; `admin` is applied when no per-device password is set) |
| `SDNMAN_DEVICE_<ID>_PASSWORD`     | _(unset)_      | Per-device password (id upper-cased, non-alnum → `_`); takes precedence over the platform fallback |

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

- **Jinja2 templates** (`presentation/templates/`) render full HTML pages on the
  server. `base.html` is the shared layout (top bar, left sidebar, content area);
  each page does `{% extends "base.html" %}` and fills in the content block.
- **HTMX** (`static/js/htmx.min.js`) adds the few dynamic bits without hand-written
  JavaScript. You annotate an element with attributes like
  `hx-get="/clients?..."` and `hx-target="#client-table"`: HTMX fetches that URL and
  swaps the returned HTML into the target element. The matching route
  (`clients_bp.py`) notices the `HX-Request` header and returns just the table
  partial instead of the whole page. This powers the live client search and
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
