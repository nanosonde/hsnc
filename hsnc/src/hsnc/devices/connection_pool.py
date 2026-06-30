"""The device connection pool.

Keeps one persistent (SSH) connection open to every configured device
**at all times**, each supervised by its own thread so a fault on one device
never affects another. When a connection drops, only that device's supervisor
reconnects, using exponential backoff. This is what lets the web app stay fast:
connections live here, warm and ready, instead of being opened inside a request.

The pool does not execute device commands itself — adapters do, reusing the warm
runners via the :class:`~.ssh_transport.PersistentRunnerRegistry`. The pool's job
is purely to *establish and maintain* the connections and report their health.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from ..entities import Device

_log = logging.getLogger("hsnc.devices.pool")


class SupervisedRunner(Protocol):
    """The subset of a persistent runner the pool supervises."""

    def ensure_connected(self) -> None: ...

    def keepalive(self) -> bool: ...

    def close(self) -> None: ...


#: Maps a device to the persistent runner that owns its connection.
RunnerFor = Callable[[Device], SupervisedRunner]


@dataclass
class ConnectionState:
    """Live health of a single device connection (exposed via ``/health``)."""

    device_id: str
    name: str
    connected: bool = False
    failures: int = 0
    last_error: str = ""
    last_change: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class ConnectionPool:
    """Maintains warm SSH connections to all devices, one thread each."""

    def __init__(
        self,
        runner_for: RunnerFor,
        devices_provider: Callable[[], list[Device]],
        *,
        keepalive_interval: float = 30.0,
        backoff_initial: float = 1.0,
        backoff_max: float = 60.0,
    ) -> None:
        self._runner_for = runner_for
        self._devices_provider = devices_provider
        self._keepalive_interval = keepalive_interval
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._states: dict[str, ConnectionState] = {}
        self._states_lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Spawn one supervisor thread per configured device."""
        for device in self._devices_provider():
            state = ConnectionState(device_id=device.id, name=device.name)
            with self._states_lock:
                self._states[device.id] = state
            thread = threading.Thread(
                target=self._supervise,
                args=(device, state),
                name=f"conn-{device.id}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        _log.info("Connection pool started for %d device(s)", len(self._threads))

    def stop(self, timeout: float = 5.0) -> None:
        """Signal all supervisors to stop and close their connections."""
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()
        _log.info("Connection pool stopped")

    # -- introspection ----------------------------------------------------

    def snapshot(self) -> list[dict]:
        """Return a JSON-serialisable view of every connection's health."""
        with self._states_lock:
            return [
                {
                    "device_id": s.device_id,
                    "name": s.name,
                    "connected": s.connected,
                    "failures": s.failures,
                    "last_error": s.last_error,
                    "last_change": s.last_change,
                }
                for s in self._states.values()
            ]

    # -- supervisor -------------------------------------------------------

    def _supervise(self, device: Device, state: ConnectionState) -> None:
        """Keep one device's connection alive until asked to stop."""
        runner = self._runner_for(device)
        backoff = self._backoff_initial
        while not self._stop.is_set():
            try:
                if state.connected:
                    healthy = runner.keepalive()
                else:
                    runner.ensure_connected()
                    healthy = True
            except Exception as exc:  # noqa: BLE001 - isolate per-device faults
                healthy = False
                self._mark(state, connected=False, error=str(exc))
            else:
                if healthy:
                    if not state.connected:
                        _log.info("Connected to %s", device.id)
                    self._mark(state, connected=True, error="")
                    backoff = self._backoff_initial
                else:
                    self._mark(state, connected=False, error="keepalive failed")

            if healthy:
                self._stop.wait(self._keepalive_interval)
            else:
                _log.warning(
                    "Device %s unreachable (%s); retrying in %.0fs",
                    device.id,
                    state.last_error or "unknown",
                    backoff,
                )
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._backoff_max)

        try:
            runner.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    def _mark(self, state: ConnectionState, *, connected: bool, error: str) -> None:
        with self._states_lock:
            if state.connected != connected:
                state.last_change = datetime.now(UTC).isoformat()
            state.connected = connected
            state.last_error = error
            if not connected:
                state.failures += 1
