"""TP-Link JetStream managed-switch adapter over SSH/CLI.

Talks to JetStream switches using the same CLI surface the mock container
emulates:

* :meth:`fetch_status`  — ``show system-info`` (model / firmware / mac / uptime)
* :meth:`fetch_config`  — ``show running-config`` parsed into VLANs and ports
* :meth:`fetch_clients` — ``show mac address-table``
* :meth:`push_config`   — :class:`JetStreamCliRenderer` commands fed through one
  interactive shell session (config mode is stateful)

Read commands run as a single ``exec`` (``ssh admin@host "show ..."``); the push
uses one interactive shell because entering/exiting config contexts is stateful.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ...domain.entities import Client, Device, SwitchPort, Vlan
from ...domain.enums import ConnectionType, DeviceKind, DeviceStatus, PortMode
from ...domain.interfaces import DeviceAdapter
from ...domain.value_objects import MacAddress
from .config_renderers import JetStreamCliRenderer
from .ssh_transport import (
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


class JetStreamCliAdapter(DeviceAdapter):
    """Manages TP-Link JetStream switches via the SSH command-line interface."""

    def __init__(
        self,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._resolver = resolver or SshConnectionResolver()
        self._runner_factory = runner_factory
        self._renderer = JetStreamCliRenderer()

    def supports(self, device: Device) -> bool:
        return device.kind is DeviceKind.SWITCH

    # -- connection helper ---------------------------------------------------
    def _runner(self, device: Device) -> SshCommandRunner:
        return self._runner_factory(self._resolver.resolve(device))

    # -- reads ---------------------------------------------------------------
    def fetch_status(self, device: Device) -> Device:
        runner = self._runner(device)
        with runner:
            raw = runner.run("show system-info")
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

    def fetch_config(self, device: Device) -> Device:
        runner = self._runner(device)
        with runner:
            raw = runner.run("show running-config")
        hostname, vlans, ports = self._parse_running_config(raw)
        return replace(
            device,
            name=hostname or device.name,
            vlans=vlans or device.vlans,
            ports=ports or device.ports,
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        runner = self._runner(device)
        with runner:
            raw = runner.run("show mac address-table")
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

    # -- writes --------------------------------------------------------------
    def push_config(self, device: Device) -> None:
        runner = self._runner(device)
        with runner:
            runner.run_shell(self._renderer.render(device))

    # -- parsing helpers -----------------------------------------------------
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

    @classmethod
    def _parse_running_config(
        cls, raw: str
    ) -> tuple[str, list[Vlan], list[SwitchPort]]:
        hostname = ""
        vlans: dict[int, Vlan] = {}
        ports: dict[int, SwitchPort] = {}
        current_vlan: int | None = None
        current_port: int | None = None

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "#":
                continue
            words = stripped.split()
            head = words[0].lower()

            if head == "hostname" and len(words) >= 2:
                hostname = words[1]
                current_vlan = current_port = None
            elif head == "vlan" and len(words) >= 2 and words[1].isdigit():
                current_vlan = int(words[1])
                current_port = None
                vlans.setdefault(
                    current_vlan, Vlan(vlan_id=current_vlan, name=f"VLAN{current_vlan}")
                )
            elif head == "name" and current_vlan is not None and len(words) >= 2:
                vlans[current_vlan] = Vlan(vlan_id=current_vlan, name=" ".join(words[1:]))
            elif head == "interface" and len(words) >= 2:
                num = words[-1].split("/")[-1]
                if num.isdigit():
                    current_port = int(num)
                    current_vlan = None
                    ports.setdefault(
                        current_port, SwitchPort(number=current_port, name=f"Gi1/0/{num}")
                    )
            elif head == "switchport" and current_port is not None:
                cls._apply_switchport(ports[current_port], words[1:])
            elif head == "shutdown" and current_port is not None:
                ports[current_port].enabled = False

        return (
            hostname,
            [vlans[v] for v in sorted(vlans)],
            [ports[p] for p in sorted(ports)],
        )

    @staticmethod
    def _apply_switchport(port: SwitchPort, rest: list[str]) -> None:
        if not rest:
            return
        sub = rest[0].lower()
        if sub == "mode" and len(rest) >= 2:
            try:
                port.mode = PortMode(rest[1].lower())
            except ValueError:
                port.mode = PortMode.TRUNK
        elif sub == "access" and len(rest) >= 3 and rest[1].lower() == "vlan":
            port.pvid = int(rest[2])
        elif sub == "general" and len(rest) >= 4 and rest[1].lower() == "allowed":
            port.tagged_vlans = [int(v) for v in rest[3].split(",") if v.isdigit()]
        elif sub == "pvid" and len(rest) >= 2 and rest[1].isdigit():
            port.pvid = int(rest[1])
