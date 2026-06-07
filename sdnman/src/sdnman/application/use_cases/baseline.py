"""Use case: establish the configuration baseline from the live devices.

On controller start (when enabled) the Device Broker reads the configuration
currently running on every device. That snapshot becomes the *baseline* —
``current_config.json`` — against which staged (desired) changes are diffed, and
the read is recorded in the apply history as an ``action="baseline"`` event so
the starting point is visible and survives restarts.

The read is performed through whatever :class:`DeviceAdapterFactory` the process
is wired with: in the web/oneshot process that is the broker proxy, so even the
baseline read goes through the broker's warm connections rather than opening new
ones. A device that cannot be read is skipped (its previous baseline is kept)
instead of failing the whole run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...domain.entities import ApplyEvent, ApplyOutcome, Device
from ...domain.interfaces import (
    AppliedConfigStore,
    ApplyHistoryStore,
    ConfigRepository,
    DeviceAdapterFactory,
)


def _config_signature(device: Device) -> tuple:
    """A comparable view of just a device's *configuration* (not live state)."""
    return (
        str(device.mac) if device.mac else "",
        device.model,
        device.firmware,
        tuple(
            (p.number, p.name, p.enabled, p.mode.value, p.pvid, tuple(p.tagged_vlans))
            for p in device.ports
        ),
        tuple((v.vlan_id, v.name, v.subnet) for v in device.vlans),
        tuple(device.ssids),
    )


@dataclass
class BaselineResult:
    """Outcome of a baseline run."""

    read: list[Device] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    changed: bool = False
    recorded: bool = False


class ReadBaseline:
    """Reads live configuration from all devices and records it as the baseline."""

    def __init__(
        self,
        config: ConfigRepository,
        adapters: DeviceAdapterFactory,
        current: AppliedConfigStore,
        history: ApplyHistoryStore,
        username: str = "system",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._adapters = adapters
        self._current = current
        self._history = history
        self._username = username
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self) -> BaselineResult:
        result = BaselineResult()
        existing = {d.id: d for d in self._current.load()}
        # Start from the previous baseline so unreadable devices keep their state.
        merged: dict[str, Device] = dict(existing)
        outcomes: list[ApplyOutcome] = []

        for device in self._config.list_devices():
            adapter = self._adapters.for_device(device)
            try:
                read = adapter.fetch_config(device)
            except Exception as exc:  # noqa: BLE001 - per-device isolation
                result.failures.append(device.id)
                outcomes.append(
                    ApplyOutcome(device.id, device.name, ok=False, message=str(exc))
                )
                continue
            result.read.append(read)
            outcomes.append(ApplyOutcome(device.id, device.name, ok=True, message="read"))
            if device.id not in existing or _config_signature(read) != _config_signature(
                existing[device.id]
            ):
                result.changed = True
            merged[device.id] = read

        if result.changed:
            self._current.save(list(merged.values()))
            self._history.record_apply_event(
                ApplyEvent(
                    applied_at=self._clock(),
                    username=self._username,
                    ok=not result.failures,
                    outcomes=outcomes,
                    action="baseline",
                )
            )
            result.recorded = True
        return result
