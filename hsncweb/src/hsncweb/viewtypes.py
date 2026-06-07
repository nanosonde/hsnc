"""Web-local view types: the shapes the templates render.

The frontend is self-contained — it does **not** import the backend's DTOs.
Instead it defines its own lightweight, display-ready types here and builds them
from the JSON the REST backend returns. Field names and computed properties
mirror what the Jinja templates access, so rendering is byte-for-byte identical
to the in-process implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class StatItem:
    label: str
    value: str
    detail: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StatItem:
        return cls(label=d["label"], value=d["value"], detail=d.get("detail", ""))


@dataclass(frozen=True)
class AssociationFailureRow:
    category: str
    count: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssociationFailureRow:
        return cls(category=d["category"], count=d["count"])


@dataclass(frozen=True)
class DashboardSummary:
    site_name: str
    stats: list[StatItem]
    admin_count: int
    device_count: int
    alert_count: int
    association_failures: list[AssociationFailureRow]
    association_failure_total: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DashboardSummary:
        return cls(
            site_name=d["site_name"],
            stats=[StatItem.from_dict(s) for s in d["stats"]],
            admin_count=d["admin_count"],
            device_count=d["device_count"],
            alert_count=d["alert_count"],
            association_failures=[
                AssociationFailureRow.from_dict(a) for a in d["association_failures"]
            ],
            association_failure_total=d["association_failure_total"],
        )


@dataclass(frozen=True)
class DeviceRow:
    id: str
    name: str
    kind: str
    model: str
    mac: str
    ip: str
    status: str
    firmware: str
    uptime: str
    client_count: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceRow:
        return cls(
            id=d["id"],
            name=d["name"],
            kind=d["kind"],
            model=d["model"],
            mac=d["mac"],
            ip=d["ip"],
            status=d["status"],
            firmware=d["firmware"],
            uptime=d["uptime"],
            client_count=d.get("client_count", 0),
        )


@dataclass(frozen=True)
class PortRow:
    number: int
    name: str
    enabled: bool
    mode: str
    pvid: int
    tagged_vlans: list[int]
    link_up: bool
    speed_mbps: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PortRow:
        return cls(
            number=d["number"],
            name=d["name"],
            enabled=d["enabled"],
            mode=d["mode"],
            pvid=d["pvid"],
            tagged_vlans=list(d["tagged_vlans"]),
            link_up=d["link_up"],
            speed_mbps=d["speed_mbps"],
        )


@dataclass(frozen=True)
class VlanRow:
    vlan_id: int
    name: str
    subnet: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VlanRow:
        return cls(vlan_id=d["vlan_id"], name=d["name"], subnet=d["subnet"])


@dataclass(frozen=True)
class DeviceDetail:
    row: DeviceRow
    ports: list[PortRow] = field(default_factory=list)
    vlans: list[VlanRow] = field(default_factory=list)
    ssids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceDetail:
        return cls(
            row=DeviceRow.from_dict(d["row"]),
            ports=[PortRow.from_dict(p) for p in d.get("ports", [])],
            vlans=[VlanRow.from_dict(v) for v in d.get("vlans", [])],
            ssids=list(d.get("ssids", [])),
        )


@dataclass(frozen=True)
class ClientRow:
    id: str
    name: str
    mac: str
    ip: str
    status: str
    network: str
    ssid: str
    ap_or_port: str
    activity: str
    downloaded: str
    uploaded: str
    uptime: str
    connection: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClientRow:
        return cls(
            id=d["id"],
            name=d["name"],
            mac=d["mac"],
            ip=d["ip"],
            status=d["status"],
            network=d["network"],
            ssid=d["ssid"],
            ap_or_port=d["ap_or_port"],
            activity=d["activity"],
            downloaded=d["downloaded"],
            uploaded=d["uploaded"],
            uptime=d["uptime"],
            connection=d["connection"],
        )


@dataclass(frozen=True)
class PagedClients:
    rows: list[ClientRow]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PagedClients:
        return cls(
            rows=[ClientRow.from_dict(r) for r in d["rows"]],
            page=d["page"],
            page_size=d["page_size"],
            total=d["total"],
        )


@dataclass(frozen=True)
class TopologyNodeView:
    id: str
    label: str
    kind: str
    badge: int | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TopologyNodeView:
        return cls(id=d["id"], label=d["label"], kind=d["kind"], badge=d.get("badge"))


@dataclass(frozen=True)
class TopologyLinkView:
    source_id: str
    target_id: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TopologyLinkView:
        return cls(source_id=d["source_id"], target_id=d["target_id"])


@dataclass(frozen=True)
class TopologyView:
    nodes: list[TopologyNodeView]
    links: list[TopologyLinkView]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TopologyView:
        return cls(
            nodes=[TopologyNodeView.from_dict(n) for n in d["nodes"]],
            links=[TopologyLinkView.from_dict(link) for link in d["links"]],
        )


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    display_name: str
    role: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuthenticatedUser:
        return cls(username=d["username"], display_name=d["display_name"], role=d["role"])


@dataclass(frozen=True)
class ChangeRow:
    field: str
    old: str
    new: str
    group: str = "General"
    change: str = "modified"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChangeRow:
        return cls(
            field=d["field"],
            old=d["old"],
            new=d["new"],
            group=d.get("group", "General"),
            change=d.get("change", "modified"),
        )


@dataclass(frozen=True)
class CommandLine:
    text: str
    change: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CommandLine:
        return cls(text=d["text"], change=d["change"])


@dataclass(frozen=True)
class SettingChange:
    path: str
    old: str
    new: str
    change: str = "modified"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SettingChange:
        return cls(
            path=d["path"], old=d["old"], new=d["new"], change=d.get("change", "modified")
        )


@dataclass(frozen=True)
class DeviceDiff:
    device_id: str
    device_name: str
    state: str
    changes: list[ChangeRow] = field(default_factory=list)
    platform: str = ""
    command_diff: list[CommandLine] = field(default_factory=list)
    setting_diff: list[SettingChange] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceDiff:
        return cls(
            device_id=d["device_id"],
            device_name=d["device_name"],
            state=d["state"],
            changes=[ChangeRow.from_dict(c) for c in d.get("changes", [])],
            platform=d.get("platform", ""),
            command_diff=[CommandLine.from_dict(c) for c in d.get("command_diff", [])],
            setting_diff=[SettingChange.from_dict(s) for s in d.get("setting_diff", [])],
        )


@dataclass(frozen=True)
class ConfigDiff:
    devices: list[DeviceDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.devices)

    @property
    def change_count(self) -> int:
        return len(self.devices)

    @property
    def total_changes(self) -> int:
        return sum(len(d.changes) for d in self.devices)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConfigDiff:
        return cls(devices=[DeviceDiff.from_dict(x) for x in d.get("devices", [])])


@dataclass(frozen=True)
class DeviceApplyResult:
    device_id: str
    device_name: str
    ok: bool
    message: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceApplyResult:
        return cls(
            device_id=d["device_id"],
            device_name=d["device_name"],
            ok=d["ok"],
            message=d.get("message", ""),
        )


@dataclass(frozen=True)
class ApplyResult:
    results: list[DeviceApplyResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failures(self) -> list[DeviceApplyResult]:
        return [r for r in self.results if not r.ok]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApplyResult:
        return cls(results=[DeviceApplyResult.from_dict(r) for r in d.get("results", [])])


@dataclass(frozen=True)
class DeviceSyncResult:
    device_id: str
    device_name: str
    ok: bool
    message: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceSyncResult:
        return cls(
            device_id=d["device_id"],
            device_name=d["device_name"],
            ok=d["ok"],
            message=d.get("message", ""),
        )


@dataclass(frozen=True)
class SyncResult:
    results: list[DeviceSyncResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failures(self) -> list[DeviceSyncResult]:
        return [r for r in self.results if not r.ok]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SyncResult:
        return cls(results=[DeviceSyncResult.from_dict(r) for r in d.get("results", [])])


@dataclass(frozen=True)
class ApplyPlanItem:
    device_id: str
    device_name: str
    action: str
    supported: bool
    change_count: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApplyPlanItem:
        return cls(
            device_id=d["device_id"],
            device_name=d["device_name"],
            action=d["action"],
            supported=d["supported"],
            change_count=d["change_count"],
        )


@dataclass(frozen=True)
class ApplyPlan:
    items: list[ApplyPlanItem] = field(default_factory=list)

    @property
    def has_actionable(self) -> bool:
        return any(i.action in ("create", "update") and i.supported for i in self.items)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApplyPlan:
        return cls(items=[ApplyPlanItem.from_dict(i) for i in d.get("items", [])])


@dataclass(frozen=True)
class FieldChange:
    field: str
    old: str
    new: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldChange:
        return cls(field=d["field"], old=d["old"], new=d["new"])


@dataclass(frozen=True)
class ApplyOutcome:
    device_id: str
    device_name: str
    ok: bool
    message: str = ""
    changes: list[FieldChange] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApplyOutcome:
        return cls(
            device_id=d["device_id"],
            device_name=d["device_name"],
            ok=d["ok"],
            message=d.get("message", ""),
            changes=[FieldChange.from_dict(c) for c in d.get("changes", [])],
        )


@dataclass(frozen=True)
class ApplyEvent:
    applied_at: datetime
    username: str
    ok: bool
    outcomes: list[ApplyOutcome] = field(default_factory=list)
    action: str = "apply"
    id: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApplyEvent:
        return cls(
            applied_at=datetime.fromisoformat(d["applied_at"]),
            username=d["username"],
            ok=d["ok"],
            outcomes=[ApplyOutcome.from_dict(o) for o in d.get("outcomes", [])],
            action=d.get("action", "apply"),
            id=d.get("id"),
        )
