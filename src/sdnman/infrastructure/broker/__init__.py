"""The Device Broker package.

The broker is an always-on process that owns every device connection. It keeps a
persistent primary (SSH) connection — and optionally a secondary live-data
channel — open to each device, and exposes a small HTTP API over a Unix socket
so the web process can read and push configuration without ever connecting to a
device itself. This is the core of keeping the web UI fast.

Modules:

* :mod:`.connection_pool` — keeps primary connections warm, one thread per device
* :mod:`.server` — the Unix-socket HTTP API (broker side)
* :mod:`.client` — the IPC client (web side)
* :mod:`.proxy_adapter` — a :class:`DeviceAdapter` that proxies to the broker
* :mod:`.service` — wires the pool, poll loop and server into the daemon
"""
