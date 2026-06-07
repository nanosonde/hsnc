"""Adapter factory selecting the right :class:`DeviceAdapter` per device.

With ``use_mock=True`` every device is handled by the in-memory mock adapter.
With ``use_mock=False`` devices are routed by kind to the real OpenWrt and
JetStream SSH adapters, without any change to inner-layer code.
"""

from __future__ import annotations

from ..entities import Device
from ..enums import DeviceKind
from ..interfaces import DeviceAdapter, DeviceAdapterFactory
from .jetstream_cli_adapter import JetStreamCliAdapter
from .mock_adapter import MockDeviceAdapter
from .openwrt_ssh_adapter import OpenWrtSshAdapter
from .ssh_transport import (
    RunnerFactory,
    SshConnectionResolver,
    default_runner_factory,
)


class DefaultDeviceAdapterFactory(DeviceAdapterFactory):
    """Routes devices to mock or real adapters based on configuration."""

    def __init__(
        self,
        use_mock: bool = True,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._use_mock = use_mock
        self._mock = MockDeviceAdapter()
        resolver = resolver or SshConnectionResolver()
        self._openwrt = OpenWrtSshAdapter(resolver=resolver, runner_factory=runner_factory)
        self._jetstream = JetStreamCliAdapter(resolver=resolver, runner_factory=runner_factory)

    def for_device(self, device: Device) -> DeviceAdapter:
        if self._use_mock:
            return self._mock
        if device.kind is DeviceKind.SWITCH:
            return self._jetstream
        if device.kind in (DeviceKind.GATEWAY, DeviceKind.ACCESS_POINT):
            return self._openwrt
        raise ValueError(f"No adapter available for device kind: {device.kind}")
