"""The Device Broker daemon.

Wires the broker-profile container into the always-on process:

* a :class:`ConnectionPool` keeps a persistent SSH connection warm to every
  device, each on its own supervisor thread with isolated reconnect;
* a :class:`UnixHttpServer` serves the IPC API the web process calls to read and
  push configuration on its behalf;
* a periodic poll loop scrapes live state into the runtime store so the web app
  can render dashboards/clients without ever touching a device.

In mock mode no real connections are opened: the pool is skipped and the mock
adapters/monitoring satisfy every request.
"""

from __future__ import annotations

import logging
import threading

from ..container import Container, Settings
from .connection_pool import ConnectionPool
from .server import BrokerApi, serve

_log = logging.getLogger("sdnman.broker")


class BrokerService:
    """Owns the connection pool, IPC server and poll loop for one process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._container = Container(settings, profile="broker")
        self._stop = threading.Event()
        self._pool: ConnectionPool | None = None
        self._server = None
        self._server_thread: threading.Thread | None = None

        if not settings.use_mock_devices:
            registry = self._container.runner_registry
            resolver = self._container.ssh_resolver
            assert registry is not None and resolver is not None
            self._pool = ConnectionPool(
                runner_for=lambda device: registry.get(resolver.resolve(device)),
                devices_provider=self._container.profiles.list_devices,
            )

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._pool is not None:
            self._pool.start()
        api = BrokerApi(self._container.config, self._container.adapters, self._pool)
        self._server = serve(self._settings.broker_socket, api)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, name="broker-ipc", daemon=True
        )
        self._server_thread.start()
        _log.info(
            "Device Broker started (socket=%s, mock=%s)",
            self._settings.broker_socket,
            self._settings.use_mock_devices,
        )

    def run(self) -> None:
        """Run the poll loop until :meth:`stop` is called."""
        interval = self._settings.poll_interval_seconds
        while not self._stop.is_set():
            try:
                count = self._container.poll_device_state.execute()
                _log.info("Polled %d device(s)", count)
            except Exception:  # noqa: BLE001 - never let one sweep kill the loop
                _log.exception("Poll sweep failed")
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._pool is not None:
            self._pool.stop()
        self._container.close()
        _log.info("Device Broker stopped")
