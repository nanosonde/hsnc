"""Pydantic schemas validating the on-disk YAML configuration.

These models exist purely at the infrastructure boundary to validate and parse
external input. They are mapped to framework-free domain entities by the
repository; the domain itself never imports Pydantic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class DeviceSchema(BaseModel):
    id: str
    name: str
    kind: str
    mac: str
    model: str = ""
    ip: str | None = None
    firmware: str = ""
    site_id: str = "default"
    ports: list[PortSchema] = Field(default_factory=list)
    vlans: list[VlanSchema] = Field(default_factory=list)
    ssids: list[str] = Field(default_factory=list)


class UsersFileSchema(BaseModel):
    users: list[UserSchema] = Field(default_factory=list)


class DevicesFileSchema(BaseModel):
    devices: list[DeviceSchema] = Field(default_factory=list)
