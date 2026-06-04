"""YAML-backed :class:`ConfigRepository` and :class:`ConfigArchive`.

Configuration is split across three files under the config directory:
    site.yaml     -> single site definition
    users.yaml    -> controller users (with hashed passwords)
    devices.yaml  -> declarative device inventory
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from ...domain.entities import (
    Device,
    DeviceConnection,
    Site,
    SwitchPort,
    User,
    Vlan,
)
from ...domain.enums import DeviceKind, DeviceStatus, PortMode, Role
from ...domain.interfaces import ConfigArchive, ConfigRepository, ConfigWriter
from ...domain.value_objects import IpAddress, MacAddress
from .schemas import (
    ConnectionSchema,
    DeviceSchema,
    DevicesFileSchema,
    PortSchema,
    SiteSchema,
    UserSchema,
    UsersFileSchema,
    VlanSchema,
)

SITE_FILE = "site.yaml"
USERS_FILE = "users.yaml"
DEVICES_FILE = "devices.yaml"
_MANAGED_FILES = (SITE_FILE, USERS_FILE, DEVICES_FILE)
_BACKUP_DIRNAME = "config-backups"


class YamlConfigRepository(ConfigRepository, ConfigArchive, ConfigWriter):
    """Loads configuration from YAML and maps it to domain entities."""

    def __init__(self, config_dir: str | Path, backup_dir: str | Path | None = None) -> None:
        self._dir = Path(config_dir)
        # Pre-write backups land beside the config by default, or in data_dir.
        self._backup_dir = Path(backup_dir) if backup_dir else self._dir / _BACKUP_DIRNAME

    @property
    def config_dir(self) -> Path:
        return self._dir

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

    # -- ConfigWriter -----------------------------------------------------

    def save_device(self, device: Device) -> None:
        """Create or update a device in devices.yaml (validated + backed up)."""

        schema = self._from_device(device)
        devices = self.list_devices()
        existing = {d.id: d for d in devices}
        existing[device.id] = self._to_device(schema)  # normalise via schema

        file_schema = DevicesFileSchema(
            devices=[self._from_device(d) for d in existing.values()]
        )
        # Serialise with stable ordering and validate before touching disk.
        payload = file_schema.model_dump(mode="python")
        contents = yaml.safe_dump(payload, default_flow_style=False, sort_keys=False)
        self._validate(DEVICES_FILE, contents)

        self._backup_managed_files()
        self._atomic_write(DEVICES_FILE, contents)

    def delete_device(self, device_id: str) -> None:
        """Remove a device from devices.yaml (validated + backed up)."""

        devices = self.list_devices()
        remaining = [d for d in devices if d.id != device_id]
        if len(remaining) == len(devices):
            return  # nothing to delete

        file_schema = DevicesFileSchema(
            devices=[self._from_device(d) for d in remaining]
        )
        payload = file_schema.model_dump(mode="python")
        contents = yaml.safe_dump(payload, default_flow_style=False, sort_keys=False)
        self._validate(DEVICES_FILE, contents)

        self._backup_managed_files()
        self._atomic_write(DEVICES_FILE, contents)

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
        connection = (
            DeviceConnection(
                host=schema.connection.host,
                port=schema.connection.port,
                username=schema.connection.username,
            )
            if schema.connection is not None
            else None
        )
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
            connection=connection,
        )

    @staticmethod
    def _from_device(device: Device) -> DeviceSchema:
        return DeviceSchema(
            id=device.id,
            name=device.name,
            kind=device.kind.value,
            mac=str(device.mac),
            model=device.model,
            ip=str(device.ip) if device.ip else None,
            firmware=device.firmware,
            site_id=device.site_id,
            ports=[
                PortSchema(
                    number=p.number,
                    name=p.name,
                    enabled=p.enabled,
                    mode=p.mode.value,
                    pvid=p.pvid,
                    tagged_vlans=list(p.tagged_vlans),
                )
                for p in device.ports
            ],
            vlans=[
                VlanSchema(vlan_id=v.vlan_id, name=v.name, subnet=v.subnet)
                for v in device.vlans
            ],
            ssids=list(device.ssids),
            connection=(
                ConnectionSchema(
                    host=device.connection.host,
                    port=device.connection.port,
                    username=device.connection.username,
                )
                if device.connection is not None
                else None
            ),
        )

    # -- I/O --------------------------------------------------------------

    def _read_yaml(self, name: str) -> dict | None:
        path = self._dir / name
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _atomic_write(self, name: str, contents: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(contents, encoding="utf-8")
        tmp.replace(target)

    def _backup_managed_files(self) -> None:
        """Copy current managed config files into a timestamped backup dir."""

        present = [name for name in _MANAGED_FILES if (self._dir / name).exists()]
        if not present:
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = self._backup_dir / stamp
        dest.mkdir(parents=True, exist_ok=True)
        for name in present:
            (dest / name).write_text(
                (self._dir / name).read_text(encoding="utf-8"), encoding="utf-8"
            )

    @staticmethod
    def _validate(name: str, contents: str) -> None:
        data = yaml.safe_load(contents) or {}
        if name == SITE_FILE:
            SiteSchema.model_validate(data)
        elif name == USERS_FILE:
            UsersFileSchema.model_validate(data)
        elif name == DEVICES_FILE:
            DevicesFileSchema.model_validate(data)
