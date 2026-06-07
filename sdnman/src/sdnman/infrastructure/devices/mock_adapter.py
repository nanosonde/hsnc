"""In-memory mock device adapter (configuration plane).

Accepts configuration silently and echoes the declarative device on re-read.
Runtime/monitoring demo data lives in
:class:`~sdnman.infrastructure.devices.monitoring.MockMonitoringProvider`.
Used for tests and for running the app locally without real hardware.
"""

from __future__ import annotations

from ...domain.entities import Device
from ...domain.interfaces import DeviceAdapter


class MockDeviceAdapter(DeviceAdapter):
    """Accepts config for any device and echoes it back on re-read."""

    def supports(self, device: Device) -> bool:  # noqa: D102 - manages all devices
        return True

    def fetch_config(self, device: Device) -> Device:
        # The mock has no separate source of truth, so a re-read simply returns
        # the device unchanged, demonstrating the flow.
        return device

    def push_config(self, device: Device) -> None:
        # Mock adapter accepts config silently; nothing to apply.
        return None
