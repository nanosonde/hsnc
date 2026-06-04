"""Adapter factory selecting the right :class:`DeviceAdapter` per device.

For the MVP every device is handled by the mock adapter. Switching the factory
configuration to ``use_mock=False`` routes devices to the real (stubbed)
OpenWrt/JetStream adapters by device kind, proving the seam without changing any
inner-layer code.
"""

from __future__ import annotations

from ...domain.entities import Device
from ...domain.enums import DeviceKind
from ...domain.interfaces import DeviceAdapter, DeviceAdapterFactory
from .jetstream_cli_adapter import JetStreamCliAdapter
from .mock_adapter import MockDeviceAdapter
from .openwrt_ssh_adapter import OpenWrtSshAdapter


class DefaultDeviceAdapterFactory(DeviceAdapterFactory):
    """Routes devices to mock or real adapters based on configuration."""

    def __init__(self, use_mock: bool = True) -> None:
        self._use_mock = use_mock
        self._mock = MockDeviceAdapter()
        self._openwrt = OpenWrtSshAdapter()
        self._jetstream = JetStreamCliAdapter()

    def for_device(self, device: Device) -> DeviceAdapter:
        if self._use_mock:
            return self._mock
        if device.kind is DeviceKind.SWITCH:
            return self._jetstream
        if device.kind in (DeviceKind.GATEWAY, DeviceKind.ACCESS_POINT):
            return self._openwrt
        raise ValueError(f"No adapter available for device kind: {device.kind}")
