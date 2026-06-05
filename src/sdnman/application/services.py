"""Shared application service for assembling live network state.

Several use cases need the same enriched view (config devices + live status +
associated clients). This service centralises that orchestration so use cases
stay small and free of duplication.

Runtime data is read through the monitoring plane
(:class:`MonitoringProviderFactory`), kept separate from the SSH configuration
plane. Each device is polled in isolation: if its monitoring source is
unreachable the device is reported as ``DeviceStatus.UNKNOWN`` and the sweep
continues, so one bad device never blanks the whole view.

Live scrapes are expensive (an SSH round-trip per device, and a full connect
timeout for an unreachable one), so results are cached for a short TTL. Repeated
page loads within the window reuse the last scrape instead of re-connecting, and
a failed/unreachable device is not re-probed on every request. A TTL of ``0``
disables caching (the default, so unit tests stay deterministic).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from ..domain.entities import Client, Device
from ..domain.enums import DeviceStatus
from ..domain.interfaces import ConfigRepository, MonitoringProviderFactory

_log = logging.getLogger(__name__)


class NetworkStateService:
    """Combines declarative config with live monitoring data."""

    def __init__(
        self,
        config: ConfigRepository,
        monitoring: MonitoringProviderFactory,
        cache_ttl_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._monitoring = monitoring
        self._ttl = cache_ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._status_cache: dict[str, tuple[float, Device]] = {}
        self._clients_cache: dict[str, tuple[float, list[Client]]] = {}

    def devices(self) -> list[Device]:
        return [self._status_for(device) for device in self._config.list_devices()]

    def clients(self) -> list[Client]:
        result: list[Client] = []
        for device in self._config.list_devices():
            result.extend(self.clients_for(device))
        return result

    def clients_for(self, device: Device) -> list[Client]:
        cached = self._cache_get(self._clients_cache, device.id)
        if cached is not None:
            return cached
        provider = self._monitoring.for_device(device)
        try:
            clients = provider.fetch_clients(device)
        except Exception as exc:  # noqa: BLE001 - isolate one unreachable device
            _log.warning("Monitoring fetch_clients failed for %s: %s", device.id, exc)
            clients = []
        self._cache_put(self._clients_cache, device.id, clients)
        return clients

    def _status_for(self, device: Device) -> Device:
        cached = self._cache_get(self._status_cache, device.id)
        if cached is not None:
            return cached
        provider = self._monitoring.for_device(device)
        try:
            enriched = provider.fetch_status(device)
        except Exception as exc:  # noqa: BLE001 - isolate one unreachable device
            _log.warning("Monitoring fetch_status failed for %s: %s", device.id, exc)
            enriched = replace(device, status=DeviceStatus.UNKNOWN)
        self._cache_put(self._status_cache, device.id, enriched)
        return enriched

    # -- TTL cache helpers ---------------------------------------------------
    def _cache_get(self, cache: dict, key: str):
        if self._ttl <= 0:
            return None
        with self._lock:
            entry = cache.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at >= self._ttl:
                cache.pop(key, None)
                return None
            return value

    def _cache_put(self, cache: dict, key: str, value) -> None:
        if self._ttl <= 0:
            return
        with self._lock:
            cache[key] = (self._clock(), value)
