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

    #: Persists running-config to startup-config. Separated from the config body
    #: so the adapter can defer it until a push has been verified error-free.
    SAVE_COMMAND = "copy running-config startup-config"

    @property
    def platform(self) -> str:
        return "TP-Link JetStream CLI (SSH)"

    def render_body(self, device: Device) -> list[str]:
        """Render the configuration commands *without* the trailing save.

        These commands mutate the switch's running-config live; the save
        (:attr:`SAVE_COMMAND`) is kept separate so a failed push can be rolled
        back before anything is persisted to startup-config.
        """
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
        return lines

    def render(self, device: Device) -> list[str]:
        return self.render_body(device) + [self.SAVE_COMMAND]
