# Developer guide

Welcome. hsnc is a self-hosted network controller built as **two independent
Python packages in one repo** that share no source code:

- **`hsnc/`** — the REST **backend**. Owns all device I/O, polling and
  persistence; exposes a JSON `/api`.
- **`hsncweb/`** — the **frontend**. Server-rendered Flask + Jinja2 + HTMX; holds
  no device connections or database and calls the backend over HTTP.

Start here:

1. [Architecture](architecture.md) — planes, layers, processes, with diagrams.
2. [Local development setup](getting-started.md) — venv, run, test, lint.
3. [Project structure](project-structure.md) — where everything lives.
4. [ADRs](../adr/README.md) — the *why* behind the design.
5. [Requirements](../requirements.md) — what the system must do.

## Tech stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Backend | Flask REST API, gunicorn |
| Frontend | Flask + Jinja2 + HTMX, checked-in CSS (no Node build) |
| Config storage | YAML |
| Runtime telemetry | SQLite (WAL, retention-pruned) |
| Apply history | append-only JSONL |
| Device I/O | SSH (paramiko); optional SNMPv3 (pysnmp), Prometheus (urllib) |
| Packaging | Docker + s6-overlay (two supervised processes) |
| Tooling | ruff, pytest, Makefile |

## Conventions

- Line length 100, ruff rules `E/F/I/UP/B`, target py311.
- Keep the dependency direction: entities/ports → use cases → adapters →
  delivery. Only `container.py` wires concretes to ports.
- Secrets come from the environment, never YAML or code.
- `make lint && make unit` must stay green; both packages.
