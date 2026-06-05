"""Use case: poll all devices and persist a runtime snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ...domain.entities import AssociationFailure
from ...domain.interfaces import RuntimeStore
from ..services import NetworkStateService

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PollDeviceState:
    """Fetch live state from every device and record it in the runtime store."""

    def __init__(
        self,
        network: NetworkStateService,
        runtime: RuntimeStore,
        retention_days: int = 30,
        clock: Clock = _utcnow,
    ) -> None:
        self._network = network
        self._runtime = runtime
        self._retention_days = retention_days
        self._clock = clock

    def execute(self) -> int:
        """Record one runtime snapshot, prune old rows, return devices polled."""

        now = self._clock()
        devices = self._network.devices()
        for device in devices:
            self._runtime.record_device_status(device, now)
            for client in self._network.clients_for(device):
                self._runtime.record_client_session(client, now, device.id)

        # Association failures are currently derived as empty buckets; real
        # adapters will surface counts. Persist the buckets so history exists.
        failures = [
            AssociationFailure("Association Timeout", 0),
            AssociationFailure("Blocked by Access Control", 0),
            AssociationFailure("WPA Authentication Timeout/Failure", 0),
        ]
        self._runtime.record_association_failures(failures, now)

        # Bound time-series growth: drop rows older than the retention window.
        if self._retention_days > 0:
            self._runtime.prune(now - timedelta(days=self._retention_days))
        return len(devices)
