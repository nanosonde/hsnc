"""Use cases for the apply workflow: dry-run planning and applying config.

``PlanApply`` produces a per-device preview (no side effects). ``ApplyConfig``
pushes the desired configuration through each device's :class:`DeviceAdapter`,
updates the applied snapshot for successful devices, and records the run in the
apply history. Per-device failures (including unimplemented real-device adapters
that raise :class:`NotImplementedError`) are collected without aborting the run.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from ...domain.entities import ApplyEvent, ApplyOutcome
from ...domain.interfaces import (
    AppliedConfigStore,
    ApplyHistoryStore,
    ConfigRepository,
    DeviceAdapterFactory,
)
from ..dtos import ApplyPlan, ApplyPlanItem, ApplyResult, DeviceApplyResult
from .config_diff import GetConfigDiff


class PlanApply:
    """Dry-run: compute the action that would be taken for each device."""

    def __init__(
        self,
        config: ConfigRepository,
        applied: AppliedConfigStore,
        adapters: DeviceAdapterFactory,
    ) -> None:
        self._config = config
        self._applied = applied
        self._adapters = adapters

    def execute(self, device_ids: Iterable[str] | None = None) -> ApplyPlan:
        selected = set(device_ids) if device_ids is not None else None
        diff = GetConfigDiff(self._config, self._applied).execute()
        diff_by_id = {d.device_id: d for d in diff.devices}

        items: list[ApplyPlanItem] = []
        for device in self._config.list_devices():
            if selected is not None and device.id not in selected:
                continue
            supported = self._adapters.for_device(device).supports(device)
            device_diff = diff_by_id.get(device.id)
            if device_diff is None:
                action, change_count = "noop", 0
            elif device_diff.state == "added":
                action, change_count = "create", len(device_diff.changes)
            else:  # modified
                action, change_count = "update", len(device_diff.changes)
            if not supported:
                action = "unsupported"
            items.append(
                ApplyPlanItem(
                    device_id=device.id,
                    device_name=device.name,
                    action=action,
                    supported=supported,
                    change_count=change_count,
                )
            )
        return ApplyPlan(items=items)


class ApplyConfig:
    """Provision devices with the desired configuration."""

    def __init__(
        self,
        config: ConfigRepository,
        adapters: DeviceAdapterFactory,
        applied: AppliedConfigStore,
        history: ApplyHistoryStore,
    ) -> None:
        self._config = config
        self._adapters = adapters
        self._applied = applied
        self._history = history

    def execute(
        self,
        device_ids: Iterable[str] | None = None,
        username: str = "",
    ) -> ApplyResult:
        selected = set(device_ids) if device_ids is not None else None
        devices = [
            d
            for d in self._config.list_devices()
            if selected is None or d.id in selected
        ]
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

        # Merge successfully-applied devices into the existing snapshot so a
        # partial or per-device apply keeps the rest of the snapshot intact and
        # the diff continues to flag what still needs provisioning.
        ok_ids = {r.device_id for r in results if r.ok}
        if ok_ids:
            snapshot = {d.id: d for d in self._applied.load()}
            for device in devices:
                if device.id in ok_ids:
                    snapshot[device.id] = device
            self._applied.save(list(snapshot.values()))

        if results:
            self._history.record_apply_event(
                ApplyEvent(
                    applied_at=datetime.now(UTC),
                    username=username,
                    ok=result.ok,
                    outcomes=[
                        ApplyOutcome(r.device_id, r.device_name, r.ok, r.message)
                        for r in results
                    ],
                )
            )
        return result
