# sdnman — REST backend

The backend half of [sdn-manager](../README.md): a standalone REST service that owns
all device I/O, polling and persistence for OpenWrt gateways/APs and JetStream
switches. It exposes a JSON `/api` surface consumed by the [sdnweb](../sdnweb) frontend.

This package shares no source code with `sdnweb`.

## Layout

The package is flat: domain, application and infrastructure modules live directly
under `src/sdnman/`, with cohesive subpackages for the larger functional groups.

- **Core modules** (top level) — `entities.py`, `value_objects.py`, `enums.py`,
  `interfaces.py` (ports); `dtos.py`, `services.py`, `formatters.py`, `wire.py`
  (the JSON wire contract); `security.py`; and `container.py`, the composition root
  that wires concrete implementations to the abstract ports.
- `src/sdnman/use_cases` — the application use cases.
- `src/sdnman/config` — YAML/JSON config repositories and stores.
- `src/sdnman/devices` — device adapters, monitoring providers, SSH transport.
- `src/sdnman/persistence` — SQLite runtime store and JSONL apply history.
- `src/sdnman/backend` — the Flask REST app, background runtime and CLI.

## Console script

```sh
sdnman-ctl api          # run the REST backend dev server (default 127.0.0.1:8081)
sdnman-ctl poll         # run a single device poll sweep and exit
sdnman-ctl backup export ./backup.zip
sdnman-ctl backup import ./backup.zip
```

Production serving uses gunicorn: `gunicorn sdnman.backend.wsgi:app`.

## Develop

```sh
pip install -e .[dev,ssh]
ruff check src tests
pytest
```
