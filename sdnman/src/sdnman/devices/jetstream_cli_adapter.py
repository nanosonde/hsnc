"""TP-Link JetStream managed-switch adapter over SSH/CLI.

Configuration plane only — runtime/monitoring data lives in
:class:`~sdnman.devices.monitoring.JetStreamSshMonitoringProvider`
(and will move to SNMPv3 once implemented). Talks to JetStream switches using the
same CLI surface the mock container emulates:

* :meth:`fetch_config`  — ``show running-config`` parsed into VLANs and ports
* :meth:`push_config`   — :class:`JetStreamCliRenderer` commands fed through one
  interactive shell session (config mode is stateful)

Both reads and writes run through a single interactive shell. These switches
reject one-shot ``exec`` channels (``exec request failed on channel 0``), and
``show running-config`` is only available after ``enable`` raises the session to
privileged EXEC mode, so the read sends ``enable`` then ``show running-config``.
"""

from __future__ import annotations

from dataclasses import replace

from ..entities import Device, SwitchPort, Vlan
from ..enums import DeviceKind, PortMode
from ..interfaces import DeviceAdapter
from .config_renderers import JetStreamCliRenderer
from .ssh_transport import (
    RunnerFactory,
    SshCommandRunner,
    SshConnectionResolver,
    default_runner_factory,
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
    def fetch_config(self, device: Device) -> Device:
        runner = self._runner(device)
        # The switch rejects exec channels and gates `show running-config` behind
        # privileged mode, so raise privilege then read inside one shell session.
        with runner:
            raw = runner.run_shell(["enable", "show running-config"])
        hostname, vlans, ports = self._parse_running_config(raw)
        return replace(
            device,
            name=hostname or device.name,
            # A re-read is the single source of truth: the parsed config replaces
            # the inventory wholesale, so an empty result clears stale entries.
            vlans=vlans,
            ports=ports,
        )

    # -- writes --------------------------------------------------------------
    def push_config(self, device: Device) -> None:
        runner = self._runner(device)
        with runner:
            runner.run_shell(self._renderer.render(device))

    # -- parsing helpers -----------------------------------------------------
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
                hostname = cls._unquote(" ".join(words[1:]))
                current_vlan = current_port = None
            elif head == "vlan" and len(words) >= 2 and words[1].isdigit():
                current_vlan = int(words[1])
                current_port = None
                vlans.setdefault(
                    current_vlan, Vlan(vlan_id=current_vlan, name=f"VLAN{current_vlan}")
                )
            elif head == "name" and current_vlan is not None and len(words) >= 2:
                vlans[current_vlan] = Vlan(
                    vlan_id=current_vlan, name=cls._unquote(" ".join(words[1:]))
                )
            elif head == "interface" and len(words) >= 2:
                # `interface vlan N` is the management SVI, not a physical port.
                if words[1].lower() == "vlan":
                    current_vlan = current_port = None
                    continue
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
    def _unquote(value: str) -> str:
        """Strip a single pair of surrounding single/double quotes, if present."""
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            return value[1:-1]
        return value

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
            port.mode = PortMode.ACCESS
            port.pvid = int(rest[2])
        elif sub == "general" and len(rest) >= 4 and rest[1].lower() == "allowed":
            vlan_ids = [int(v) for v in rest[3].split(",") if v.isdigit()]
            membership = rest[4].lower() if len(rest) >= 5 else ""
            if membership == "untagged":
                # An untagged member is an access assignment; the PVID is set by
                # the companion `switchport pvid` line.
                port.mode = PortMode.ACCESS
                if vlan_ids:
                    port.pvid = vlan_ids[0]
            else:
                # `... tagged` (or no keyword, as the mock emits) means trunk.
                port.mode = PortMode.TRUNK
                port.tagged_vlans = vlan_ids
        elif sub == "pvid" and len(rest) >= 2 and rest[1].isdigit():
            port.pvid = int(rest[1])
