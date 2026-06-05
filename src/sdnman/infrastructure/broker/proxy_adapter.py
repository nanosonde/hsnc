"""Web-side device adapter that proxies to the Device Broker.

In the web process every :class:`DeviceAdapter` operation is delegated to the
broker over the Unix socket — the web app holds no device connections. Reads
(``fetch_config``) and writes (``push_config``) become synchronous IPC calls;
the broker performs the actual SSH work on its warm connection and returns the
result inline, so the apply UI still reflects real success/failure.
"""

from __future__ import annotations

from ...domain.entities import Device
from ...domain.interfaces import DeviceAdapter, DeviceAdapterFactory
from ..config.mapping import device_to_config, merge
from ..config.schemas import DeviceConfigSchema
from .client import BrokerClient


class BrokerProxyDeviceAdapter(DeviceAdapter):
    """Delegates configuration reads/writes to the broker over IPC."""

    def __init__(self, client: BrokerClient) -> None:
        self._client = client

    def supports(self, device: Device) -> bool:
        return True

    def fetch_config(self, device: Device) -> Device:
        payload = self._client.read_config(device.id)
        config = DeviceConfigSchema.model_validate({**payload, "id": device.id})
        return merge(device, config)

    def push_config(self, device: Device) -> None:
        payload = device_to_config(device).model_dump(mode="python")
        self._client.apply_config(device.id, payload)


class BrokerProxyAdapterFactory(DeviceAdapterFactory):
    """Every device is served by the same broker-proxy adapter."""

    def __init__(self, client: BrokerClient) -> None:
        self._adapter = BrokerProxyDeviceAdapter(client)

    def for_device(self, device: Device) -> DeviceAdapter:
        return self._adapter
