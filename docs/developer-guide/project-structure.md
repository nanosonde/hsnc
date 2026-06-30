# Project structure

```text
hsnc/                  REST backend package (dist: hsnc, import: hsnc)
  src/hsnc/
    entities.py        domain entities (Device, Client, Vlan, ...)
    value_objects.py   MacAddress, IpAddress, throughput/volume
    enums.py           DeviceKind, DeviceStatus, ConnectionType, ...
    interfaces.py      ports (DeviceAdapter, MonitoringProvider, repos)
    dtos.py services.py formatters.py   application glue + JSON wire contract
    security.py        password hashing/verification
    container.py       composition root (the only place wiring ports→adapters)
    use_cases/         one file per operation (apply, revert, poll, backup, ...)
    config/            YAML/JSON repositories, schemas, mapping, stores
    devices/           device drivers + monitoring providers
      ssh_transport.py shared SSH transport, resolver, settings
      factory.py       config-adapter factory (by kind)
      monitoring.py    monitoring-provider factory (by kind) + mock/null
      openwrt/         adapter, config_renderer, prometheus_monitoring
      jetstream/       adapter, config_renderer, snmp_monitoring
    persistence/       SQLite runtime store + JSONL apply history
    backend/           Flask REST app, background poller, CLI (hsnc-ctl)
  tests/               unit + fakes
hsncweb/               frontend package (dist: hsnc-web, import: hsncweb)
  src/hsncweb/
    app.py wsgi.py settings.py cli.py   Flask app + hsnc-web CLI
    api_client.py      HTTP client to the backend /api
    blueprints/        dashboard, devices, clients, config, topology, backup, auth
    templates/ static/ Jinja2 + HTMX + one CSS file (no Node build)
  tests/
config/                site.yaml, users.yaml, devices.yaml(.example)
data/                  runtime: desired/current config, runtime.db, history.jsonl
docker/                Dockerfile bits + s6-overlay service definitions
fakes/                 throwaway device simulators (both planes) for integration tests
docs/                  this documentation
```

## Layering

The flat module layout keeps the Clean-Architecture dependency direction:
`entities/ports → use_cases → adapters (config/devices/persistence) → backend`.
The frontend depends on none of it — it reaches the backend over HTTP.

## Adding a device platform

1. New package under `hsnc/src/hsnc/devices/<platform>/` with `adapter.py`
   (`DeviceAdapter`) and `config_renderer.py`.
2. A non-SSH monitoring provider (e.g. `prometheus_monitoring.py` or
   `snmp_monitoring.py`).
3. Register in `factory.py` (config) and `monitoring.py` (provider factory).
4. Wire env/settings in `container.py`; add unit tests with fakes.

See [architecture](architecture.md) and the relevant [ADRs](../adr/README.md).
