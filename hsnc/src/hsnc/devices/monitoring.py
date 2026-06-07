"""Monitoring providers — the runtime/monitoring plane.

Separated from the SSH *configuration* adapters so runtime data can come from a
different source than SSH. Each platform owns its providers:

* OpenWrt — :class:`~hsnc.devices.openwrt.ssh_monitoring.OpenWrtSshMonitoringProvider`
  (primary, ``ubus`` over SSH) and
  :class:`~hsnc.devices.openwrt.prometheus_monitoring.OpenWrtPrometheusMonitoringProvider`
  (secondary, Prometheus node-exporter).
* JetStream — :class:`~hsnc.devices.jetstream.ssh_monitoring.JetStreamSshMonitoringProvider`
  (primary, SSH CLI) and
  :class:`~hsnc.devices.jetstream.snmp_monitoring.JetStreamSnmpMonitoringProvider`
  (secondary, SNMPv3).

:class:`DefaultMonitoringProviderFactory` picks the provider per device from the
device's ``monitoring.source`` (primary / secondary / none). When no monitoring
source is available, :class:`NullMonitoringProvider` reports the device as
``DeviceStatus.UNKNOWN`` with no clients rather than inventing data.
"""

from __future__ import annotations

from dataclasses import replace

from ..entities import Client, Device
from ..enums import ConnectionType, DeviceKind, DeviceStatus
from ..interfaces import MonitoringProvider, MonitoringProviderFactory
from ..value_objects import DataVolume, IpAddress, MacAddress, Throughput
from .jetstream.ssh_monitoring import JetStreamSshMonitoringProvider
from .openwrt.ssh_monitoring import OpenWrtSshMonitoringProvider
from .ssh_transport import (
    RunnerFactory,
    SshConnectionResolver,
    default_runner_factory,
)


class NullMonitoringProvider(MonitoringProvider):
    """No monitoring source: report reachability as unknown, no clients.

    Used for devices whose monitoring backend (e.g. SNMPv3) is not yet
    implemented, so the UI honestly shows "unknown" instead of fabricated data.
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
    """Routes devices to a monitoring provider.

    In mock mode every device uses :class:`MockMonitoringProvider`. Otherwise the
    provider is selected by device kind: OpenWrt (gateway/AP) and JetStream
    (switch) currently fall back to SSH scraping. Unknown kinds get the
    :class:`NullMonitoringProvider` (reports ``UNKNOWN``) until a real provider
    (Prometheus / SNMPv3) is wired in.
    """

    def __init__(
        self,
        use_mock: bool = True,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._use_mock = use_mock
        self._mock = MockMonitoringProvider()
        self._null = NullMonitoringProvider()
        resolver = resolver or SshConnectionResolver()
        self._openwrt = OpenWrtSshMonitoringProvider(
            resolver=resolver, runner_factory=runner_factory
        )
        self._jetstream = JetStreamSshMonitoringProvider(
            resolver=resolver, runner_factory=runner_factory
        )

    def for_device(self, device: Device) -> MonitoringProvider:
        if self._use_mock:
            return self._mock
        if device.kind is DeviceKind.SWITCH:
            return self._jetstream
        if device.kind in (DeviceKind.GATEWAY, DeviceKind.ACCESS_POINT):
            return self._openwrt
        return self._null
