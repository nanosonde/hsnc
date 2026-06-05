"""JSON store for per-device configuration payloads.

Backs both ``desired_config.json`` (the staged inventory the user edits) and
``current_config.json`` (the last configuration read from the devices — the
baseline used to compute pending changes). Each file holds only the
configuration payload (VLANs, ports, SSIDs, firmware, …) keyed by device id;
connection/identity lives in ``devices.yaml`` instead.

Writes are atomic (temp file + rename) so a crashed write never corrupts the
store. These files are owned by the web side of the application.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import DeviceConfigFileSchema, DeviceConfigSchema


class JsonDeviceConfigStore:
    """Atomic JSON map of ``device_id -> configuration payload``."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> dict[str, DeviceConfigSchema]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        schema = DeviceConfigFileSchema.model_validate(raw)
        return {entry.id: entry for entry in schema.devices}

    def save_all(self, configs: dict[str, DeviceConfigSchema]) -> None:
        schema = DeviceConfigFileSchema(devices=list(configs.values()))
        payload = schema.model_dump(mode="json")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def put(self, config: DeviceConfigSchema) -> None:
        configs = self.load()
        configs[config.id] = config
        self.save_all(configs)

    def remove(self, device_id: str) -> None:
        configs = self.load()
        if configs.pop(device_id, None) is not None:
            self.save_all(configs)
