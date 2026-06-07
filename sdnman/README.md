# sdnman — REST backend

The backend half of [sdn-manager](../README.md): a standalone REST service that owns
all device I/O, polling and persistence for OpenWrt gateways/APs and JetStream
switches. It exposes a JSON `/api` surface consumed by the [sdnweb](../sdnweb) frontend.

This package shares no source code with `sdnweb`.

## Layout

- `src/sdnman/domain` — entities, value objects, enums, ports.
- `src/sdnman/application` — use cases, DTOs, the JSON wire contract.
- `src/sdnman/infrastructure` — config repositories, device adapters, persistence,
  the composition container.
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
