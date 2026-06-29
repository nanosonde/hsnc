"""P0 safety net: render guardrail + golden-HTML byte-identity for every web page.

This boots the real Flask app against an in-process *mock* container (no SSH)
using a fixed fixture config, so the rendered HTML is deterministic. The
golden snapshots under ``tests/golden/`` are captured from the pre-refactor code
and MUST stay byte-identical through the REST split. Regenerate intentionally
with ``REGEN_GOLDEN=1 pytest tests/test_web_routes.py``.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest
from hsnc.container import Settings

from hsncweb.app import create_app

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
    flask_app = create_app(api_client=api_client)
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


def test_ssh_log_renders_terminal_partial(auth_client):
    resp = auth_client.get("/devices/switch-1/ssh-log", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="terminal"' in html
    # Mock devices -> no live SSH session, so the empty-state message shows.
    assert "No SSH activity (mock devices)." in html


def test_ssh_log_unknown_device_404(auth_client):
    resp = auth_client.get("/devices/does-not-exist/ssh-log")
    assert resp.status_code == 404



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


# -- CSRF protection ---------------------------------------------------------
# The golden/route fixtures above run with CSRF disabled (app.testing). These
# build a second app with protection explicitly enabled to exercise the guard.


@pytest.fixture
def csrf_app(tmp_path):
    settings = Settings(
        config_dir=_FIXTURES,
        data_dir=tmp_path,
        use_mock_devices=True,
        baseline_on_start=False,
    )
    api_client, container = backend_api_client(settings)
    flask_app = create_app(api_client=api_client)
    flask_app.config["READ_ONLY"] = False
    flask_app.config["TESTING"] = True
    flask_app.config["CSRF_ENABLED"] = True
    try:
        yield flask_app
    finally:
        container.close()


def test_post_without_csrf_token_is_rejected(csrf_app):
    client = csrf_app.test_client()
    resp = client.post("/login", data={"username": "admin", "password": "admin"})
    assert resp.status_code == 400


def test_post_with_csrf_token_is_accepted(csrf_app):
    client = csrf_app.test_client()
    page = client.get("/login").get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match, "login form should embed a CSRF token when protection is enabled"
    token = match.group(1)
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "admin", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.data


def test_get_requests_need_no_csrf_token(csrf_app):
    client = csrf_app.test_client()
    assert client.get("/login").status_code == 200


# -- Input validation guards -------------------------------------------------


def test_save_vlan_missing_field_flashes_not_500(auth_client):
    # Omitting the required vlan_id must yield a user-facing redirect, not a 500.
    resp = auth_client.post(
        "/devices/switch-1/vlans",
        data={"name": "x", "subnet": ""},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.data


def test_save_vlan_out_of_range_flashes_not_500(auth_client):
    resp = auth_client.post(
        "/devices/switch-1/vlans",
        data={"vlan_id": "99999", "name": "x"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.data


def test_clients_page_size_is_clamped(auth_client):
    # An absurd page_size must not 500; it is clamped server-side.
    resp = auth_client.get("/clients?page_size=999999")
    assert resp.status_code == 200


def test_oversized_upload_is_rejected(app):
    app.config["MAX_CONTENT_LENGTH"] = 64
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin"})
    resp = client.post(
        "/backup/import",
        data={"archive": (io.BytesIO(b"x" * 4096), "big.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413


def test_repeated_failed_logins_are_rate_limited(app):
    app.config["LOGIN_RATELIMITER"].max_attempts = 2
    client = app.test_client()
    bad = {"username": "admin", "password": "wrong"}
    assert client.post("/login", data=bad).status_code == 401
    assert client.post("/login", data=bad).status_code == 401
    # Third attempt is blocked before the credentials are even checked.
    assert client.post("/login", data=bad).status_code == 429


def test_successful_login_clears_rate_limit_counter(app):
    app.config["LOGIN_RATELIMITER"].max_attempts = 2
    client = app.test_client()
    assert client.post("/login", data={"username": "admin", "password": "wrong"}).status_code == 401
    # A success resets the counter so later failures start from zero again.
    assert client.post("/login", data={"username": "admin", "password": "admin"}).status_code in (
        302,
        303,
    )
    assert client.post("/login", data={"username": "admin", "password": "wrong"}).status_code == 401



