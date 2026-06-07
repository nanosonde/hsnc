"""Tests for the connection pool, runtime-store monitoring and baseline read."""

from __future__ import annotations

import time
from dataclasses import replace

from hsnc.devices.connection_pool import ConnectionPool
from hsnc.devices.runtime_monitoring import (
    RuntimeStoreMonitoringProvider,
)
from hsnc.entities import Client, Device, SwitchPort, Vlan
from hsnc.enums import ConnectionType, DeviceKind, DeviceStatus, PortMode
from hsnc.interfaces import DeviceAdapter, DeviceAdapterFactory
from hsnc.persistence.sqlite_runtime_store import SqliteRuntimeStore
from hsnc.use_cases.baseline import ReadBaseline
from hsnc.value_objects import IpAddress, MacAddress

from .fakes import (
    FakeApplyHistoryStore,
    FakeConfigRepository,
)


def _switch() -> Device:
    return Device(
        id="switch-1",
        name="SW",
        kind=DeviceKind.SWITCH,
        ip=IpAddress("192.168.50.2"),
        vlans=[Vlan(10, "Mgmt", "192.168.10.0/24")],
        ports=[SwitchPort(number=1, name="up", mode=PortMode.TRUNK, pvid=1, tagged_vlans=[10])],
    )


class _RecordingAdapter(DeviceAdapter):
    """Returns canned read config and records pushed devices."""

    def __init__(self, read: Device) -> None:
        self._read = read
        self.pushed: list[Device] = []

    def supports(self, device: Device) -> bool:
        return True

    def fetch_config(self, device: Device) -> Device:
        return self._read

    def push_config(self, device: Device) -> None:
        self.pushed.append(device)


class _Factory(DeviceAdapterFactory):
    def __init__(self, adapter: DeviceAdapter) -> None:
        self._adapter = adapter

    def for_device(self, device: Device) -> DeviceAdapter:
        return self._adapter


# -- connection pool -----------------------------------------------------


class _FlakyRunner:
    """Fails to connect for the first ``fail_times`` attempts, then succeeds."""

    def __init__(self, fail_times: int) -> None:
        self._remaining = fail_times
        self.closed = False

    def ensure_connected(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            raise OSError("connection refused")

    def keepalive(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


def test_connection_pool_reconnects_after_failure():
    device = _switch()
    runner = _FlakyRunner(fail_times=2)
    pool = ConnectionPool(
        runner_for=lambda d: runner,
        devices_provider=lambda: [device],
        keepalive_interval=0.02,
        backoff_initial=0.01,
        backoff_max=0.05,
    )
    pool.start()
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            snap = pool.snapshot()
            if snap and snap[0]["connected"]:
                break
            time.sleep(0.02)
        snap = pool.snapshot()
        assert snap[0]["connected"] is True
        assert snap[0]["failures"] >= 1
    finally:
        pool.stop()
    assert runner.closed is True


# -- runtime-store monitoring (web read path) ----------------------------


def test_runtime_store_monitoring_reads_latest(tmp_path):
    from datetime import UTC, datetime

    store = SqliteRuntimeStore(tmp_path / "rt.db")
    device = _switch()
    now = datetime.now(UTC)
    online = replace(device, status=DeviceStatus.CONNECTED, uptime_seconds=123)
    store.record_device_status(online, now)
    client = Client(
        id="switch-1-aa",
        name="laptop",
        mac=MacAddress("AA:BB:CC:00:00:01"),
        connection=ConnectionType.WIRED,
        status=DeviceStatus.CONNECTED,
        ip=IpAddress("192.168.50.20"),
        ap_or_port="port 1",
    )
    store.record_client_session(client, now, device_id="switch-1")

    provider = RuntimeStoreMonitoringProvider(store)
    status = provider.fetch_status(device)
    assert status.status is DeviceStatus.CONNECTED
    assert status.uptime_seconds == 123

    clients = provider.fetch_clients(device)
    assert len(clients) == 1
    assert clients[0].mac == MacAddress("AA:BB:CC:00:00:01")
    assert clients[0].ap_or_port == "port 1"
    store.close()


def test_runtime_store_monitoring_unknown_when_empty(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "rt.db")
    provider = RuntimeStoreMonitoringProvider(store)
    status = provider.fetch_status(_switch())
    assert status.status is DeviceStatus.UNKNOWN
    assert provider.fetch_clients(_switch()) == []
    store.close()


# -- baseline use case ---------------------------------------------------


def test_read_baseline_records_when_changed(site, users):
    device = _switch()
    read = replace(device, model="Read Model", firmware="1.0")
    repo = FakeConfigRepository(site, users, [device])
    from .fakes import FakeAppliedConfigStore

    current = FakeAppliedConfigStore([])
    history = FakeApplyHistoryStore()
    baseline = ReadBaseline(repo, _Factory(_RecordingAdapter(read)), current, history)

    result = baseline.execute()

    assert result.changed is True
    assert result.recorded is True
    assert len(result.read) == 1
    assert current.load()[0].model == "Read Model"
    assert history.events[0].action == "baseline"


def test_read_baseline_noop_when_unchanged(site, users):
    device = _switch()
    read = replace(device, model="Same", firmware="1.0")
    repo = FakeConfigRepository(site, users, [device])
    from .fakes import FakeAppliedConfigStore

    current = FakeAppliedConfigStore([read])
    history = FakeApplyHistoryStore()
    baseline = ReadBaseline(repo, _Factory(_RecordingAdapter(read)), current, history)

    result = baseline.execute()

    assert result.changed is False
    assert result.recorded is False
    assert history.events == []
