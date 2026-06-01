"""Platform-native config renderers (the inverse of pushing config).

Each renderer turns a declarative :class:`Device` into the concrete command
sequence that would provision it on its target platform:

* :class:`UciConfigRenderer` — OpenWrt ``uci`` commands sent over SSH.
* :class:`JetStreamCliRenderer` — TP-Link JetStream CLI commands over SSH.

These power the command-level diff on the Pending Changes view, so an operator
sees the exact commands that lead to both the applied and the desired state.
"""

from __future__ import annotations

from ...domain.entities import Device
from ...domain.enums import DeviceKind, PortMode
from ...domain.interfaces import (
    DeviceConfigRenderer,
    DeviceConfigRendererFactory,
)


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


class DefaultConfigRendererFactory(DeviceConfigRendererFactory):
    """Routes devices to the UCI or JetStream renderer by platform.

    Any device whose model advertises OpenWrt is rendered with ``uci``; other
    managed switches use the JetStream CLI. Gateways and access points in this
    project are OpenWrt-based and default to ``uci``.
    """

    def __init__(self) -> None:
        self._uci = UciConfigRenderer()
        self._jetstream = JetStreamCliRenderer()

    def for_device(self, device: Device) -> DeviceConfigRenderer:
        if "openwrt" in device.model.lower():
            return self._uci
        if device.kind is DeviceKind.SWITCH:
            return self._jetstream
        return self._uci
