"""Backend REST API tests: JSON shapes, status codes, and error envelopes.

Boots the API app against an in-process *mock* container (no SSH) using the
fixed fixture config, runs one poll sweep to populate the runtime snapshot, then
exercises every endpoint through the Flask test client.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from sdnman.backend.app import create_api_app
from sdnman.infrastructure.container import Container, Settings

_FIXTURES = Path(__file__).resolve().parent / "web_fixtures"


@pytest.fixture
def container(tmp_path):
    settings = Settings(
        config_dir=_FIXTURES,
        data_dir=tmp_path,
        use_mock_devices=True,
        baseline_on_start=False,
    )
    c = Container(settings)
    # Seed the runtime snapshot the way the poll loop would on a live system.
    c.poll_device_state.execute()
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def client(container):
    app = create_api_app(container.settings, container=container)
    return app.test_client()


def test_health_reports_mock_mode(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["mock"] is True
    assert body["connections"] == []


def test_auth_verify_accepts_valid_credentials(client):
    resp = client.post("/api/auth/verify", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"


def test_auth_verify_rejects_bad_credentials(client):
    resp = client.post("/api/auth/verify", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


def test_dashboard_returns_summary(client):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["site_name"] == "Default"
    assert isinstance(body["stats"], list)


def test_devices_list_and_detail(client):
    resp = client.get("/api/devices")
    assert resp.status_code == 200
    rows = resp.get_json()
    ids = {row["id"] for row in rows}
    assert {"gateway-1", "switch-1", "ap-1", "switch-2"} <= ids

    detail = client.get("/api/devices/switch-1")
    assert detail.status_code == 200
    assert detail.get_json()["row"]["id"] == "switch-1"


def test_device_detail_unknown_returns_404_envelope(client):
    resp = client.get("/api/devices/does-not-exist")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_clients_paged(client):
    resp = client.get("/api/clients?page=1&page_size=5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert "rows" in body


def test_topology_and_history_and_diff_and_plan(client):
    assert client.get("/api/topology").status_code == 200
    assert client.get("/api/history").get_json() == []
    assert client.get("/api/config/diff").status_code == 200
    assert client.get("/api/config/plan").status_code == 200


def test_save_vlan_then_delete(client):
    resp = client.post(
        "/api/config/devices/switch-1/vlans",
        json={"vlan_id": 42, "name": "TEST", "subnet": "192.168.42.0/24"},
    )
    assert resp.status_code == 204
    delete = client.post("/api/config/devices/switch-1/vlans/42/delete")
    assert delete.status_code == 204


def test_save_vlan_unknown_device_returns_404(client):
    resp = client.post(
        "/api/config/devices/ghost/vlans",
        json={"vlan_id": 10, "name": "X", "subnet": ""},
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"]["type"] == "DeviceNotFoundError"


def test_save_vlan_invalid_value_returns_400(client):
    resp = client.post(
        "/api/config/devices/switch-1/vlans",
        json={"vlan_id": "not-an-int", "name": "X", "subnet": ""},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["type"] == "ValueError"


def test_apply_revert_sync(client):
    apply = client.post("/api/config/apply", json={"username": "admin"})
    assert apply.status_code == 200
    assert "results" in apply.get_json()

    revert = client.post("/api/config/revert", json={})
    assert revert.status_code == 200
    assert "reverted" in revert.get_json()

    sync = client.post("/api/devices/sync", json={"username": "admin"})
    assert sync.status_code == 200
    assert "results" in sync.get_json()


def test_delete_device_unknown_returns_404(client):
    resp = client.post("/api/devices/ghost/delete")
    assert resp.status_code == 404


def test_backup_export_then_import(client):
    export = client.get("/api/backup/export")
    assert export.status_code == 200
    assert export.headers["Content-Type"] == "application/zip"
    archive = export.get_data()
    assert zipfile.is_zipfile(__import__("io").BytesIO(archive))

    imported = client.post(
        "/api/backup/import",
        data=archive,
        content_type="application/zip",
    )
    assert imported.status_code == 204


def test_responses_are_valid_json(client):
    # The wire contract must always round-trip through JSON.
    body = client.get("/api/dashboard").get_data(as_text=True)
    assert json.loads(body) is not None
