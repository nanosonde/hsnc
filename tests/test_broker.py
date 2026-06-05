"""Tests for the Device Broker: IPC server/client, proxy adapter, pool, baseline."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

from sdnman.application.use_cases.baseline import ReadBaseline
from sdnman.domain.entities import Client, Device, SwitchPort, Vlan
from sdnman.domain.enums import ConnectionType, DeviceKind, DeviceStatus, PortMode
from sdnman.domain.interfaces import DeviceAdapter, DeviceAdapterFactory
from sdnman.domain.value_objects import IpAddress, MacAddress
from sdnman.infrastructure.broker.client import (
    BrokerClient,
    BrokerRequestError,
    BrokerUnavailableError,
)
from sdnman.infrastructure.broker.connection_pool import ConnectionPool
from sdnman.infrastructure.broker.proxy_adapter import BrokerProxyAdapterFactory
from sdnman.infrastructure.broker.server import BrokerApi, serve
from sdnman.infrastructure.devices.runtime_monitoring import (
    RuntimeStoreMonitoringProvider,
)
from sdnman.infrastructure.persistence.sqlite_runtime_store import SqliteRuntimeStore

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


@pytest.fixture
def broker_server(tmp_path, site, users):
    """A running broker IPC server over a real Unix socket."""
    device = _switch()
    read = replace(device, model="JetStream X", firmware="9.9", ssids=[])
    adapter = _RecordingAdapter(read)
    repo = FakeConfigRepository(site, users, [device])
    api = BrokerApi(repo, _Factory(adapter))
    socket_path = tmp_path / "broker.sock"
    server = serve(socket_path, api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield socket_path, adapter, read
    finally:
        server.shutdown()
        server.server_close()


def test_broker_health(broker_server):
    socket_path, _adapter, _read = broker_server
    client = BrokerClient(socket_path)
    assert client.health()["status"] == "ok"


def test_broker_read_config(broker_server):
    socket_path, _adapter, read = broker_server
    client = BrokerClient(socket_path)
    payload = client.read_config("switch-1")
    assert payload["model"] == "JetStream X"
    assert payload["vlans"][0]["vlan_id"] == 10


def test_broker_read_unknown_device(broker_server):
    socket_path, _adapter, _read = broker_server
    client = BrokerClient(socket_path)
    with pytest.raises(BrokerRequestError) as exc:
        client.read_config("nope")
    assert exc.value.status == 404


def test_proxy_adapter_fetch_and_push(broker_server):
    socket_path, adapter, _read = broker_server
    factory = BrokerProxyAdapterFactory(BrokerClient(socket_path))
    device = _switch()

    proxy = factory.for_device(device)
    fetched = proxy.fetch_config(device)
    assert fetched.model == "JetStream X"
    assert fetched.vlans[0].vlan_id == 10

    proxy.push_config(replace(device, ssids=["Corp"]))
    assert adapter.pushed, "broker should have received the push"
    assert adapter.pushed[0].id == "switch-1"


def test_broker_client_unavailable(tmp_path):
    client = BrokerClient(tmp_path / "missing.sock", timeout=0.5)
    with pytest.raises(BrokerUnavailableError):
        client.health()


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
