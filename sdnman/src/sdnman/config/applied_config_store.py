"""Current-config store: the last configuration read from the devices.

Records the device configuration as last read from the hardware (the *baseline*)
so the controller can compute pending changes (desired vs current). Persisted as
``current_config.json`` under the data dir; the configuration payload is keyed by
device id and merged with the connection profiles from ``devices.yaml`` on load,
mirroring :class:`LayeredConfigRepository`.

This satisfies the :class:`AppliedConfigStore` port: "applied" and "current" are
the same concept — the configuration the controller believes is running on each
device.
"""

from __future__ import annotations

from pathlib import Path

from ..entities import Device
from ..interfaces import AppliedConfigStore, ConfigRepository
from .device_config_store import JsonDeviceConfigStore
from .mapping import device_to_config, merge

_SNAPSHOT_NAME = "current_config.json"


class CurrentConfigStore(AppliedConfigStore):
    """Persists the last-read configuration payload as JSON in the data dir."""

    def __init__(
        self,
        data_dir: str | Path,
        profiles: ConfigRepository,
        store: JsonDeviceConfigStore | None = None,
    ) -> None:
        self._store = store or JsonDeviceConfigStore(Path(data_dir) / _SNAPSHOT_NAME)
        self._profiles = profiles

    @property
    def store(self) -> JsonDeviceConfigStore:
        return self._store

    def load(self) -> list[Device]:
        # Synthesise a bare entry (profile, no payload) for every known device,
        # even before the first baseline is written. This keeps the snapshot in
        # step with the inventory so a device is never spuriously diffed as a
        # whole "added" device (which would also make it impossible to revert)
        # when current_config.json is missing or omits it.
        configs = self._store.load() if self._store.exists() else {}
        return [merge(p, configs.get(p.id)) for p in self._profiles.list_devices()]

    def save(self, devices: list[Device]) -> None:
        self._store.save_all({d.id: device_to_config(d) for d in devices})

