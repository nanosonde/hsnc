"""JetStream config renderer — turns a declarative device into CLI commands.

Powers both the real config push (over an interactive SSH shell) and the
command-level diff on the Pending Changes view.
"""

from __future__ import annotations

from ...entities import Device
from ...enums import PortMode
from ...interfaces import DeviceConfigRenderer


class JetStreamCliRenderer(DeviceConfigRenderer):
    """Renders TP-Link JetStream switch configuration as CLI commands."""

    @property
    def platform(self) -> str:
        return "TP-Link JetStream CLI (SSH)"

    def render(self, device: Device) -> list[str]:
        lines: list[str] = ["configure", f"hostname {device.name}"]

        for vlan in sorted(device.vlans, key=lambda v: v.vlan_id):
            lines.append(f"vlan {vlan.vlan_id}")
            if vlan.name:
                lines.append(f" name {vlan.name}")
            lines.append(" exit")

        for port in sorted(device.ports, key=lambda p: p.number):
            lines.append(f"interface gigabitEthernet 1/0/{port.number}")
            if not port.enabled:
                lines.append(" shutdown")
            if port.mode is PortMode.ACCESS:
                lines.append(" switchport mode access")
                lines.append(f" switchport access vlan {port.pvid}")
            else:
                allowed = ",".join(
                    str(v) for v in sorted({port.pvid, *port.tagged_vlans})
                )
                lines.append(f" switchport mode {port.mode.value}")
                lines.append(f" switchport general allowed vlan {allowed}")
                lines.append(f" switchport pvid {port.pvid}")
            lines.append(" exit")

        lines.append("end")
        lines.append("copy running-config startup-config")
        return lines
