"""JetStream runtime monitoring over the SSH CLI — the primary polling source.

Scrapes live runtime state for TP-Link JetStream switches through one interactive
shell session (these switches reject one-shot ``exec`` channels). This is the
*primary* monitoring connection; the SNMPv3 provider
(:mod:`.snmp_monitoring`) is the optional *secondary* source.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ...entities import Client, Device
from ...enums import ConnectionType, DeviceStatus
from ...interfaces import MonitoringProvider
from ...value_objects import MacAddress
from ..ssh_transport import (
    RunnerFactory,
    SshCommandRunner,
    SshConnectionResolver,
    default_runner_factory,
)

_MAC_TABLE_RE = re.compile(
    r"^([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})\s+(\d+)\s+(\S+)", re.MULTILINE
)
_UPTIME_RE = re.compile(
    r"(?:(\d+)\s*days?)?\s*(\d{1,2}):(\d{2}):(\d{2})", re.IGNORECASE
)


class JetStreamSshMonitoringProvider(MonitoringProvider):
    """Scrapes JetStream runtime state over the SSH CLI as the primary source."""

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
