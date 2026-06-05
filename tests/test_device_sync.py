"""Tests for re-reading device config and deleting devices."""

from __future__ import annotations

from sdnman.application.use_cases.delete_device import DeleteDevice
from sdnman.application.use_cases.sync_device_config import SyncDeviceConfig
from sdnman.domain.entities import Device
from sdnman.domain.enums import DeviceKind
from sdnman.domain.interfaces import DeviceAdapter, DeviceAdapterFactory
from sdnman.domain.value_objects import MacAddress

from .fakes import (
    FakeAdapterFactory,
    FakeAppliedConfigStore,
    FakeApplyHistoryStore,
    FakeConfigWriter,
    FakeDeviceAdapter,
)


def test_sync_writes_config_updates_snapshot_and_records_reread(config):
    writer = FakeConfigWriter(config)
    applied = FakeAppliedConfigStore()
    history = FakeApplyHistoryStore()
    adapters = FakeAdapterFactory(FakeDeviceAdapter())

    result = SyncDeviceConfig(config, adapters, writer, applied, history).execute(
        username="admin"
    )

    assert result.ok
    assert {r.device_id for r in result.results} == {"switch-1", "gateway-1"}
    # devices were written back to the inventory
    assert {d.id for d in writer.saved} == {"switch-1", "gateway-1"}
    # the applied snapshot is updated so the re-read produces no pending diff
    assert {d.id for d in applied.load()} == {"switch-1", "gateway-1"}
    # the run is recorded as a re-read
    assert len(history.events) == 1
    assert history.events[0].action == "reread"
    assert history.events[0].ok


def test_sync_single_device_only_touches_that_device(config):
    writer = FakeConfigWriter(config)
    applied = FakeAppliedConfigStore()
    history = FakeApplyHistoryStore()
    adapters = FakeAdapterFactory(FakeDeviceAdapter())

    result = SyncDeviceConfig(config, adapters, writer, applied, history).execute(
        device_ids=["switch-1"]
    )

    assert {r.device_id for r in result.results} == {"switch-1"}
    assert {d.id for d in applied.load()} == {"switch-1"}


def test_sync_surfaces_not_implemented_as_failure(config):
    class _RaisingAdapter(DeviceAdapter):
        def supports(self, device: Device) -> bool:
            return True

        def fetch_status(self, device: Device) -> Device:
            return device

        def fetch_config(self, device: Device) -> Device:
            raise NotImplementedError("Driver not implemented yet.")

        def fetch_clients(self, device):
            return []

        def push_config(self, device: Device) -> None:
            return None

    class _RaisingFactory(DeviceAdapterFactory):
        def for_device(self, device: Device) -> DeviceAdapter:
            return _RaisingAdapter()

    writer = FakeConfigWriter(config)
    applied = FakeAppliedConfigStore()
    history = FakeApplyHistoryStore()

    result = SyncDeviceConfig(
        config, _RaisingFactory(), writer, applied, history
    ).execute()

    assert not result.ok
    assert result.failures
    assert "not implemented" in result.failures[0].message.lower()
    # nothing written or snapshotted on failure
    assert writer.saved == []
    assert applied.load() == []
    # the failed run is still recorded as a re-read
    assert history.events[0].action == "reread"
    assert not history.events[0].ok


def test_delete_device_removes_from_inventory_and_snapshot(config):
    writer = FakeConfigWriter(config)
    existing = config.list_devices()
    applied = FakeAppliedConfigStore(existing)

    DeleteDevice(writer, applied).execute("switch-1")

    assert config.get_device("switch-1") is None
    assert {d.id for d in applied.load()} == {"gateway-1"}


def test_mock_adapter_fetch_config_returns_device():
    from sdnman.infrastructure.devices.mock_adapter import MockDeviceAdapter

    device = Device(
        id="switch-1",
        name="TL-SG2210P",
        kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
    )
    fresh = MockDeviceAdapter().fetch_config(device)
    assert fresh.id == "switch-1"
    assert fresh is device
