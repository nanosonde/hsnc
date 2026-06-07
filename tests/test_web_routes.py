"""P0 safety net: render guardrail + golden-HTML byte-identity for every web page.

This boots the real Flask app against an in-process *mock* container (no SSH, no
broker) using a fixed fixture config, so the rendered HTML is deterministic. The
golden snapshots under ``tests/golden/`` are captured from the pre-refactor code
and MUST stay byte-identical through the REST split. Regenerate intentionally
with ``REGEN_GOLDEN=1 pytest tests/test_web_routes.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sdnman.infrastructure.container import Settings
from sdnman.presentation.app import create_app

from .harness import backend_api_client

_FIXTURES = Path(__file__).resolve().parent / "web_fixtures"
_GOLDEN = Path(__file__).resolve().parent / "golden"

# Every GET page in the app, with a stable golden-file name.
_GET_PAGES = [
    ("dashboard", "/"),
    ("devices", "/devices"),
    ("device_detail", "/devices/switch-1"),
    ("device_edit", "/devices/switch-1/edit"),
    ("clients", "/clients"),
    ("topology", "/topology"),
    ("backup", "/backup"),
    ("pending", "/config/pending"),
    ("history", "/config/history"),
]


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        config_dir=_FIXTURES,
        data_dir=tmp_path,
        use_mock_devices=True,
        baseline_on_start=False,
    )
    api_client, container = backend_api_client(settings)
    flask_app = create_app(settings, api_client=api_client)
    flask_app.config["READ_ONLY"] = True
    flask_app.config["TESTING"] = True
    try:
        yield flask_app
    finally:
        container.close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.data
    return client


def _check_golden(name: str, html: str) -> None:
    _GOLDEN.mkdir(exist_ok=True)
    path = _GOLDEN / f"{name}.html"
    if os.environ.get("REGEN_GOLDEN") or not path.exists():
        path.write_text(html, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    assert html == expected, (
        f"Golden HTML mismatch for {name!r}. The rendered page changed.\n"
        f"If this change is intended, regenerate with REGEN_GOLDEN=1."
    )


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<form" in html and "password" in html
    _check_golden("login", html)


def test_unauthenticated_redirects_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["Location"]


@pytest.mark.parametrize("name,path", _GET_PAGES)
def test_get_page_renders_and_matches_golden(auth_client, name, path):
    resp = auth_client.get(path)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    html = resp.get_data(as_text=True)
    _check_golden(name, html)


def test_clients_htmx_partial_matches_golden(auth_client):
    resp = auth_client.get("/clients", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    _check_golden("clients_partial", resp.get_data(as_text=True))


def test_read_only_blocks_apply(auth_client):
    resp = auth_client.post("/config/apply", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_read_only_blocks_apply_device(auth_client):
    resp = auth_client.post("/config/apply/switch-1", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_backup_export_returns_zip(auth_client):
    resp = auth_client.get("/backup/export")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] in (
        "application/zip",
        "application/octet-stream",
    )
