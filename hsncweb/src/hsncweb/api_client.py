"""Frontend HTTP client for the REST backend.

The web app holds **no** device or persistence logic: every read and write goes
through this client to the backend's ``/api`` surface. JSON responses are
deserialized into the web-local :mod:`viewtypes`; error envelopes are re-raised
as the same-named exceptions (with the same message) the in-process
implementation raised, so the blueprints' ``except``/``flash`` logic is unchanged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from . import viewtypes as vt


class ApiError(RuntimeError):
    """Raised for backend errors without a more specific mapped type."""


class DeviceNotFoundError(Exception):
    """Web-local mirror of the backend's ``DeviceNotFoundError``."""


class ConfigEditError(Exception):
    """Web-local mirror of the backend's ``ConfigEditError``."""


_EXCEPTIONS: dict[str, type[Exception]] = {
    "DeviceNotFoundError": DeviceNotFoundError,
    "ConfigEditError": ConfigEditError,
    "ValueError": ValueError,
}


class Transport(Protocol):
    """Sends one HTTP request and returns ``(status_code, body_bytes)``."""

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]: ...


class UrllibTransport:
    """Default transport over the standard library (no third-party deps)."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

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
        url = self._base + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        body = data
        req_headers = dict(headers or {})
        if json is not None:
            body = _json_bytes(json)
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


class ApiClient:
    """Typed facade over the backend ``/api`` endpoints."""

    def __init__(
        self, base_url: str = "", token: str = "", transport: Transport | None = None
    ) -> None:
        self._token = token.strip()
        self._transport = transport or UrllibTransport(base_url)

    # -- low-level ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        raw_body: bytes | None = None,
    ) -> tuple[int, bytes]:
        return self._transport.request(
            method,
            path,
            params=params,
            json=json_body,
            data=raw_body,
            headers=self._headers(),
        )

    def _json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        raw_body: bytes | None = None,
    ) -> Any:
        status, body = self._send(
            method, path, params=params, json_body=json_body, raw_body=raw_body
        )
        if status >= 400:
            self._raise(status, body)
        if not body:
            return None
        return json.loads(body)

    def _raise(self, status: int, body: bytes) -> None:
        type_name, message = _parse_error(body)
        exc_cls = _EXCEPTIONS.get(type_name)
        if exc_cls is not None:
            raise exc_cls(message)
        raise ApiError(message or f"Backend returned HTTP {status}")

    # -- reads -------------------------------------------------------------

    def get_site(self) -> dict[str, str]:
        return self._json("GET", "/api/site")

    def get_dashboard(self) -> vt.DashboardSummary:
        return vt.DashboardSummary.from_dict(self._json("GET", "/api/dashboard"))

    def get_config_diff(self) -> vt.ConfigDiff:
        return vt.ConfigDiff.from_dict(self._json("GET", "/api/config/diff"))

    def get_apply_plan(self) -> vt.ApplyPlan:
        return vt.ApplyPlan.from_dict(self._json("GET", "/api/config/plan"))

    def list_devices(self) -> list[vt.DeviceRow]:
        return [vt.DeviceRow.from_dict(r) for r in self._json("GET", "/api/devices")]

    def get_device_detail(self, device_id: str) -> vt.DeviceDetail | None:
        status, body = self._send("GET", f"/api/devices/{device_id}")
        if status == 404:
            return None
        if status >= 400:
            self._raise(status, body)
        return vt.DeviceDetail.from_dict(json.loads(body))

    def get_ssh_log(self, device_id: str, limit: int = 1000) -> vt.SshConsole | None:
        status, body = self._send(
            "GET", f"/api/devices/{device_id}/ssh-log", params={"limit": limit}
        )
        if status == 404:
            return None
        if status >= 400:
            self._raise(status, body)
        return vt.SshConsole.from_dict(json.loads(body))


    def list_clients(
        self, search: str = "", page: int = 1, page_size: int = 10
    ) -> vt.PagedClients:
        params = {"search": search, "page": page, "page_size": page_size}
        return vt.PagedClients.from_dict(self._json("GET", "/api/clients", params=params))

    def get_topology(self) -> vt.TopologyView:
        return vt.TopologyView.from_dict(self._json("GET", "/api/topology"))

    def list_apply_history(self, limit: int = 50) -> list[vt.ApplyEvent]:
        data = self._json("GET", "/api/history", params={"limit": limit})
        return [vt.ApplyEvent.from_dict(e) for e in data]

    # -- auth --------------------------------------------------------------

    def login(self, username: str, password: str) -> vt.AuthenticatedUser | None:
        status, body = self._send(
            "POST", "/api/auth/verify", json_body={"username": username, "password": password}
        )
        if status == 401:
            return None
        if status >= 400:
            self._raise(status, body)
        return vt.AuthenticatedUser.from_dict(json.loads(body))

    # -- config edits ------------------------------------------------------

    def save_vlan(self, device_id: str, vlan_id: int, name: str, subnet: str) -> None:
        self._json(
            "POST",
            f"/api/config/devices/{device_id}/vlans",
            json_body={"vlan_id": vlan_id, "name": name, "subnet": subnet},
        )

    def delete_vlan(self, device_id: str, vlan_id: int) -> None:
        self._json("POST", f"/api/config/devices/{device_id}/vlans/{vlan_id}/delete")

    def save_port(
        self,
        device_id: str,
        number: int,
        name: str,
        enabled: bool,
        mode: str,
        pvid: int,
        tagged_vlans: list[int],
    ) -> None:
        self._json(
            "POST",
            f"/api/config/devices/{device_id}/ports/{number}",
            json_body={
                "name": name,
                "enabled": enabled,
                "mode": mode,
                "pvid": pvid,
                "tagged_vlans": tagged_vlans,
            },
        )

    def save_ssids(self, device_id: str, ssids: list[str]) -> None:
        self._json(
            "POST",
            f"/api/config/devices/{device_id}/ssids",
            json_body={"ssids": ssids},
        )

    # -- apply / revert / sync / delete -----------------------------------

    def apply_config(
        self, device_ids: list[str] | None = None, username: str = ""
    ) -> vt.ApplyResult:
        body = {"device_ids": device_ids, "username": username}
        return vt.ApplyResult.from_dict(self._json("POST", "/api/config/apply", json_body=body))

    def revert_changes(self, device_ids: list[str] | None = None) -> int:
        body = {"device_ids": device_ids}
        data = self._json("POST", "/api/config/revert", json_body=body)
        return int(data["reverted"])

    def sync_device_config(
        self, device_ids: list[str] | None = None, username: str = ""
    ) -> vt.SyncResult:
        body = {"device_ids": device_ids, "username": username}
        return vt.SyncResult.from_dict(self._json("POST", "/api/devices/sync", json_body=body))

    def delete_device(self, device_id: str) -> None:
        self._json("POST", f"/api/devices/{device_id}/delete")

    # -- backup ------------------------------------------------------------

    def export_backup(self) -> bytes:
        status, body = self._send("GET", "/api/backup/export")
        if status >= 400:
            self._raise(status, body)
        return body

    def import_backup(self, archive_bytes: bytes) -> None:
        self._json("POST", "/api/backup/import", raw_body=archive_bytes)


def _parse_error(body: bytes) -> tuple[str, str]:
    try:
        payload = json.loads(body)
        error = payload.get("error", {})
        return error.get("type", ""), error.get("message", "")
    except (ValueError, AttributeError):
        return "", body.decode("utf-8", "replace")
