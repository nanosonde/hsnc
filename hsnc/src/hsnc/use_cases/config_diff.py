"""Use case: compute pending changes (desired YAML vs last applied snapshot)."""

from __future__ import annotations

import difflib

from ..dtos import ChangeRow, CommandLine, ConfigDiff, DeviceDiff, SettingChange
from ..entities import Device, SwitchPort, Vlan
from ..interfaces import (
    AppliedConfigStore,
    ConfigRepository,
    DeviceConfigRendererFactory,
)


def _classify(old: str, new: str) -> str:
    if not old:
        return "added"
    if not new:
        return "removed"
    return "modified"


# --- General (scalar) fields ------------------------------------------------

_GENERAL_FIELDS = {
    "Name": lambda d: d.name,
    "Model": lambda d: d.model,
    "IP address": lambda d: str(d.ip) if d.ip else "",
    "Firmware": lambda d: d.firmware,
}


def _general_changes(old: Device | None, new: Device) -> list[ChangeRow]:
    rows: list[ChangeRow] = []
    for label, getter in _GENERAL_FIELDS.items():
        new_val = getter(new)
        old_val = getter(old) if old is not None else ""
        if old_val != new_val:
            rows.append(
                ChangeRow(
                    field=label,
                    old=old_val,
                    new=new_val,
                    group="General",
                    change=_classify(old_val, new_val),
                )
            )
    return rows


# --- VLANs ------------------------------------------------------------------

def _vlan_summary(v: Vlan) -> str:
    return f"{v.name or '(unnamed)'} · {v.subnet or 'no subnet'}"


def _vlan_changes(old: Device | None, new: Device) -> list[ChangeRow]:
    old_map = {v.vlan_id: v for v in (old.vlans if old is not None else [])}
    new_map = {v.vlan_id: v for v in new.vlans}
    rows: list[ChangeRow] = []
    for vid in sorted(old_map.keys() | new_map.keys()):
        o, n = old_map.get(vid), new_map.get(vid)
        label = f"VLAN {vid}"
        if o is None:
            rows.append(
                ChangeRow(label, "", _vlan_summary(n), group="VLANs", change="added")
            )
        elif n is None:
            rows.append(
                ChangeRow(label, _vlan_summary(o), "", group="VLANs", change="removed")
            )
        else:
            if o.name != n.name:
                rows.append(
                    ChangeRow(f"{label} · Name", o.name, n.name, group="VLANs")
                )
            if o.subnet != n.subnet:
                rows.append(
                    ChangeRow(f"{label} · Subnet", o.subnet, n.subnet, group="VLANs")
                )
    return rows


# --- Switch ports -----------------------------------------------------------

def _tagged(p: SwitchPort) -> str:
    return ", ".join(str(t) for t in p.tagged_vlans) or "none"


_PORT_ATTRS: list[tuple[str, object]] = [
    ("Name", lambda p: p.name or "(unnamed)"),
    ("Status", lambda p: "Enabled" if p.enabled else "Disabled"),
    ("Mode", lambda p: p.mode.value),
    ("PVID", lambda p: str(p.pvid)),
    ("Tagged VLANs", _tagged),
]


def _port_summary(p: SwitchPort) -> str:
    state = "enabled" if p.enabled else "disabled"
    return f"{p.mode.value}, PVID {p.pvid}, tagged [{_tagged(p)}], {state}"


def _port_changes(old: Device | None, new: Device) -> list[ChangeRow]:
    old_map = {p.number: p for p in (old.ports if old is not None else [])}
    new_map = {p.number: p for p in new.ports}
    rows: list[ChangeRow] = []
    for num in sorted(old_map.keys() | new_map.keys()):
        o, n = old_map.get(num), new_map.get(num)
        label = f"Port {num}"
        if o is None:
            rows.append(
                ChangeRow(label, "", _port_summary(n), group="Ports", change="added")
            )
        elif n is None:
            rows.append(
                ChangeRow(label, _port_summary(o), "", group="Ports", change="removed")
            )
        else:
            for attr_label, fmt in _PORT_ATTRS:
                ov, nv = fmt(o), fmt(n)  # type: ignore[operator]
                if ov != nv:
                    rows.append(
                        ChangeRow(f"{label} · {attr_label}", ov, nv, group="Ports")
                    )
    return rows


# --- Wireless (SSIDs) -------------------------------------------------------

def _ssid_changes(old: Device | None, new: Device) -> list[ChangeRow]:
    old_ssids = list(old.ssids) if old is not None else []
    new_ssids = list(new.ssids)
    rows: list[ChangeRow] = []
    for ssid in new_ssids:
        if ssid not in old_ssids:
            rows.append(ChangeRow("SSID", "", ssid, group="Wireless", change="added"))
    for ssid in old_ssids:
        if ssid not in new_ssids:
            rows.append(ChangeRow("SSID", ssid, "", group="Wireless", change="removed"))
    return rows



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
                        setting_diff=self._setting_diff(None, device),
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
                        setting_diff=self._setting_diff(applied[device_id], device),
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
                        setting_diff=self._setting_diff(device, None),
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

    def _setting_diff(
        self, old: Device | None, new: Device | None
    ) -> list[SettingChange]:
        """LuCI-style per-option diff of native config paths (UCI for OpenWrt).

        Returns an empty list for platforms whose renderer exposes no option
        paths (``settings`` defaults to an empty mapping).
        """
        if self._renderers is None:
            return []
        reference = new if new is not None else old
        if reference is None:
            return []
        renderer = self._renderers.for_device(reference)
        old_s = renderer.settings(old) if old is not None else {}
        new_s = renderer.settings(new) if new is not None else {}
        if not old_s and not new_s:
            return []

        # Preserve a stable, readable order: desired paths first, then any
        # remaining applied-only (removed) paths.
        ordered: list[str] = list(new_s.keys())
        ordered += [k for k in old_s if k not in new_s]

        rows: list[SettingChange] = []
        for path in ordered:
            ov = old_s.get(path)
            nv = new_s.get(path)
            if ov == nv:
                continue
            rows.append(
                SettingChange(
                    path=path,
                    old=ov or "",
                    new=nv or "",
                    change=_classify(ov or "", nv or ""),
                )
            )
        return rows

    @staticmethod
    def _field_changes(old: Device | None, new: Device) -> list[ChangeRow]:
        """Granular, grouped before/after rows (General, VLANs, Ports, Wireless)."""
        rows: list[ChangeRow] = []
        rows.extend(_general_changes(old, new))
        rows.extend(_vlan_changes(old, new))
        rows.extend(_port_changes(old, new))
        rows.extend(_ssid_changes(old, new))
        return rows
