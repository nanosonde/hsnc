"""Domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class DeviceKind(StrEnum):
    """The category of a managed network device."""

    GATEWAY = "gateway"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"


class DeviceStatus(StrEnum):
    """Operational status of a device or client."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    PENDING = "pending"
    UNKNOWN = "unknown"


class ConnectionType(StrEnum):
    """How a client is attached to the network."""

    WIRED = "wired"
    WIRELESS = "wireless"


class Role(StrEnum):
    """Authorization role for a controller user."""

    ADMIN = "admin"
    VIEWER = "viewer"


class PortMode(StrEnum):
    """802.1Q tagging mode of a switch port within a VLAN."""

    ACCESS = "access"
    TRUNK = "trunk"
    HYBRID = "hybrid"
