"""The device connection manager.

SSH is the configuration plane only, so connections are **demand-driven**: a
device's connection is opened lazily on the first config command (by the warm
runner in :class:`~.ssh_transport.PersistentRunnerRegistry`), then kept warm for
repeat config requests and gracefully closed once it has been idle past the
configured window. Each device is supervised by its own thread so a fault on one
device never affects another.

The manager does not open or execute device commands itself — adapters do that,
lazily, when a config requirement arrives. The manager's job is to keep an
already-open connection warm (periodic keepalive) and to reap it once idle,
reporting connection health for ``/health``.
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
    """The subset of a persistent runner the manager supervises.

    The manager never opens a connection itself: it only keeps an already-open
    one warm (:meth:`keepalive`) and closes it once idle (:meth:`close_idle`).
    """

    def is_alive(self) -> bool: ...

    def idle_seconds(self) -> float: ...

    def keepalive(self) -> bool: ...

    def close_idle(self) -> None: ...

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
    """Keeps demand-opened SSH connections warm and reaps idle ones, one thread each."""

    def __init__(
        self,
        runner_for: RunnerFor,
        devices_provider: Callable[[], list[Device]],
        *,
        idle_timeout: float = 300.0,
        keepalive_interval: float = 30.0,
    ) -> None:
        self._runner_for = runner_for
        self._devices_provider = devices_provider
        self._idle_timeout = idle_timeout
        # Scan at least as often as the idle window so a connection is reaped
        # promptly once idle, even when the window is shorter than a keepalive.
        self._scan_interval = max(0.01, min(keepalive_interval, idle_timeout))
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
        """Keep one device's connection warm and reap it once idle.

        The connection is opened on demand by the adapter on the first config
        command, not here. While it is open this thread keepalives it so the
        link stays warm for repeat requests, and closes it gracefully once it
        has been idle past the configured window.
        """
        runner = self._runner_for(device)
        while not self._stop.is_set():
            try:
                if runner.is_alive():
                    if runner.idle_seconds() >= self._idle_timeout:
                        runner.close_idle()
                        _log.info("Closed idle connection to %s", device.id)
                        self._mark(state, connected=False, error="")
                    elif runner.keepalive():
                        self._mark(state, connected=True, error="")
                    else:
                        self._mark(state, connected=False, error="keepalive failed")
                else:
                    self._mark(state, connected=False, error="")
            except Exception as exc:  # noqa: BLE001 - isolate per-device faults
                self._mark(state, connected=False, error=str(exc))
            self._stop.wait(self._scan_interval)

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
            # Count only genuine faults (a non-empty error); a benign
            # not-yet-connected or graceful idle close is not a failure.
            if error:
                state.failures += 1
