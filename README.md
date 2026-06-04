# openwrt-manager-ui

An open-source, self-hosted network controller UI with an Omada/UniFi-style look
and feel, for **OpenWrt-based gateways & access points** and **TP-Link JetStream
managed switches** (with VLANs).

- **Backend:** Python 3 + Flask
- **Frontend:** server-rendered Jinja2 + HTMX + checked-in CSS (no Node toolchain)
- **Config storage:** YAML files
- **Runtime/telemetry storage:** SQLite3
- **Backup:** export/import a single ZIP (config + runtime history)
- **Architecture:** Clean Architecture (domain / application / infrastructure / presentation)
- **Packaging:** Docker container served over HTTP via gunicorn

> **MVP status:** Devices are served by a built-in **mock adapter** so the UI is
> fully usable without hardware. VLAN, port and wireless editing plus the
> review/apply workflow are implemented end-to-end against the mock adapter.
> Real device drivers (OpenWrt SSH/UCI, JetStream SSH/CLI) are present as
> interface-conformant **stubs** and slot in without touching the inner layers.

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

## Quick start (Docker)

```bash
docker compose up --build
# open http://<host>:8080
```

Default logins (change immediately): `admin` / `admin` and `viewer` / `viewer`.

Data (YAML config + SQLite DB) persists in the `controller-data` Docker volume.

## Quick start (local dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
omada-ctl serve --debug          # http://localhost:8080
```

## Tests & lint

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

## Backups

From the UI (admin only): **Backup → Download / Import**.

From the CLI:

```bash
omada-ctl backup export ./backup.zip
omada-ctl backup import ./backup.zip
```

## Configuration

YAML files live in `OMADA_CONFIG_DIR` (default `./config`, or `/data/config` in Docker):

| File           | Purpose                                   |
| -------------- | ----------------------------------------- |
| `site.yaml`    | Single site definition                    |
| `users.yaml`   | Controller users (hashed passwords, roles)|
| `devices.yaml` | Declarative device inventory (incl. VLANs)|

### Environment variables

| Variable                  | Default | Description                              |
| ------------------------- | ------- | ---------------------------------------- |
| `OMADA_CONFIG_DIR`        | `config`| Path to YAML config directory            |
| `OMADA_DATA_DIR`          | `data`  | Path to SQLite data directory            |
| `OMADA_USE_MOCK_DEVICES`  | `1`     | `1` mock adapters, `0` real (stub) drivers |
| `OMADA_POLL_INTERVAL`     | `30`    | Background poll interval (seconds)       |
| `OMADA_SECRET_KEY`        | dev key | Flask session secret (set in production) |

## Roadmap

- Implement `OpenWrtSshAdapter` (ubus/uci over SSH) and `JetStreamCliAdapter`.
- Multi-site support.

## License

MIT — see [LICENSE](LICENSE).
