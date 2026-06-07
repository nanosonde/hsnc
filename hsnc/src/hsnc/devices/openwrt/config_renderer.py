"""OpenWrt config renderer — turns a declarative device into ``uci`` commands.

Powers both the real config push (over SSH) and the command-level diff on the
Pending Changes view, so an operator sees the exact ``uci`` commands that lead to
both the applied and the desired state.
"""

from __future__ import annotations

from ...entities import Device
from ...interfaces import DeviceConfigRenderer


class UciConfigRenderer(DeviceConfigRenderer):
    """Renders OpenWrt configuration as ``uci`` commands (DSA bridge model)."""

    @property
    def platform(self) -> str:
        return "OpenWrt (UCI over SSH)"

    def render(self, device: Device) -> list[str]:
        lines: list[str] = [f"uci set system.@system[0].hostname='{device.name}'"]
        if device.ip:
            lines.append(f"uci set network.lan.ipaddr='{device.ip}'")

        if device.vlans or device.ports:
            lines.extend(self._render_switch(device))

        for idx, ssid in enumerate(device.ssids):
            lines.append(f"uci set wireless.@wifi-iface[{idx}].ssid='{ssid}'")
            lines.append(f"uci set wireless.@wifi-iface[{idx}].network='lan'")

        lines.append("uci commit")
        return lines

    def settings(self, device: Device) -> dict[str, str]:
        """Flatten the config into concrete UCI option paths (LuCI-style).

        Bridge-VLAN sections are keyed by their VLAN id (``[10]``) rather than an
        anonymous index so the diff stays stable and readable.
        """
        s: dict[str, str] = {"system.@system[0].hostname": device.name}
        if device.ip:
            s["network.lan.ipaddr"] = str(device.ip)

        ports = sorted(device.ports, key=lambda p: p.number)
        for vlan in sorted(device.vlans, key=lambda v: v.vlan_id):
            base = f"network.@bridge-vlan[{vlan.vlan_id}]"
            members: list[str] = []
            for port in ports:
                if not port.enabled:
                    continue
                if vlan.vlan_id in port.tagged_vlans:
                    members.append(f"lan{port.number}:t")
                elif port.pvid == vlan.vlan_id:
                    members.append(f"lan{port.number}:u*")
            s[f"{base}.device"] = "br-lan"
            s[f"{base}.vlan"] = str(vlan.vlan_id)
            s[f"{base}.ports"] = " ".join(members)

        for idx, ssid in enumerate(device.ssids):
            s[f"wireless.@wifi-iface[{idx}].ssid"] = ssid
            s[f"wireless.@wifi-iface[{idx}].network"] = "lan"
        return s

    @staticmethod
    def _render_switch(device: Device) -> list[str]:
        lines: list[str] = []
        ports = sorted((p for p in device.ports), key=lambda p: p.number)
        for vlan in sorted(device.vlans, key=lambda v: v.vlan_id):
            members: list[str] = []
            for port in ports:
                if not port.enabled:
                    continue
                if vlan.vlan_id in port.tagged_vlans:
                    members.append(f"lan{port.number}:t")
                elif port.pvid == vlan.vlan_id:
                    # untagged + PVID member in OpenWrt DSA syntax
                    members.append(f"lan{port.number}:u*")
            lines.append(f"uci add network bridge-vlan  # VLAN {vlan.vlan_id} ({vlan.name})")
            lines.append("uci set network.@bridge-vlan[-1].device='br-lan'")
            lines.append(f"uci set network.@bridge-vlan[-1].vlan='{vlan.vlan_id}'")
            lines.append(f"uci set network.@bridge-vlan[-1].ports='{' '.join(members)}'")
        return lines
