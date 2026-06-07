"""Frontend API-client tests.

Exercises the full wire path: the client serializes a request, the *real*
backend handles it against a mock container, and the client deserializes the
JSON into web view types. This locks the round-trip contract between backend
DTOs and frontend view types, plus the error-envelope re-raising.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from sdnman.backend.app import create_api_app
from sdnman.infrastructure.container import Container, Settings
from sdnman.presentation import viewtypes as vt
from sdnman.presentation.api_client import ApiClient, DeviceNotFoundError

_FIXTURES = Path(__file__).resolve().parent / "web_fixtures"


class FlaskTestTransport:
    """Routes ApiClient requests through a Flask test client."""

    def __init__(self, client) -> None:
        self._client = client

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        resp = self._client.open(
            path,
            method=method,
            query_string=params,
            json=json,
            data=data,
            headers=headers or {},
        )
        return resp.status_code, resp.get_data()


@pytest.fixture
def api(tmp_path):
    settings = Settings(
        config_dir=_FIXTURES,
        data_dir=tmp_path,
        use_mock_devices=True,
        baseline_on_start=False,
    )
    container = Container(settings, profile="api")
    container.poll_device_state.execute()
    app = create_api_app(settings, container=container)
    client = ApiClient(transport=FlaskTestTransport(app.test_client()))
    try:
        yield client
    finally:
        container.close()


def test_login_valid_and_invalid(api):
    user = api.login("admin", "admin")
    assert isinstance(user, vt.AuthenticatedUser)
    assert user.username == "admin"
    assert api.login("admin", "wrong") is None


def test_dashboard(api):
    summary = api.get_dashboard()
    assert isinstance(summary, vt.DashboardSummary)
    assert summary.site_name == "Default"


def test_devices_and_detail(api):
    rows = api.list_devices()
    assert {r.id for r in rows} >= {"gateway-1", "switch-1", "ap-1", "switch-2"}
    detail = api.get_device_detail("switch-1")
    assert isinstance(detail, vt.DeviceDetail)
    assert detail.row.id == "switch-1"
    assert api.get_device_detail("nope") is None


def test_clients_topology_history(api):
    paged = api.list_clients(page=1, page_size=5)
    assert isinstance(paged, vt.PagedClients)
    assert paged.page_size == 5
    topo = api.get_topology()
    assert isinstance(topo, vt.TopologyView)
    assert api.list_apply_history() == []


def test_diff_and_plan(api):
    assert isinstance(api.get_config_diff(), vt.ConfigDiff)
    assert isinstance(api.get_apply_plan(), vt.ApplyPlan)


def test_save_and_delete_vlan(api):
    api.save_vlan("switch-1", vlan_id=55, name="LAB", subnet="10.55.0.0/24")
    api.delete_vlan("switch-1", 55)


def test_save_vlan_unknown_device_raises(api):
    with pytest.raises(DeviceNotFoundError):
        api.save_vlan("ghost", vlan_id=10, name="X", subnet="")


def test_apply_revert_sync(api):
    result = api.apply_config(username="admin")
    assert isinstance(result, vt.ApplyResult)
    assert isinstance(api.revert_changes(), int)
    assert isinstance(api.sync_device_config(username="admin"), vt.SyncResult)


def test_backup_round_trip(api):
    archive = api.export_backup()
    assert zipfile.is_zipfile(BytesIO(archive))
    api.import_backup(archive)
