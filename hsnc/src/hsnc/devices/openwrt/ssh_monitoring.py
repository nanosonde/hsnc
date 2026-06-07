"""OpenWrt runtime monitoring over SSH (``ubus``) — the primary polling source.

Scrapes live runtime state for OpenWrt gateways and access points using the same
``ubus`` surface the mock container emulates. DHCP leases come from the ``dhcp``
ubus object when present (odhcpd) and fall back to the dnsmasq lease file
(``/tmp/dhcp.leases``) otherwise.

This is the *primary* monitoring connection. The Prometheus exporter provider
(:mod:`.prometheus_monitoring`) is the optional *secondary* source.
"""

from __future__ import annotations

import json
from dataclasses import replace

from ...entities import Client, Device
from ...enums import ConnectionType, DeviceStatus
from ...interfaces import MonitoringProvider
from ...value_objects import IpAddress, MacAddress
from ..ssh_transport import (
    RunnerFactory,
    SshCommandRunner,
    SshConnectionResolver,
    SshError,
    default_runner_factory,
)


class OpenWrtSshMonitoringProvider(MonitoringProvider):
    """Scrapes OpenWrt runtime state over SSH (``ubus``) as the primary source.

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
