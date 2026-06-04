"""Tests for config diff and declarative apply workflow."""

from __future__ import annotations

import copy

from omada_clone.application.use_cases.apply_config import ApplyConfig, PlanApply
from omada_clone.application.use_cases.config_diff import GetConfigDiff
from omada_clone.domain.entities import Device, Vlan
from omada_clone.domain.enums import DeviceKind, DeviceStatus
from omada_clone.domain.interfaces import DeviceAdapter, DeviceAdapterFactory
from omada_clone.domain.value_objects import MacAddress

from .fakes import (
    FakeAppliedConfigStore,
    FakeApplyHistoryStore,
    FakeConfigRepository,
    FakeDeviceAdapter,
)


class _RaisingAdapter(DeviceAdapter):
    def supports(self, device: Device) -> bool:
        return True

    def fetch_status(self, device: Device) -> Device:
        return device

    def fetch_clients(self, device):
        return []

    def push_config(self, device: Device) -> None:
        raise NotImplementedError("Driver for this device is not implemented yet.")


class _RaisingFactory(DeviceAdapterFactory):
    def for_device(self, device: Device) -> DeviceAdapter:
        return _RaisingAdapter()


def test_diff_reports_added_devices_when_nothing_applied(config):
    diff = GetConfigDiff(config, FakeAppliedConfigStore()).execute()
    assert diff.has_changes
    assert diff.change_count == len(config.list_devices())
    assert all(d.state == "added" for d in diff.devices)


def test_diff_detects_modified_field(config, devices):
    applied = FakeAppliedConfigStore(devices=copy.deepcopy(devices))
    # mutate the desired config: add a VLAN to switch-1
    switch = config.get_device("switch-1")
    switch.vlans.append(Vlan(vlan_id=10, name="IoT", subnet="192.168.10.0/24"))

    diff = GetConfigDiff(config, applied).execute()
    assert diff.has_changes
    modified = [d for d in diff.devices if d.state == "modified"]
    assert len(modified) == 1
    assert modified[0].device_id == "switch-1"
    assert any(c.group == "VLANs" for c in modified[0].changes)


def test_apply_with_mock_clears_diff(config, adapters):
    applied = FakeAppliedConfigStore()
    history = FakeApplyHistoryStore()
    apply = ApplyConfig(config, adapters, applied, history)

    result = apply.execute(username="admin")
    assert result.ok
    assert len(result.results) == len(config.list_devices())

    diff = GetConfigDiff(config, applied).execute()
    assert not diff.has_changes
    # a history event is recorded with the acting user
    assert len(history.events) == 1
    assert history.events[0].username == "admin"
    assert history.events[0].ok


def test_apply_skips_unchanged_devices(config, adapters):
    applied = FakeAppliedConfigStore(devices=copy.deepcopy(config.list_devices()))
    history = FakeApplyHistoryStore()
    apply = ApplyConfig(config, adapters, applied, history)

    result = apply.execute(username="admin")
    # nothing differs -> nothing applied, nothing recorded
    assert result.ok
    assert result.results == []
    assert history.events == []


def test_apply_records_field_changes_for_history(config, adapters, devices):
    applied = FakeAppliedConfigStore(devices=copy.deepcopy(devices))
    history = FakeApplyHistoryStore()
    # one real change on switch-1
    switch = config.get_device("switch-1")
    switch.vlans.append(Vlan(vlan_id=10, name="IoT", subnet="192.168.10.0/24"))

    ApplyConfig(config, adapters, applied, history).execute(username="admin")

    assert len(history.events) == 1
    outcomes = history.events[0].outcomes
    # only the changed device is recorded
    assert [o.device_id for o in outcomes] == ["switch-1"]
    # and the specific field change is captured (granular VLAN row)
    assert any(c.field.startswith("VLAN ") for c in outcomes[0].changes)


def test_apply_surfaces_not_implemented_per_device(config):
    applied = FakeAppliedConfigStore()
    apply = ApplyConfig(config, _RaisingFactory(), applied, FakeApplyHistoryStore())

    result = apply.execute()
    assert not result.ok
    assert len(result.failures) == len(config.list_devices())
    assert "not implemented" in result.failures[0].message.lower()
    # nothing applied -> diff still dirty
    assert GetConfigDiff(config, applied).execute().has_changes


def test_apply_partial_success_records_only_ok_devices(devices):
    config = FakeConfigRepository(
        site=None,
        users=[],
        devices=[
            Device(
                id="ok-1",
                name="Good",
                kind=DeviceKind.SWITCH,
                mac=MacAddress("B0:4E:26:00:00:11"),
                status=DeviceStatus.CONNECTED,
            ),
            Device(
                id="bad-1",
                name="Bad",
                kind=DeviceKind.GATEWAY,
                mac=MacAddress("B0:4E:26:00:00:12"),
                status=DeviceStatus.CONNECTED,
            ),
        ],
    )

    class _MixedFactory(DeviceAdapterFactory):
        def for_device(self, device: Device) -> DeviceAdapter:
            if device.id == "bad-1":
                return _RaisingAdapter()
            return FakeDeviceAdapter({})

    applied = FakeAppliedConfigStore()
    result = ApplyConfig(config, _MixedFactory(), applied, FakeApplyHistoryStore()).execute()

    assert not result.ok
    assert {r.device_id for r in result.results if r.ok} == {"ok-1"}
    # only the successful device should be in the snapshot
    assert {d.id for d in applied.load()} == {"ok-1"}


def test_plan_reports_create_actions_when_nothing_applied(config, adapters):
    plan = PlanApply(config, FakeAppliedConfigStore(), adapters).execute()
    assert plan.has_actionable
    assert {i.action for i in plan.items} == {"create"}
    assert all(i.supported for i in plan.items)
    # dry-run must not record history or change the snapshot
    applied = FakeAppliedConfigStore()
    PlanApply(config, applied, adapters).execute()
    assert applied.load() == []


def test_plan_reports_noop_after_apply(config, adapters):
    applied = FakeAppliedConfigStore()
    ApplyConfig(config, adapters, applied, FakeApplyHistoryStore()).execute()
    plan = PlanApply(config, applied, adapters).execute()
    assert not plan.has_actionable
    assert {i.action for i in plan.items} == {"noop"}


def test_plan_marks_unsupported_devices(config):
    class _Unsupported(DeviceAdapter):
        def supports(self, device: Device) -> bool:
            return False

        def fetch_status(self, device: Device) -> Device:
            return device

        def fetch_clients(self, device):
            return []

        def push_config(self, device: Device) -> None:
            return None

    class _UnsupportedFactory(DeviceAdapterFactory):
        def for_device(self, device: Device) -> DeviceAdapter:
            return _Unsupported()

    plan = PlanApply(config, FakeAppliedConfigStore(), _UnsupportedFactory()).execute()
    assert not plan.has_actionable
    assert {i.action for i in plan.items} == {"unsupported"}


def test_per_device_apply_only_touches_that_device(config, adapters):
    applied = FakeAppliedConfigStore()
    history = FakeApplyHistoryStore()
    apply = ApplyConfig(config, adapters, applied, history)

    target = config.list_devices()[0]
    result = apply.execute(device_ids=[target.id], username="admin")
    assert result.ok
    assert len(result.results) == 1
    assert {d.id for d in applied.load()} == {target.id}
    # the others remain pending
    pending = {d.device_id for d in GetConfigDiff(config, applied).execute().devices}
    assert target.id not in pending
    assert len(history.events) == 1
