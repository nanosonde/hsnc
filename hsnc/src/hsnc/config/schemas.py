"""Pydantic schemas validating the on-disk YAML configuration.

These models exist purely at the infrastructure boundary to validate and parse
external input. They are mapped to framework-free domain entities by the
repository; the domain itself never imports Pydantic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SiteSchema(BaseModel):
    id: str = "default"
    name: str = "Default"
    description: str = ""
    country: str = ""


class UserSchema(BaseModel):
    username: str
    password_hash: str
    role: str = "viewer"
    display_name: str = ""


class VlanSchema(BaseModel):
    vlan_id: int = Field(ge=1, le=4094)
    name: str
    subnet: str = ""


class PortSchema(BaseModel):
    number: int = Field(ge=1)
    name: str = ""
    enabled: bool = True
    mode: str = "access"
    pvid: int = 1
    tagged_vlans: list[int] = Field(default_factory=list)


class ConnectionSchema(BaseModel):
    host: str = ""
    port: int = Field(default=0, ge=0, le=65535)
    username: str = ""


_REMOVED_MONITORING_KEYS = ("source", "secondary", "type")


class MonitoringSchema(BaseModel):
    """Per-device monitoring config.

    The monitoring plane never uses SSH; the transport is fixed by platform
    (Prometheus for OpenWrt, SNMPv3 for JetStream), so only the on/off flag and
    an optional endpoint override are configurable::

        monitoring:
          enabled: true                              # default; false disables polling
          endpoint: "http://host:9100/metrics"       # optional; SNMP host[:port] for switches
          port: 161                                  # optional, SNMP only (default 161)

    When ``endpoint`` is omitted it is derived from the device's management IP.
    """

    enabled: bool = True
    endpoint: str = ""
    port: int = Field(default=0, ge=0, le=65535)

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_keys(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        present = [key for key in _REMOVED_MONITORING_KEYS if key in data]
        if present:
            raise ValueError(
                "monitoring keys "
                + ", ".join(repr(key) for key in present)
                + " were removed: the monitoring plane no longer uses SSH and the "
                "primary/secondary model is gone. Use `enabled`, `endpoint` and "
                "`port` instead. See docs/devices/."
            )
        return data


class DeviceSchema(BaseModel):
    """Connection/identity profile for a device (``devices.yaml``).

    This is the *connection* configuration only. The running/desired device
    configuration (VLANs, ports, SSIDs, firmware, …) lives in separate
    JSON stores owned by the web app, not here.
    """

    id: str
    name: str
    kind: str
    site_id: str = "default"
    ip: str | None = None
    connection: ConnectionSchema | None = None
    monitoring: MonitoringSchema | None = None


class DeviceConfigSchema(BaseModel):
    """Per-device running/desired configuration payload (JSON stores)."""

    id: str
    mac: str = ""
    model: str = ""
    firmware: str = ""
    ports: list[PortSchema] = Field(default_factory=list)
    vlans: list[VlanSchema] = Field(default_factory=list)
    ssids: list[str] = Field(default_factory=list)


class UsersFileSchema(BaseModel):
    users: list[UserSchema] = Field(default_factory=list)


class DevicesFileSchema(BaseModel):
    devices: list[DeviceSchema] = Field(default_factory=list)


class DeviceConfigFileSchema(BaseModel):
    """On-disk schema for ``desired_config.json`` / ``current_config.json``."""

    devices: list[DeviceConfigSchema] = Field(default_factory=list)
