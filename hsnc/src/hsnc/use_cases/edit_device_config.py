"""Use cases: edit device configuration (VLANs, ports, SSIDs).

Each use case loads the current device from the config repository, applies a
single mutation in the domain model, then persists via the :class:`ConfigWriter`
(which validates and takes a timestamped backup before writing).
"""

from __future__ import annotations

from ..entities import Device, SwitchPort, Vlan
from ..enums import PortMode
from ..interfaces import ConfigRepository, ConfigWriter


class DeviceNotFoundError(Exception):
    """Raised when a referenced device does not exist."""


class ConfigEditError(Exception):
    """Raised when a requested edit is invalid (e.g. duplicate VLAN id)."""


class _BaseEdit:
    def __init__(self, config: ConfigRepository, writer: ConfigWriter) -> None:
        self._config = config
        self._writer = writer

    def _load(self, device_id: str) -> Device:
        device = self._config.get_device(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device


class SaveVlan(_BaseEdit):
    """Create or update a VLAN on a device."""

    def execute(
        self, device_id: str, vlan_id: int, name: str, subnet: str = ""
    ) -> None:
        device = self._load(device_id)
        try:
            vlan = Vlan(vlan_id=vlan_id, name=name, subnet=subnet)
        except ValueError as exc:
            raise ConfigEditError(str(exc)) from exc
        device.vlans = [v for v in device.vlans if v.vlan_id != vlan_id]
        device.vlans.append(vlan)
        device.vlans.sort(key=lambda v: v.vlan_id)
        self._writer.save_device(device)


class DeleteVlan(_BaseEdit):
    """Remove a VLAN from a device."""

    def execute(self, device_id: str, vlan_id: int) -> None:
        device = self._load(device_id)
        if vlan_id in (p.pvid for p in device.ports):
            raise ConfigEditError(
                f"VLAN {vlan_id} is in use as a port PVID and cannot be removed."
            )
        device.vlans = [v for v in device.vlans if v.vlan_id != vlan_id]
        for port in device.ports:
            port.tagged_vlans = [t for t in port.tagged_vlans if t != vlan_id]
        self._writer.save_device(device)


class SavePort(_BaseEdit):
    """Update a switch port's configuration."""

    def execute(
        self,
        device_id: str,
        number: int,
        name: str,
        enabled: bool,
        mode: str,
        pvid: int,
        tagged_vlans: list[int],
    ) -> None:
        device = self._load(device_id)
        try:
            port_mode = PortMode(mode)
        except ValueError as exc:
            raise ConfigEditError(f"Invalid port mode: {mode!r}") from exc

        valid_vlans = {v.vlan_id for v in device.vlans}
        if pvid not in valid_vlans:
            raise ConfigEditError(f"PVID {pvid} is not a defined VLAN.")
        for tag in tagged_vlans:
            if tag not in valid_vlans:
                raise ConfigEditError(f"Tagged VLAN {tag} is not a defined VLAN.")

        updated = SwitchPort(
            number=number,
            name=name,
            enabled=enabled,
            mode=port_mode,
            pvid=pvid,
            tagged_vlans=sorted(set(tagged_vlans)),
        )
        existing = next((p for p in device.ports if p.number == number), None)
        if existing is None:
            raise ConfigEditError(f"Port {number} does not exist on this device.")
        # preserve live-only fields
        updated.link_up = existing.link_up
        updated.speed_mbps = existing.speed_mbps
        device.ports = [updated if p.number == number else p for p in device.ports]
        device.ports.sort(key=lambda p: p.number)
        self._writer.save_device(device)


class SaveSsids(_BaseEdit):
    """Replace the list of SSIDs on an access point."""

    def execute(self, device_id: str, ssids: list[str]) -> None:
        device = self._load(device_id)
        cleaned = [s.strip() for s in ssids if s.strip()]
        device.ssids = cleaned
        self._writer.save_device(device)
