"""Tests for config diff and declarative apply workflow."""

from __future__ import annotations

import copy

from omada_clone.application.use_cases.apply_config import ApplyConfig
from omada_clone.application.use_cases.config_diff import GetConfigDiff
from omada_clone.domain.entities import Device, Vlan
from omada_clone.domain.enums import DeviceKind, DeviceStatus
from omada_clone.domain.interfaces import DeviceAdapter, DeviceAdapterFactory
from omada_clone.domain.value_objects import MacAddress

from .fakes import (
    FakeAppliedConfigStore,
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
    assert any(c.field == "VLANs" for c in modified[0].changes)


def test_apply_with_mock_clears_diff(config, adapters):
    applied = FakeAppliedConfigStore()
    apply = ApplyConfig(config, adapters, applied)

    result = apply.execute()
    assert result.ok
    assert len(result.results) == len(config.list_devices())

    diff = GetConfigDiff(config, applied).execute()
    assert not diff.has_changes


def test_apply_surfaces_not_implemented_per_device(config):
    applied = FakeAppliedConfigStore()
    apply = ApplyConfig(config, _RaisingFactory(), applied)

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
    result = ApplyConfig(config, _MixedFactory(), applied).execute()

    assert not result.ok
    assert {r.device_id for r in result.results if r.ok} == {"ok-1"}
    # only the successful device should be in the snapshot
    assert {d.id for d in applied.load()} == {"ok-1"}
