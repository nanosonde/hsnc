"""Monitoring provider that reads the last poll from the runtime store.

This is the web app's monitoring source. The web process must never open a
device connection in a request, so instead of scraping live it reads the most
recent snapshot the poll loop recorded into the runtime database. Pages
therefore render from local SQLite and never block on SSH connects or timeouts.
"""

from __future__ import annotations

from ...domain.entities import Client, Device
from ...domain.interfaces import (
    MonitoringProvider,
    MonitoringProviderFactory,
    RuntimeStore,
)


class RuntimeStoreMonitoringProvider(MonitoringProvider):
    """Serves device status/clients from the latest recorded runtime snapshot."""

    def __init__(self, runtime: RuntimeStore) -> None:
        self._runtime = runtime

    def fetch_status(self, device: Device) -> Device:
        return self._runtime.latest_device_status(device)

    def fetch_clients(self, device: Device) -> list[Client]:
        return self._runtime.latest_clients(device)


class RuntimeStoreMonitoringFactory(MonitoringProviderFactory):
    """Every device is served from the runtime store (no live connections)."""

    def __init__(self, runtime: RuntimeStore) -> None:
        self._provider = RuntimeStoreMonitoringProvider(runtime)

    def for_device(self, device: Device) -> MonitoringProvider:
        return self._provider
