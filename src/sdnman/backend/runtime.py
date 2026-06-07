"""Background lifecycle for the REST backend process.

Mirrors the old Device Broker's non-IPC duties inside the API process: keep a
persistent SSH connection warm to every device, read the baseline once on boot
(when enabled), and run a periodic poll loop that scrapes live state into the
runtime store. In mock mode no real connections are opened.

Started from the gunicorn worker (single worker) so the warm runners, the poll
loop and the request handlers all share one container.
"""

from __future__ import annotations

import logging
import threading

from ..infrastructure.container import Container
from ..infrastructure.devices.connection_pool import ConnectionPool

_log = logging.getLogger("sdnman.backend")


class BackendRuntime:
    """Owns the connection pool and poll loop for one backend process."""

    def __init__(self, container: Container) -> None:
        self._container = container
        self._settings = container.settings
        self._stop = threading.Event()
        self._pool: ConnectionPool | None = None
        self._poll_thread: threading.Thread | None = None

        if not self._settings.use_mock_devices:
            registry = container.runner_registry
            resolver = container.ssh_resolver
            assert registry is not None and resolver is not None
            self._pool = ConnectionPool(
                runner_for=lambda device: registry.get(resolver.resolve(device)),
                devices_provider=container.profiles.list_devices,
            )

    @property
    def pool(self) -> ConnectionPool | None:
        return self._pool

    def start(self) -> None:
        if self._pool is not None:
            self._pool.start()
        if self._settings.baseline_on_start:
            self._read_baseline()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="backend-poll", daemon=True
        )
        self._poll_thread.start()
        _log.info("Backend runtime started (mock=%s)", self._settings.use_mock_devices)

    def _read_baseline(self) -> None:
        try:
            result = self._container.read_baseline.execute()
            seeded = self._container.seed_desired_from_current()
            _log.info(
                "Baseline: read %d device(s), %d failure(s), changed=%s, seeded_desired=%s",
                len(result.read),
                len(result.failures),
                result.changed,
                seeded,
            )
        except Exception:  # noqa: BLE001 - never let a bad baseline kill startup
            _log.exception("Baseline read failed")

    def _poll_loop(self) -> None:
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
        if self._pool is not None:
            self._pool.stop()
        self._container.close()
        _log.info("Backend runtime stopped")
