"""Use cases: export and import a full backup (config + runtime + history).

A backup is a single ZIP archive containing:
    config/<file>      -> raw YAML configuration files
    runtime.json       -> all runtime tables exported as JSON rows
    history.jsonl      -> the apply/audit history (one JSON object per line)
    manifest.json      -> archive metadata (version, created_at)
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

from ...domain.interfaces import ApplyHistoryStore, ConfigArchive, RuntimeStore

ARCHIVE_VERSION = 1
_CONFIG_PREFIX = "config/"
_RUNTIME_NAME = "runtime.json"
_HISTORY_NAME = "history.jsonl"
_MANIFEST_NAME = "manifest.json"


class ExportBackup:
    """Produce a ZIP archive (as bytes) of config, runtime and history."""

    def __init__(
        self,
        config: ConfigArchive,
        runtime: RuntimeStore,
        history: ApplyHistoryStore,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._history = history

    def execute(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            manifest = {
                "version": ARCHIVE_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
            }
            archive.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))

            for name, contents in self._config.export_files().items():
                archive.writestr(f"{_CONFIG_PREFIX}{name}", contents)

            runtime_rows = self._runtime.export_rows()
            archive.writestr(_RUNTIME_NAME, json.dumps(runtime_rows, indent=2, default=str))
            archive.writestr(_HISTORY_NAME, self._history.export_text())

        return buffer.getvalue()


class ImportBackup:
    """Restore config, runtime and history from a backup archive's bytes."""

    def __init__(
        self,
        config: ConfigArchive,
        runtime: RuntimeStore,
        history: ApplyHistoryStore,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._history = history

    def execute(self, archive_bytes: bytes) -> None:
        buffer = io.BytesIO(archive_bytes)
        with zipfile.ZipFile(buffer, "r") as archive:
            names = set(archive.namelist())

            if _MANIFEST_NAME in names:
                manifest = json.loads(archive.read(_MANIFEST_NAME))
                version = manifest.get("version")
                if version != ARCHIVE_VERSION:
                    raise ValueError(f"Unsupported backup version: {version!r}")

            config_files: dict[str, str] = {}
            for name in names:
                if name.startswith(_CONFIG_PREFIX) and not name.endswith("/"):
                    relative = name[len(_CONFIG_PREFIX):]
                    config_files[relative] = archive.read(name).decode("utf-8")
            if config_files:
                self._config.import_files(config_files)

            if _RUNTIME_NAME in names:
                runtime_rows = json.loads(archive.read(_RUNTIME_NAME))
                self._runtime.import_rows(runtime_rows)

            if _HISTORY_NAME in names:
                self._history.import_text(archive.read(_HISTORY_NAME).decode("utf-8"))
