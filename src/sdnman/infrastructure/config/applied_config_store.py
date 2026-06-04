"""File-based :class:`AppliedConfigStore` (JSON snapshot under the data dir).

Records the device configuration as of the last successful apply so the
controller can compute pending changes (desired YAML vs applied snapshot).
The on-disk format reuses the same Pydantic device schema as the YAML config.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...domain.entities import Device
from ...domain.interfaces import AppliedConfigStore
from .schemas import DevicesFileSchema
from .yaml_config_repository import YamlConfigRepository

_SNAPSHOT_NAME = "applied_config.json"


class FileAppliedConfigStore(AppliedConfigStore):
    """Persists the applied snapshot as JSON in the data directory."""

    def __init__(self, data_dir: str | Path) -> None:
        self._path = Path(data_dir) / _SNAPSHOT_NAME

    def load(self) -> list[Device]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        schema = DevicesFileSchema.model_validate(raw)
        return [YamlConfigRepository._to_device(d) for d in schema.devices]

    def save(self, devices: list[Device]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        schema = DevicesFileSchema(
            devices=[YamlConfigRepository._from_device(d) for d in devices]
        )
        payload = schema.model_dump(mode="json")
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)
