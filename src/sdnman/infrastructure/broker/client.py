"""Web-side client for the Device Broker IPC API.

A thin wrapper over :class:`http.client.HTTPConnection` taught to dial an
AF_UNIX socket. Used by :class:`~.proxy_adapter.BrokerProxyDeviceAdapter` so the
web process can ask the broker to read/push device configuration without ever
opening a device connection itself. Standard library only.
"""

from __future__ import annotations

import http.client
import json
import socket
from pathlib import Path


class BrokerUnavailableError(RuntimeError):
    """Raised when the broker socket cannot be reached."""


class BrokerRequestError(RuntimeError):
    """Raised when the broker returns a non-2xx response."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"broker returned {status}: {message}")
        self.status = status
        self.message = message


class _UnixHTTPConnection(http.client.HTTPConnection):
    """An :class:`http.client.HTTPConnection` that dials a Unix socket."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


class BrokerClient:
    """Synchronous client for the broker's Unix-socket HTTP API."""

    def __init__(self, socket_path: str | Path, timeout: float = 30.0) -> None:
        self._socket_path = str(socket_path)
        self._timeout = timeout

    def health(self) -> dict:
        return self._request("GET", "/health")

    def read_config(self, device_id: str) -> dict:
        return self._request("GET", f"/devices/{device_id}/config")

    def apply_config(self, device_id: str, payload: dict) -> dict:
        return self._request("POST", f"/devices/{device_id}/apply", payload)

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        conn = _UnixHTTPConnection(self._socket_path, self._timeout)
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if data is not None else {}
            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            if response.status >= 400:
                message = parsed.get("error", "unknown error") if isinstance(parsed, dict) else ""
                raise BrokerRequestError(response.status, message)
            return parsed
        except (OSError, ConnectionError) as exc:
            raise BrokerUnavailableError(
                f"cannot reach broker at unix:{self._socket_path}: {exc}"
            ) from exc
        finally:
            conn.close()
