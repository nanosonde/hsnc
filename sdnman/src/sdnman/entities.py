"""Domain entities: objects with identity and a lifecycle.

Entities are plain dataclasses free of any framework or persistence concern.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from datetime import datetime

from .enums import (
    ConnectionType,
    DeviceKind,
    DeviceStatus,
    PortMode,
    Role,
)
from .value_objects import DataVolume, IpAddress, MacAddress, Throughput


@dataclass
class Site:
    """A logical grouping of devices and clients (one site is supported today)."""

    id: str
    name: str
    description: str = ""
    country: str = ""


@dataclass
class User:
    """A controller operator with an authorization role."""

    username: str
    password_hash: str
    role: Role
    display_name: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


@dataclass
class Vlan:
    """An 802.1Q VLAN definition."""

    vlan_id: int
    name: str
    subnet: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.vlan_id <= 4094:
            raise ValueError("VLAN id must be between 1 and 4094")
        if self.subnet:
            if "/" not in self.subnet:
                raise ValueError(
                    f"Subnet must be in CIDR notation (e.g. 192.168.1.0/24): {self.subnet!r}"
                )
            try:
                ipaddress.ip_network(self.subnet, strict=False)
            except ValueError as exc:
                raise ValueError(f"Invalid subnet {self.subnet!r}: {exc}") from exc


@dataclass
class SwitchPort:
    """A physical port on a managed switch."""

    number: int
    name: str = ""
    enabled: bool = True
    mode: PortMode = PortMode.ACCESS
    pvid: int = 1
    tagged_vlans: list[int] = field(default_factory=list)
    link_up: bool = False
    speed_mbps: int = 0


@dataclass
class DeviceConnection:
    """SSH connection details for managing a device.

    Empty/zero fields fall back to platform defaults at adapter build time. The
    password is never stored here (or in YAML): it is resolved from the
    environment so secrets stay out of the declarative inventory.
    """

    host: str = ""  # "" -> use the device's management IP
    port: int = 0  # 0 -> platform default (22)
    username: str = ""  # "" -> platform default (root / admin)


@dataclass
class MonitoringConfig:
    """Optional secondary live-data source for a device.

    The configuration plane is always SSH. This describes an *additional*
    runtime/telemetry channel the poll loop may open alongside the SSH
    connection (e.g. an SNMPv3 agent or a Prometheus exporter over HTTP(S)).
    ``type == "ssh"`` means runtime data is scraped over the same SSH plane;
    ``type == "none"`` disables live data for the device.
    """

    type: str = "ssh"  # ssh | snmp | prometheus | none
    endpoint: str = ""  # transport-specific target, e.g. "https://host:9100/metrics"


@dataclass
class Device:
    """A managed network device (gateway, switch or access point)."""

    id: str
    name: str
    kind: DeviceKind
    mac: MacAddress | None = None
    model: str = ""
    ip: IpAddress | None = None
    status: DeviceStatus = DeviceStatus.UNKNOWN
    firmware: str = ""
    uptime_seconds: int = 0
    site_id: str = "default"
    # switch-only attributes
    ports: list[SwitchPort] = field(default_factory=list)
    vlans: list[Vlan] = field(default_factory=list)
    # access-point-only attributes
    ssids: list[str] = field(default_factory=list)
    # optional SSH connection override (host/port/user); None -> derive from ip
    connection: DeviceConnection | None = None
    # optional secondary live-data source (SNMP/Prometheus); None -> SSH scrape
    monitoring: MonitoringConfig | None = None


@dataclass
class Client:
    """An endpoint attached to the network (wired or wireless)."""

    id: str
    name: str
    mac: MacAddress
    connection: ConnectionType
    status: DeviceStatus = DeviceStatus.UNKNOWN
    ip: IpAddress | None = None
    network: str = "LAN"
    ssid: str = ""
    ap_or_port: str = ""
    activity: Throughput = field(default_factory=Throughput)
    downloaded: DataVolume = field(default_factory=DataVolume)
    uploaded: DataVolume = field(default_factory=DataVolume)
    uptime_seconds: int = 0
    site_id: str = "default"


@dataclass
class TopologyNode:
    """A node in the network topology graph."""

    id: str
    label: str
    kind: str  # "internet" | "device" | "controller" | "client_group"
    badge: int | None = None


@dataclass
class TopologyLink:
    """A connection between two topology nodes."""

    source_id: str
    target_id: str


@dataclass
class Topology:
    """The full topology graph for a site."""

    nodes: list[TopologyNode] = field(default_factory=list)
    links: list[TopologyLink] = field(default_factory=list)


@dataclass
class AssociationFailure:
    """A recorded wireless association failure, by category."""

    category: str
    count: int = 0


@dataclass(frozen=True)
class FieldChange:
    """A single field-level change applied to a device (for audit/history)."""

    field: str
    old: str
    new: str


@dataclass(frozen=True)
class ApplyOutcome:
    """The result of pushing configuration to a single device."""

    device_id: str
    device_name: str
    ok: bool
    message: str = ""
    changes: list[FieldChange] = field(default_factory=list)


@dataclass
class ApplyEvent:
    """A recorded configuration-apply run (for history / audit)."""

    applied_at: datetime
    username: str
    ok: bool
    outcomes: list[ApplyOutcome] = field(default_factory=list)
    action: str = "apply"
    id: int | None = None
