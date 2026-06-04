"""Shared application service for assembling live network state.

Several use cases need the same enriched view (config devices + live status +
associated clients). This service centralises that orchestration so use cases
stay small and free of duplication.
"""

from __future__ import annotations

from ..domain.entities import Client, Device
from ..domain.interfaces import ConfigRepository, DeviceAdapterFactory


class NetworkStateService:
    """Combines declarative config with live adapter data."""

    def __init__(self, config: ConfigRepository, adapters: DeviceAdapterFactory) -> None:
        self._config = config
        self._adapters = adapters

    def devices(self) -> list[Device]:
        enriched: list[Device] = []
        for device in self._config.list_devices():
            adapter = self._adapters.for_device(device)
            enriched.append(adapter.fetch_status(device))
        return enriched

    def clients(self) -> list[Client]:
        result: list[Client] = []
        for device in self._config.list_devices():
            adapter = self._adapters.for_device(device)
            result.extend(adapter.fetch_clients(device))
        return result

    def clients_for(self, device: Device) -> list[Client]:
        adapter = self._adapters.for_device(device)
        return adapter.fetch_clients(device)
