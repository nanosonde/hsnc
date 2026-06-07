"""OpenWrt device adapter (gateway / access point) over SSH + UCI.

Configuration plane only — runtime/monitoring data lives in
:class:`~sdnman.infrastructure.devices.monitoring.OpenWrtSshMonitoringProvider`.
Talks to OpenWrt-based devices using the same ``uci`` surface the mock container
emulates:

* :meth:`fetch_config`  — ``uci show network|wireless|system`` parsed into a Device
* :meth:`push_config`   — :class:`UciConfigRenderer` commands replayed over SSH

Each command is stateless, so it runs as an individual ``exec`` over SSH.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ...domain.entities import Device, SwitchPort, Vlan
from ...domain.enums import DeviceKind, PortMode
from ...domain.interfaces import DeviceAdapter
from ...domain.value_objects import IpAddress
from .config_renderers import UciConfigRenderer
from .ssh_transport import (
    RunnerFactory,
    SshCommandRunner,
    SshConnectionResolver,
    default_runner_factory,
)

# Matches `pkg.section.option='value'` / `pkg.section=type` lines from `uci show`.
_UCI_LINE_RE = re.compile(r"^([^.=]+)\.([^.=]+)(?:\.([^=]+))?=(.*)$")
_PORT_MEMBER_RE = re.compile(r"^lan(\d+):(t|u\*?)$")


class OpenWrtSshAdapter(DeviceAdapter):
    """Manages OpenWrt-based gateways and access points via SSH/UCI."""

    def __init__(
        self,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._resolver = resolver or SshConnectionResolver()
        self._runner_factory = runner_factory
        self._renderer = UciConfigRenderer()

    def supports(self, device: Device) -> bool:
        return device.kind in (DeviceKind.GATEWAY, DeviceKind.ACCESS_POINT)

    # -- connection helper ---------------------------------------------------
    def _runner(self, device: Device) -> SshCommandRunner:
        return self._runner_factory(self._resolver.resolve(device))

    # -- reads ---------------------------------------------------------------
    def fetch_config(self, device: Device) -> Device:
        runner = self._runner(device)
        with runner:
            raw = "".join(
                runner.run(f"uci show {pkg}") for pkg in ("system", "network", "wireless")
            )
        options = self._parse_uci(raw)

        hostname = options.get("system.@system[0].hostname", device.name)
        ipaddr = options.get("network.lan.ipaddr")
        vlans, ports = self._parse_bridge_vlans(options, device)
        ssids = self._parse_ssids(options)

        return replace(
            device,
            name=hostname,
            ip=IpAddress(ipaddr) if ipaddr else device.ip,
            # A re-read is the single source of truth: the parsed config replaces
            # the inventory wholesale, so an empty result clears stale entries.
            vlans=vlans,
            ports=ports,
            ssids=ssids,
        )

    # -- writes --------------------------------------------------------------
    def push_config(self, device: Device) -> None:
        runner = self._runner(device)
        with runner:
            # Read current bridge-vlan sections so we can clear them before
            # re-adding, keeping the push idempotent (anonymous sections would
            # otherwise accumulate on every apply).
            existing = self._parse_uci(runner.run("uci show network"))
            count = len(
                {
                    key.split(".")[1]
                    for key in existing
                    if key.startswith("network.@bridge-vlan[")
                }
            )
            commands = [
                "uci delete network.@bridge-vlan[0]" for _ in range(count)
            ] + self._renderer.render(device)
            for command in commands:
                runner.run(command)

    # -- parsing helpers -----------------------------------------------------
    @staticmethod
    def _parse_uci(raw: str) -> dict[str, str]:
        options: dict[str, str] = {}
        for line in raw.splitlines():
            match = _UCI_LINE_RE.match(line.strip())
            if not match:
                continue
            pkg, section, option, value = match.groups()
            value = value.strip().strip("'\"")
            key = f"{pkg}.{section}" + (f".{option}" if option else "")
            options[key] = value
        return options

    @classmethod
    def _parse_bridge_vlans(
        cls, options: dict[str, str], device: Device
    ) -> tuple[list[Vlan], list[SwitchPort]]:
        existing_names = {v.vlan_id: v.name for v in device.vlans}
        prefix = "network.@bridge-vlan["
        sections: dict[str, dict[str, str]] = {}
        for key, value in options.items():
            if not key.startswith(prefix):
                continue
            rest = key[len("network."):]
            section, _, option = rest.partition(".")
            if option:
                sections.setdefault(section, {})[option] = value

        vlans: list[Vlan] = []
        ports: dict[int, SwitchPort] = {}
        for section in sorted(sections):
            data = sections[section]
            vlan_str = data.get("vlan")
            if not vlan_str or not vlan_str.isdigit():
                continue
            vlan_id = int(vlan_str)
            vlans.append(Vlan(vlan_id=vlan_id, name=existing_names.get(vlan_id, f"VLAN{vlan_id}")))
            for token in data.get("ports", "").split():
                member = _PORT_MEMBER_RE.match(token)
                if not member:
                    continue
                num = int(member.group(1))
                flag = member.group(2)
                port = ports.setdefault(num, SwitchPort(number=num, name=f"LAN{num}"))
                if flag.startswith("u"):
                    port.pvid = vlan_id
                elif vlan_id not in port.tagged_vlans:
                    port.tagged_vlans.append(vlan_id)
        for port in ports.values():
            port.mode = PortMode.TRUNK if port.tagged_vlans else PortMode.ACCESS
        return vlans, [ports[n] for n in sorted(ports)]

    @staticmethod
    def _parse_ssids(options: dict[str, str]) -> list[str]:
        ssids: dict[int, str] = {}
        for key, value in options.items():
            if key.startswith("wireless.@wifi-iface[") and key.endswith(".ssid"):
                idx = int(key.split("[")[1].split("]")[0])
                ssids[idx] = value
        return [ssids[i] for i in sorted(ssids)]
