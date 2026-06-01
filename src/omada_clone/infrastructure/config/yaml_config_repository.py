"""YAML-backed :class:`ConfigRepository` and :class:`ConfigArchive`.

Configuration is split across three files under the config directory:
    site.yaml     -> single site definition
    users.yaml    -> controller users (with hashed passwords)
    devices.yaml  -> declarative device inventory
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ...domain.entities import (
    Device,
    Site,
    SwitchPort,
    User,
    Vlan,
)
from ...domain.enums import DeviceKind, DeviceStatus, PortMode, Role
from ...domain.interfaces import ConfigArchive, ConfigRepository
from ...domain.value_objects import IpAddress, MacAddress
from .schemas import (
    DeviceSchema,
    DevicesFileSchema,
    SiteSchema,
    UserSchema,
    UsersFileSchema,
)

SITE_FILE = "site.yaml"
USERS_FILE = "users.yaml"
DEVICES_FILE = "devices.yaml"
_MANAGED_FILES = (SITE_FILE, USERS_FILE, DEVICES_FILE)


class YamlConfigRepository(ConfigRepository, ConfigArchive):
    """Loads configuration from YAML and maps it to domain entities."""

    def __init__(self, config_dir: str | Path) -> None:
        self._dir = Path(config_dir)

    # -- ConfigRepository -------------------------------------------------

    def get_site(self) -> Site:
        raw = self._read_yaml(SITE_FILE) or {}
        schema = SiteSchema.model_validate(raw)
        return Site(
            id=schema.id,
            name=schema.name,
            description=schema.description,
            country=schema.country,
        )

    def list_users(self) -> list[User]:
        raw = self._read_yaml(USERS_FILE) or {}
        schema = UsersFileSchema.model_validate(raw)
        return [self._to_user(u) for u in schema.users]

    def get_user(self, username: str) -> User | None:
        return next((u for u in self.list_users() if u.username == username), None)

    def list_devices(self) -> list[Device]:
        raw = self._read_yaml(DEVICES_FILE) or {}
        schema = DevicesFileSchema.model_validate(raw)
        return [self._to_device(d) for d in schema.devices]

    def get_device(self, device_id: str) -> Device | None:
        return next((d for d in self.list_devices() if d.id == device_id), None)

    # -- ConfigArchive ----------------------------------------------------

    def export_files(self) -> dict[str, str]:
        files: dict[str, str] = {}
        for name in _MANAGED_FILES:
            path = self._dir / name
            if path.exists():
                files[name] = path.read_text(encoding="utf-8")
        return files

    def import_files(self, files: dict[str, str]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for name, contents in files.items():
            if name not in _MANAGED_FILES:
                continue
            # validate before writing so a bad archive cannot corrupt config
            self._validate(name, contents)
            (self._dir / name).write_text(contents, encoding="utf-8")

    # -- mapping helpers --------------------------------------------------

    @staticmethod
    def _to_user(schema: UserSchema) -> User:
        return User(
            username=schema.username,
            password_hash=schema.password_hash,
            role=Role(schema.role),
            display_name=schema.display_name,
        )

    @staticmethod
    def _to_device(schema: DeviceSchema) -> Device:
        ports = [
            SwitchPort(
                number=p.number,
                name=p.name,
                enabled=p.enabled,
                mode=PortMode(p.mode),
                pvid=p.pvid,
                tagged_vlans=list(p.tagged_vlans),
            )
            for p in schema.ports
        ]
        vlans = [Vlan(vlan_id=v.vlan_id, name=v.name, subnet=v.subnet) for v in schema.vlans]
        return Device(
            id=schema.id,
            name=schema.name,
            kind=DeviceKind(schema.kind),
            mac=MacAddress(schema.mac),
            model=schema.model,
            ip=IpAddress(schema.ip) if schema.ip else None,
            status=DeviceStatus.UNKNOWN,
            firmware=schema.firmware,
            site_id=schema.site_id,
            ports=ports,
            vlans=vlans,
            ssids=list(schema.ssids),
        )

    # -- I/O --------------------------------------------------------------

    def _read_yaml(self, name: str) -> dict | None:
        path = self._dir / name
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    @staticmethod
    def _validate(name: str, contents: str) -> None:
        data = yaml.safe_load(contents) or {}
        if name == SITE_FILE:
            SiteSchema.model_validate(data)
        elif name == USERS_FILE:
            UsersFileSchema.model_validate(data)
        elif name == DEVICES_FILE:
            DevicesFileSchema.model_validate(data)
