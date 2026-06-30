"""Monitoring providers — the runtime/monitoring plane.

Separated from the SSH *configuration* adapters: the monitoring plane never uses
SSH. The transport is fixed by platform:

* OpenWrt gateways/APs —
  :class:`~hsnc.devices.openwrt.prometheus_monitoring.OpenWrtPrometheusMonitoringProvider`
  (Prometheus node-exporter).
* JetStream switches —
  :class:`~hsnc.devices.jetstream.snmp_monitoring.JetStreamSnmpMonitoringProvider`
  (SNMPv3).

:class:`DefaultMonitoringProviderFactory` picks the provider per device by kind.
A device with ``monitoring.enabled: false`` (or no usable transport) gets
:class:`NullMonitoringProvider`, which reports ``DeviceStatus.UNKNOWN`` with no
clients rather than inventing data.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ..entities import Client, Device
from ..enums import ConnectionType, DeviceKind, DeviceStatus
from ..interfaces import MonitoringProvider, MonitoringProviderFactory
from ..value_objects import DataVolume, IpAddress, MacAddress, Throughput
from .jetstream.snmp_monitoring import (
    JetStreamSnmpMonitoringProvider,
    SnmpConnectionSettings,
)
from .openwrt.prometheus_monitoring import (
    OpenWrtPrometheusMonitoringProvider,
    PrometheusSettings,
)

_logger = logging.getLogger(__name__)


class NullMonitoringProvider(MonitoringProvider):
    """No monitoring source: report reachability as unknown, no clients.

    Used for devices with ``monitoring.enabled: false`` and for devices whose
    platform has no monitoring transport, so the UI honestly shows "unknown"
    instead of fabricated data.
    """

    def fetch_status(self, device: Device) -> Device:
        return replace(device, status=DeviceStatus.UNKNOWN)

    def fetch_clients(self, device: Device) -> list[Client]:
        return []


# Demo clients keyed by the device they are attached to. Mirrors the
# "All (6)" wired-clients list from the reference screenshot.
_DEMO_CLIENTS: dict[str, list[dict]] = {
    "switch-1": [
        {"id": "c1", "name": "D4-5D", "mac": "D4:5D:64:11:22:33",
         "ip": "192.168.50.1", "uptime": 1618},
        {"id": "c2", "name": "DESKTOP-5DO0R", "mac": "AC:1F:6B:00:00:01",
         "ip": None, "uptime": 1588},
        {"id": "c3", "name": "Galaxy-A51-dl-Lac", "mac": "AC:1F:6B:00:00:02",
         "ip": None, "uptime": 372},
        {"id": "c4", "name": "IsiPhone", "mac": "AC:1F:6B:00:00:03",
         "ip": None, "uptime": 1277},
        {"id": "c5", "name": "OC200_E491B4", "mac": "B0:4E:26:E4:91:B4",
         "ip": "192.168.50.197", "uptime": 1591},
        {"id": "c6", "name": "Sweeper", "mac": "AC:1F:6B:00:00:05",
         "ip": None, "uptime": 1609},
    ],
}

# Live status overrides applied on top of the declarative device definition.
_DEMO_STATUS: dict[str, dict] = {
    "gateway-1": {"status": DeviceStatus.DISCONNECTED, "uptime": 0},
    "switch-1": {"status": DeviceStatus.CONNECTED, "uptime": 1602},
    "ap-1": {"status": DeviceStatus.CONNECTED, "uptime": 1600},
}


class MockMonitoringProvider(MonitoringProvider):
    """Returns canned-but-plausible runtime data for any device."""

    def fetch_status(self, device: Device) -> Device:
        override = _DEMO_STATUS.get(device.id)
        if override:
            device.status = override["status"]
            device.uptime_seconds = override["uptime"]
        else:
            device.status = DeviceStatus.CONNECTED
        return device

    def fetch_clients(self, device: Device) -> list[Client]:
        clients: list[Client] = []
        for spec in _DEMO_CLIENTS.get(device.id, []):
            clients.append(
                Client(
                    id=spec["id"],
                    name=spec["name"],
                    mac=MacAddress(spec["mac"]),
                    connection=ConnectionType.WIRED,
                    status=DeviceStatus.CONNECTED,
                    ip=IpAddress(spec["ip"]) if spec["ip"] else None,
                    network="LAN",
                    ssid="",
                    ap_or_port=device.name,
                    activity=Throughput(0),
                    downloaded=DataVolume(0),
                    uploaded=DataVolume(0),
                    uptime_seconds=spec["uptime"],
                    site_id=device.site_id,
                )
            )
        return clients


class DefaultMonitoringProviderFactory(MonitoringProviderFactory):
    """Routes devices to a monitoring provider by platform/kind.

    The monitoring plane never uses SSH. In mock mode every device uses
    :class:`MockMonitoringProvider`. Otherwise:

    * ``monitoring.enabled == False`` -> :class:`NullMonitoringProvider`.
    * switch -> :class:`JetStreamSnmpMonitoringProvider` (SNMPv3).
    * gateway / access point -> :class:`OpenWrtPrometheusMonitoringProvider`
      (Prometheus node-exporter).
    * any other kind -> :class:`NullMonitoringProvider` (reports ``UNKNOWN``).

    An unreachable or misconfigured endpoint reports ``UNKNOWN`` rather than
    masking the problem; there is no SSH fallback.
    """

    def __init__(
        self,
        use_mock: bool = True,
        prometheus_settings: PrometheusSettings | None = None,
        snmp_settings: SnmpConnectionSettings | None = None,
    ) -> None:
        self._use_mock = use_mock
        self._mock = MockMonitoringProvider()
        self._null = NullMonitoringProvider()
        self._openwrt_prometheus = OpenWrtPrometheusMonitoringProvider(
            settings=prometheus_settings or PrometheusSettings.from_env()
        )
        self._jetstream_snmp = JetStreamSnmpMonitoringProvider(
            settings=snmp_settings or SnmpConnectionSettings.from_env()
        )

    def for_device(self, device: Device) -> MonitoringProvider:
        if self._use_mock:
            return self._mock
        if device.monitoring is not None and not device.monitoring.enabled:
            return self._null
        if device.kind is DeviceKind.SWITCH:
            return self._jetstream_snmp
        if device.kind in (DeviceKind.GATEWAY, DeviceKind.ACCESS_POINT):
            return self._openwrt_prometheus
        _logger.warning(
            "device %r has kind %r with no monitoring transport; reporting UNKNOWN",
            device.id,
            device.kind,
        )
        return self._null
