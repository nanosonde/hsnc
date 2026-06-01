"""Data-transfer objects: flat view models for the presentation layer.

DTOs decouple templates from domain entities and carry pre-formatted,
display-ready values.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StatItem:
    """A single headline statistic on the dashboard summary strip."""

    label: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class AssociationFailureRow:
    category: str
    count: int


@dataclass(frozen=True)
class DashboardSummary:
    """Everything the dashboard view needs to render."""

    site_name: str
    stats: list[StatItem]
    admin_count: int
    device_count: int
    alert_count: int
    cloud_status: str
    association_failures: list[AssociationFailureRow]
    association_failure_total: int


@dataclass(frozen=True)
class DeviceRow:
    """A device as shown in the Devices table."""

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


@dataclass(frozen=True)
class VlanRow:
    vlan_id: int
    name: str
    subnet: str


@dataclass(frozen=True)
class DeviceDetail:
    row: DeviceRow
    ports: list[PortRow] = field(default_factory=list)
    vlans: list[VlanRow] = field(default_factory=list)
    ssids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClientRow:
    """A client as shown in the Clients table."""

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


@dataclass(frozen=True)
class TopologyNodeView:
    id: str
    label: str
    kind: str
    badge: int | None


@dataclass(frozen=True)
class TopologyLinkView:
    source_id: str
    target_id: str


@dataclass(frozen=True)
class TopologyView:
    nodes: list[TopologyNodeView]
    links: list[TopologyLinkView]


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    display_name: str
    role: str


@dataclass(frozen=True)
class ChangeRow:
    """A single field-level change between applied and desired config."""

    field: str
    old: str
    new: str


@dataclass(frozen=True)
class DeviceDiff:
    """Pending changes for one device."""

    device_id: str
    device_name: str
    state: str  # "added" | "modified" | "removed"
    changes: list[ChangeRow] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigDiff:
    """The full set of pending changes across all devices."""

    devices: list[DeviceDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.devices)

    @property
    def change_count(self) -> int:
        return len(self.devices)


@dataclass(frozen=True)
class DeviceApplyResult:
    device_id: str
    device_name: str
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of an apply operation."""

    results: list[DeviceApplyResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failures(self) -> list[DeviceApplyResult]:
        return [r for r in self.results if not r.ok]
