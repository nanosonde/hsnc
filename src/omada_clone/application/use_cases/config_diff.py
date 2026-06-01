"""Use case: compute pending changes (desired YAML vs last applied snapshot)."""

from __future__ import annotations

import difflib

from ...domain.entities import Device
from ...domain.interfaces import (
    AppliedConfigStore,
    ConfigRepository,
    DeviceConfigRendererFactory,
)
from ..dtos import ChangeRow, CommandLine, ConfigDiff, DeviceDiff


def _vlan_repr(device: Device) -> str:
    return "; ".join(
        f"{v.vlan_id}:{v.name}:{v.subnet}" for v in sorted(device.vlans, key=lambda v: v.vlan_id)
    )


def _port_repr(device: Device) -> str:
    parts = []
    for p in sorted(device.ports, key=lambda p: p.number):
        tagged = ",".join(str(t) for t in p.tagged_vlans)
        parts.append(f"{p.number}:{p.mode.value}:pvid={p.pvid}:tag=[{tagged}]:en={p.enabled}")
    return "; ".join(parts)


def _ssid_repr(device: Device) -> str:
    return ", ".join(device.ssids)


_FIELDS = {
    "Name": lambda d: d.name,
    "Model": lambda d: d.model,
    "IP": lambda d: str(d.ip) if d.ip else "",
    "Firmware": lambda d: d.firmware,
    "VLANs": _vlan_repr,
    "Ports": _port_repr,
    "SSIDs": _ssid_repr,
}


class GetConfigDiff:
    """Diff the desired configuration against the last applied snapshot."""

    def __init__(
        self,
        config: ConfigRepository,
        applied: AppliedConfigStore,
        renderers: DeviceConfigRendererFactory | None = None,
    ) -> None:
        self._config = config
        self._applied = applied
        self._renderers = renderers

    def execute(self) -> ConfigDiff:
        desired = {d.id: d for d in self._config.list_devices()}
        applied = {d.id: d for d in self._applied.load()}

        diffs: list[DeviceDiff] = []

        for device_id, device in desired.items():
            if device_id not in applied:
                diffs.append(
                    DeviceDiff(
                        device_id,
                        device.name,
                        "added",
                        self._field_changes(None, device),
                        platform=self._platform(device),
                        command_diff=self._command_diff(None, device),
                    )
                )
                continue
            changes = self._field_changes(applied[device_id], device)
            if changes:
                diffs.append(
                    DeviceDiff(
                        device_id,
                        device.name,
                        "modified",
                        changes,
                        platform=self._platform(device),
                        command_diff=self._command_diff(applied[device_id], device),
                    )
                )

        for device_id, device in applied.items():
            if device_id not in desired:
                diffs.append(
                    DeviceDiff(
                        device_id,
                        device.name,
                        "removed",
                        [],
                        platform=self._platform(device),
                        command_diff=self._command_diff(device, None),
                    )
                )

        return ConfigDiff(devices=diffs)

    def _platform(self, device: Device) -> str:
        if self._renderers is None:
            return ""
        return self._renderers.for_device(device).platform

    def _command_diff(
        self, old: Device | None, new: Device | None
    ) -> list[CommandLine]:
        """Line-level diff of the commands producing the applied vs desired config."""
        if self._renderers is None:
            return []
        reference = new if new is not None else old
        if reference is None:
            return []
        renderer = self._renderers.for_device(reference)
        old_cmds = renderer.render(old) if old is not None else []
        new_cmds = renderer.render(new) if new is not None else []

        rows: list[CommandLine] = []
        for line in difflib.Differ().compare(old_cmds, new_cmds):
            marker, text = line[:2], line[2:]
            if marker == "+ ":
                rows.append(CommandLine(text=text, change="added"))
            elif marker == "- ":
                rows.append(CommandLine(text=text, change="removed"))
            elif marker == "  ":
                rows.append(CommandLine(text=text, change="context"))
            # "? " hint lines are intraline markers; skip them
        return rows

    @staticmethod
    def _field_changes(old: Device | None, new: Device) -> list[ChangeRow]:
        rows: list[ChangeRow] = []
        for label, getter in _FIELDS.items():
            new_val = getter(new)
            old_val = getter(old) if old is not None else ""
            if old_val != new_val:
                rows.append(ChangeRow(field=label, old=old_val, new=new_val))
        return rows
