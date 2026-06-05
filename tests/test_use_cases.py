"""Tests for the application use cases using in-memory fakes."""

from __future__ import annotations

from datetime import UTC, datetime

from sdnman.application.services import NetworkStateService
from sdnman.application.use_cases.authenticate_user import AuthenticateUser
from sdnman.application.use_cases.get_dashboard_summary import GetDashboardSummary
from sdnman.application.use_cases.get_topology import GetTopology
from sdnman.application.use_cases.list_clients import ListClients
from sdnman.application.use_cases.list_devices import (
    GetDeviceDetail,
    ListDevices,
)
from sdnman.application.use_cases.poll_device_state import PollDeviceState

from .fakes import FakeRuntimeStore, FakeTopologyProvider


def _network(config, monitoring) -> NetworkStateService:
    return NetworkStateService(config, monitoring)


def test_authenticate_success(config):
    def verify(password, password_hash):
        return password_hash == f"hash-{password}"

    use_case = AuthenticateUser(config, verify)
    result = use_case.execute("admin", "admin")
    assert result is not None
    assert result.role == "admin"


def test_authenticate_wrong_password(config):
    use_case = AuthenticateUser(config, lambda p, h: False)
    assert use_case.execute("admin", "nope") is None


def test_authenticate_unknown_user(config):
    use_case = AuthenticateUser(config, lambda p, h: True)
    assert use_case.execute("ghost", "x") is None


def test_dashboard_summary(config, monitoring):
    network = _network(config, monitoring)
    runtime = FakeRuntimeStore()
    summary = GetDashboardSummary(config, network, runtime).execute()

    stats = {s.label: s.value for s in summary.stats}
    assert stats["Switches"] == "1"
    assert stats["Clients"] == "6"
    assert summary.admin_count == 2
    assert summary.device_count == 2


def test_list_devices_includes_client_count(config, monitoring):
    network = _network(config, monitoring)
    rows = ListDevices(network).execute()
    by_id = {r.id: r for r in rows}
    assert by_id["switch-1"].client_count == 6
    assert by_id["gateway-1"].client_count == 0


def test_get_device_detail(config, monitoring):
    network = _network(config, monitoring)
    detail = GetDeviceDetail(network).execute("switch-1")
    assert detail is not None
    assert detail.row.name == "TL-SG2210P"


def test_get_device_detail_missing(config, monitoring):
    network = _network(config, monitoring)
    assert GetDeviceDetail(network).execute("nope") is None


def test_list_clients_pagination(config, monitoring):
    network = _network(config, monitoring)
    paged = ListClients(network).execute(page=1, page_size=4)
    assert paged.total == 6
    assert len(paged.rows) == 4
    assert paged.total_pages == 2


def test_list_clients_search(config, monitoring):
    network = _network(config, monitoring)
    paged = ListClients(network).execute(search="client-3")
    assert paged.total == 1
    assert paged.rows[0].name == "client-3"


def test_network_caches_live_scrapes_within_ttl(config):
    from sdnman.domain.interfaces import MonitoringProvider, MonitoringProviderFactory

    class _CountingProvider(MonitoringProvider):
        def __init__(self) -> None:
            self.status_calls = 0
            self.client_calls = 0

        def fetch_status(self, device):
            self.status_calls += 1
            return device

        def fetch_clients(self, device):
            self.client_calls += 1
            return []

    class _Factory(MonitoringProviderFactory):
        def __init__(self, provider):
            self._provider = provider

        def for_device(self, device):
            return self._provider

    provider = _CountingProvider()
    now = {"t": 1000.0}
    network = NetworkStateService(
        config, _Factory(provider), cache_ttl_seconds=30.0, clock=lambda: now["t"]
    )
    device_count = len(config.list_devices())

    # Two sweeps within the TTL only scrape each device once.
    network.devices()
    network.devices()
    assert provider.status_calls == device_count

    # After the TTL expires, the next sweep re-scrapes.
    now["t"] += 31.0
    network.devices()
    assert provider.status_calls == device_count * 2


def test_network_without_ttl_always_scrapes(config):
    from sdnman.domain.interfaces import MonitoringProvider, MonitoringProviderFactory

    class _CountingProvider(MonitoringProvider):
        def __init__(self) -> None:
            self.status_calls = 0

        def fetch_status(self, device):
            self.status_calls += 1
            return device

        def fetch_clients(self, device):
            return []

    class _Factory(MonitoringProviderFactory):
        def __init__(self, provider):
            self._provider = provider

        def for_device(self, device):
            return self._provider

    provider = _CountingProvider()
    network = NetworkStateService(config, _Factory(provider))  # default TTL=0
    device_count = len(config.list_devices())

    network.devices()
    network.devices()
    assert provider.status_calls == device_count * 2


def test_topology(config, monitoring):
    network = _network(config, monitoring)
    view = GetTopology(network, FakeTopologyProvider()).execute()
    node_ids = {n.id for n in view.nodes}
    assert "internet" in node_ids
    assert "switch-1" in node_ids


def test_poll_device_state(config, monitoring):
    network = _network(config, monitoring)
    runtime = FakeRuntimeStore()
    count = PollDeviceState(
        network, runtime, clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)
    ).execute()
    assert count == 2
    assert len(runtime.client_sessions) == 6
    assert len(runtime.failures) == 3
