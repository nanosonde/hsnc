"""Use case: apply the desired configuration to devices.

Pushes each device's desired configuration through its :class:`DeviceAdapter`.
On overall success the applied snapshot is updated so the pending-changes diff
clears. Per-device failures (including unimplemented real-device adapters that
raise :class:`NotImplementedError`) are collected and reported without aborting
the whole run.
"""

from __future__ import annotations

from ...domain.interfaces import (
    AppliedConfigStore,
    ConfigRepository,
    DeviceAdapterFactory,
)
from ..dtos import ApplyResult, DeviceApplyResult


class ApplyConfig:
    """Provision devices with the desired configuration."""

    def __init__(
        self,
        config: ConfigRepository,
        adapters: DeviceAdapterFactory,
        applied: AppliedConfigStore,
    ) -> None:
        self._config = config
        self._adapters = adapters
        self._applied = applied

    def execute(self) -> ApplyResult:
        devices = self._config.list_devices()
        results: list[DeviceApplyResult] = []

        for device in devices:
            adapter = self._adapters.for_device(device)
            try:
                adapter.push_config(device)
                results.append(DeviceApplyResult(device.id, device.name, ok=True))
            except NotImplementedError as exc:
                results.append(
                    DeviceApplyResult(
                        device.id,
                        device.name,
                        ok=False,
                        message=str(exc) or "Device driver not implemented yet.",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surface any adapter error per device
                results.append(
                    DeviceApplyResult(device.id, device.name, ok=False, message=str(exc))
                )

        result = ApplyResult(results=results)
        # Only record devices that applied successfully into the snapshot so the
        # diff continues to flag the ones that still need provisioning.
        if result.ok:
            self._applied.save(devices)
        else:
            ok_ids = {r.device_id for r in results if r.ok}
            if ok_ids:
                previously = {d.id: d for d in self._applied.load()}
                for device in devices:
                    if device.id in ok_ids:
                        previously[device.id] = device
                self._applied.save(list(previously.values()))
        return result
