"""Use case: re-read configuration from physical devices into the inventory.

``SyncDeviceConfig`` reads the live configuration from each device through its
:class:`DeviceAdapter`, writes it back into the declarative inventory (YAML),
and updates the applied snapshot so the re-read does not surface as a pending
change. The run is recorded in the apply history with ``action="reread"``.
Per-device failures (including unimplemented real-device adapters that raise
:class:`NotImplementedError`) are collected without aborting the run.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from ..dtos import DeviceSyncResult, SyncResult
from ..entities import ApplyEvent, ApplyOutcome, Device
from ..interfaces import (
    AppliedConfigStore,
    ApplyHistoryStore,
    ConfigRepository,
    ConfigWriter,
    DeviceAdapterFactory,
)


class SyncDeviceConfig:
    """Re-read device configuration from hardware into the inventory."""

    def __init__(
        self,
        config: ConfigRepository,
        adapters: DeviceAdapterFactory,
        writer: ConfigWriter,
        applied: AppliedConfigStore,
        history: ApplyHistoryStore,
    ) -> None:
        self._config = config
        self._adapters = adapters
        self._writer = writer
        self._applied = applied
        self._history = history

    def execute(
        self,
        device_ids: Iterable[str] | None = None,
        username: str = "",
    ) -> SyncResult:
        selected = set(device_ids) if device_ids is not None else None
        devices = [
            d
            for d in self._config.list_devices()
            if selected is None or d.id in selected
        ]

        results: list[DeviceSyncResult] = []
        synced: dict[str, Device] = {}
        for device in devices:
            adapter = self._adapters.for_device(device)
            try:
                fresh = adapter.fetch_config(device)
                self._writer.save_device(fresh)
                synced[device.id] = fresh
                results.append(DeviceSyncResult(device.id, device.name, ok=True))
            except NotImplementedError as exc:
                results.append(
                    DeviceSyncResult(
                        device.id,
                        device.name,
                        ok=False,
                        message=str(exc) or "Device driver not implemented yet.",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surface any adapter error per device
                results.append(
                    DeviceSyncResult(device.id, device.name, ok=False, message=str(exc))
                )

        result = SyncResult(results=results)

        # Re-read configuration becomes the new source of truth: update the
        # applied snapshot for successfully-read devices so the re-read does not
        # show up as a pending change.
        if synced:
            snapshot = {d.id: d for d in self._applied.load()}
            snapshot.update(synced)
            self._applied.save(list(snapshot.values()))

        if results:
            self._history.record_apply_event(
                ApplyEvent(
                    applied_at=datetime.now(UTC),
                    username=username,
                    ok=result.ok,
                    action="reread",
                    outcomes=[
                        ApplyOutcome(r.device_id, r.device_name, r.ok, r.message)
                        for r in results
                    ],
                )
            )
        return result
