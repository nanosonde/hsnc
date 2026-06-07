"""Monitoring providers — the runtime/monitoring plane.

Separated from the SSH *configuration* adapters so runtime data can come from a
different source than SSH. Today the SSH-scraping providers are the fallback
(OpenWrt ``ubus`` and JetStream CLI); future providers (OpenWrt Prometheus
exporter, SNMPv3 for switches) can slot into :class:`DefaultMonitoringProviderFactory`
without touching the configuration plane.

When no monitoring source is available for a device, :class:`NullMonitoringProvider`
reports it as ``DeviceStatus.UNKNOWN`` with no clients rather than inventing data.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace

from ...domain.entities import Client, Device
from ...domain.enums import ConnectionType, DeviceKind, DeviceStatus
from ...domain.interfaces import MonitoringProvider, MonitoringProviderFactory
from ...domain.value_objects import DataVolume, IpAddress, MacAddress, Throughput
from .ssh_transport import (
    RunnerFactory,
    SshCommandRunner,
    SshConnectionResolver,
    SshError,
    default_runner_factory,
)

_MAC_TABLE_RE = re.compile(
    r"^([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})\s+(\d+)\s+(\S+)", re.MULTILINE
)
_UPTIME_RE = re.compile(
    r"(?:(\d+)\s*days?)?\s*(\d{1,2}):(\d{2}):(\d{2})", re.IGNORECASE
)


class OpenWrtSshMonitoringProvider(MonitoringProvider):
    """Scrapes OpenWrt runtime state over SSH (``ubus``) as the fallback source.

    DHCP leases come from the ``dhcp`` ubus object when present (odhcpd) and fall
    back to the dnsmasq lease file (``/tmp/dhcp.leases``) otherwise.
    """

    def __init__(
        self,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._resolver = resolver or SshConnectionResolver()
        self._runner_factory = runner_factory

    def _runner(self, device: Device) -> SshCommandRunner:
        return self._runner_factory(self._resolver.resolve(device))

    def fetch_status(self, device: Device) -> Device:
        runner = self._runner(device)
        with runner:
            board = json.loads(runner.run("ubus call system board"))
            try:
                lan = json.loads(runner.run("ubus call network.interface.lan status"))
            except Exception:  # noqa: BLE001 - lan iface may be absent
                lan = {}
        release = board.get("release", {}) or {}
        firmware = release.get("version") or device.firmware
        return replace(
            device,
            status=DeviceStatus.CONNECTED,
            model=board.get("model") or device.model,
            firmware=firmware,
            uptime_seconds=int(lan.get("uptime", device.uptime_seconds) or 0),
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        runner = self._runner(device)
        with runner:
            try:
                raw = runner.run("ubus call dhcp ipv4leases")
            except SshError:
                # Devices that serve DHCP via dnsmasq have no odhcpd ``dhcp``
                # ubus object, so fall back to parsing the dnsmasq lease file.
                return self._clients_from_lease_file(
                    device, runner.run("cat /tmp/dhcp.leases")
                )
        return self._clients_from_ubus(device, raw)

    @staticmethod
    def _clients_from_ubus(device: Device, raw: str) -> list[Client]:
        data = json.loads(raw) if raw.strip() else {}
        clients: list[Client] = []
        for bridge in (data.get("device") or {}).values():
            for lease in bridge.get("ipv4-leases", []) or []:
                mac = lease.get("mac")
                address = lease.get("address")
                if not mac:
                    continue
                hostname = lease.get("hostname") or mac
                clients.append(
                    Client(
                        id=f"{device.id}-{MacAddress(mac)}",
                        name=hostname,
                        mac=MacAddress(mac),
                        connection=ConnectionType.WIRED,
                        status=DeviceStatus.CONNECTED,
                        ip=IpAddress(address) if address else None,
                        ap_or_port=device.name,
                        site_id=device.site_id,
                    )
                )
        return clients

    @staticmethod
    def _clients_from_lease_file(device: Device, raw: str) -> list[Client]:
        # dnsmasq lease line: "<expiry> <mac> <ip> <hostname> <client-id>".
        clients: list[Client] = []
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            mac, address, hostname = parts[1], parts[2], parts[3]
            if mac.count(":") != 5:
                continue
            mac_obj = MacAddress(mac)
            name = hostname if hostname not in ("", "*") else str(mac_obj)
            clients.append(
                Client(
                    id=f"{device.id}-{mac_obj}",
                    name=name,
                    mac=mac_obj,
                    connection=ConnectionType.WIRED,
                    status=DeviceStatus.CONNECTED,
                    ip=IpAddress(address) if address not in ("", "*") else None,
                    ap_or_port=device.name,
                    site_id=device.site_id,
                )
            )
        return clients


class JetStreamSshMonitoringProvider(MonitoringProvider):
    """Scrapes JetStream runtime state over the SSH CLI as the fallback source.

    Replace with an SNMPv3 provider once implemented; until then this keeps the
    switch's runtime data populated.
    """

    def __init__(
        self,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._resolver = resolver or SshConnectionResolver()
        self._runner_factory = runner_factory

    def _runner(self, device: Device) -> SshCommandRunner:
        return self._runner_factory(self._resolver.resolve(device))

    def fetch_status(self, device: Device) -> Device:
        runner = self._runner(device)
        with runner:
            # JetStream switches reject SSH ``exec`` channels, so reads go
            # through one interactive shell session.
            raw = runner.run_shell(["show system-info"])
        info = self._parse_key_values(raw)
        mac = info.get("MAC Address")
        return replace(
            device,
            status=DeviceStatus.CONNECTED,
            name=info.get("Device Name", device.name),
            model=info.get("Device Model", device.model),
            firmware=info.get("Software Version", device.firmware),
            mac=MacAddress(mac) if mac else device.mac,
            uptime_seconds=self._parse_uptime(info.get("Running Time", "")),
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        runner = self._runner(device)
        with runner:
            # JetStream switches reject SSH ``exec`` channels, so reads go
            # through one interactive shell session.
            raw = runner.run_shell(["show mac address-table"])
        clients: list[Client] = []
        for mac, _vlan, port in _MAC_TABLE_RE.findall(raw):
            clients.append(
                Client(
                    id=f"{device.id}-{MacAddress(mac)}",
                    name=str(MacAddress(mac)),
                    mac=MacAddress(mac),
                    connection=ConnectionType.WIRED,
                    status=DeviceStatus.CONNECTED,
                    ap_or_port=port,
                    site_id=device.site_id,
                )
            )
        return clients

    @staticmethod
    def _parse_key_values(raw: str) -> dict[str, str]:
        info: dict[str, str] = {}
        for line in raw.splitlines():
            if " - " in line:
                key, _, value = line.partition(" - ")
                info[key.strip()] = value.strip()
        return info

    @staticmethod
    def _parse_uptime(text: str) -> int:
        match = _UPTIME_RE.search(text)
        if not match:
            return 0
        days, hours, minutes, seconds = match.groups()
        return (
            int(days or 0) * 86400
            + int(hours) * 3600
            + int(minutes) * 60
            + int(seconds)
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
