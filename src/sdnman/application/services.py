"""Shared application service for assembling live network state.

Several use cases need the same enriched view (config devices + live status +
associated clients). This service centralises that orchestration so use cases
stay small and free of duplication.

Runtime data is read through the monitoring plane
(:class:`MonitoringProviderFactory`), kept separate from the SSH configuration
plane. Each device is polled in isolation: if its monitoring source is
unreachable the device is reported as ``DeviceStatus.UNKNOWN`` and the sweep
continues, so one bad device never blanks the whole view.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ..domain.entities import Client, Device
from ..domain.enums import DeviceStatus
from ..domain.interfaces import ConfigRepository, MonitoringProviderFactory

_log = logging.getLogger(__name__)


class NetworkStateService:
    """Combines declarative config with live monitoring data."""

    def __init__(
        self, config: ConfigRepository, monitoring: MonitoringProviderFactory
    ) -> None:
        self._config = config
        self._monitoring = monitoring

    def devices(self) -> list[Device]:
        enriched: list[Device] = []
        for device in self._config.list_devices():
            provider = self._monitoring.for_device(device)
            try:
                enriched.append(provider.fetch_status(device))
            except Exception:  # noqa: BLE001 - isolate one unreachable device
                _log.warning("Monitoring fetch_status failed for %s", device.id, exc_info=True)
                enriched.append(replace(device, status=DeviceStatus.UNKNOWN))
        return enriched

    def clients(self) -> list[Client]:
        result: list[Client] = []
        for device in self._config.list_devices():
            result.extend(self.clients_for(device))
        return result

    def clients_for(self, device: Device) -> list[Client]:
        provider = self._monitoring.for_device(device)
        try:
            return provider.fetch_clients(device)
        except Exception:  # noqa: BLE001 - isolate one unreachable device
            _log.warning("Monitoring fetch_clients failed for %s", device.id, exc_info=True)
            return []
