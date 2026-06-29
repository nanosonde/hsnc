# Architecture

hsnc is two standalone packages — a REST **backend** (`hsnc/`) and a presentation
**frontend** (`hsncweb/`) — that share no code and communicate only over HTTP.

## High level

```mermaid
flowchart TB
    U[Browser] -->|HTML / HTMX| W[hsncweb frontend]
    W -->|HTTP /api JSON| B[hsnc backend]
    B -->|SSH config + primary monitoring| DEV[Devices]
    B -->|SNMPv3 / Prometheus secondary| DEV
    B --> ST[(YAML config · SQLite runtime · JSONL history)]
```

The frontend opens no device connection and has no database; the backend is the
sole owner of device I/O and persistence.

## Backend layers (Clean Architecture, flat layout)

The dependency direction is strict; modules live flat under `hsnc/src/hsnc/`
rather than in nested layer folders.

```mermaid
flowchart TD
    DEL[backend: api / app / runtime / cli] --> UC[use cases]
    UC --> CORE[entities · value objects · ports]
    AD[adapters: YAML config · SQLite · device drivers · security] -. implement .-> CORE
    DEL --> CONT[container.py composition root]
    CONT --> AD
```

- **Core** — `entities.py`, `value_objects.py`, `enums.py`, `interfaces.py`
  (ports). No framework or I/O.
- **Use cases** — one file per operation (`use_cases/`); orchestrate the core.
- **Adapters** — YAML/JSON repos, SQLite runtime store, device drivers, security.
- **Delivery** — Flask REST app, background poller, CLI.
- **Composition root** — `container.py` is the only place wiring concretes to
  ports (selecting mock vs real).

## Two planes

Device access splits into independent planes so monitoring can use a different
transport than configuration:

- **Config plane (SSH only):** `DeviceAdapter` — `supports` / `fetch_config` /
  `push_config`. OpenWrt UCI, JetStream CLI.
- **Monitoring plane (pluggable):** `MonitoringProvider` — `fetch_status` /
  `fetch_clients`, chosen per device by a `MonitoringProviderFactory` from
  `monitoring.source` (primary SSH scrape, secondary Prometheus/SNMPv3, mock,
  null). Selection is strict — no SSH fallback for a secondary device.

```mermaid
flowchart LR
    POLL[poller] --> F[MonitoringProviderFactory]
    F -->|primary| SSHM[SSH scrape]
    F -->|secondary: prometheus| PROM[OpenWrt exporter]
    F -->|secondary: snmp| SNMP[JetStream SNMPv3]
    F -->|none / misconfig| NULL[Null → UNKNOWN]
```

## Processes & data

The container runs two supervised processes (s6-overlay) sharing `/data`:

- **web** — `gunicorn hsncweb.wsgi:app`; no connections, no DB.
- **api / backend** — `gunicorn hsnc.backend.wsgi:app`; keeps SSH warm per device
  (own thread, independent reconnect), the only writer of `runtime.db`,
  `history.jsonl`, `desired_config.json`, `current_config.json`.

Keeping connections warm and out of the request path is what keeps the UI fast:
an unreachable device can never block a page.

## Config vs telemetry storage

- **YAML** — declarative inventory/users/site (diff-friendly, hand-editable).
- **SQLite** — runtime telemetry, append/prune, queried per page.
- **JSONL** — append-only apply history.

See the [ADRs](../adr/README.md) for the reasoning behind each choice.
