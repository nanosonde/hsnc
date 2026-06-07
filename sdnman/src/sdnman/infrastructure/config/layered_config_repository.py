"""Layered configuration repository: connection profiles + config payloads.

Assembles full :class:`Device` entities by overlaying the desired configuration
payload (``desired_config.json``) onto the connection profiles read from
``devices.yaml``. This is the **desired** view the application edits and diffs
against the current (last-read) configuration.

* Reads (``list_devices`` / ``get_device``) merge profile + desired payload.
* Writes (``save_device``) persist only the configuration payload to the desired
  store, leaving connection profiles under the user's control in ``devices.yaml``.
* ``delete_device`` drops both the desired payload and the connection profile.

Site and user reads delegate to the underlying profile repository unchanged.
"""

from __future__ import annotations

from ...domain.entities import Device, Site, User
from ...domain.interfaces import ConfigArchive, ConfigRepository, ConfigWriter
from .device_config_store import JsonDeviceConfigStore
from .mapping import device_to_config, merge
from .yaml_config_repository import YamlConfigRepository


class LayeredConfigRepository(ConfigRepository, ConfigWriter, ConfigArchive):
    """Combines a profile repository with a desired-config JSON store."""

    def __init__(
        self,
        profiles: YamlConfigRepository,
        desired: JsonDeviceConfigStore,
        current: JsonDeviceConfigStore | None = None,
    ) -> None:
        self._profiles = profiles
        self._desired = desired
        self._current = current

    # -- ConfigRepository -------------------------------------------------

    def get_site(self) -> Site:
        return self._profiles.get_site()

    def list_users(self) -> list[User]:
        return self._profiles.list_users()

    def get_user(self, username: str) -> User | None:
        return self._profiles.get_user(username)

    def list_devices(self) -> list[Device]:
        configs = self._desired.load()
        return [merge(p, configs.get(p.id)) for p in self._profiles.list_devices()]

    def get_device(self, device_id: str) -> Device | None:
        profile = self._profiles.get_device(device_id)
        if profile is None:
            return None
        return merge(profile, self._desired.load().get(device_id))

    # -- ConfigWriter -----------------------------------------------------

    def save_device(self, device: Device) -> None:
        self._desired.put(device_to_config(device))

    def delete_device(self, device_id: str) -> None:
        self._desired.remove(device_id)
        self._profiles.delete_device(device_id)

    # -- ConfigArchive ----------------------------------------------------

    def export_files(self) -> dict[str, str]:
        files = self._profiles.export_files()
        for store in self._payload_stores():
            if store.path.exists():
                files[store.path.name] = store.path.read_text(encoding="utf-8")
        return files

    def import_files(self, files: dict[str, str]) -> None:
        payload_names = {store.path.name: store for store in self._payload_stores()}
        for name, store in payload_names.items():
            if name in files:
                store.path.parent.mkdir(parents=True, exist_ok=True)
                store.path.write_text(files[name], encoding="utf-8")
        profile_files = {k: v for k, v in files.items() if k not in payload_names}
        if profile_files:
            self._profiles.import_files(profile_files)

    def _payload_stores(self) -> list[JsonDeviceConfigStore]:
        stores = [self._desired]
        if self._current is not None:
            stores.append(self._current)
        return stores

