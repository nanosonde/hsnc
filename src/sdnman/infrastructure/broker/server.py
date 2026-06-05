"""The Device Broker's IPC server (HTTP over a Unix-domain socket).

The web process never opens a device connection. Instead it talks to the broker
over a private Unix socket (``/data/broker.sock``, ``0600``), asking it to read
or push configuration on its behalf. HTTP is used as the wire format because it
is in the standard library on both ends — no extra dependency, no network port.

:class:`BrokerApi` holds the request-handling logic and is transport-agnostic so
it can be unit-tested directly; :class:`UnixHttpServer` wraps it for real use.
"""

from __future__ import annotations

import json
import logging
import os
import socketserver
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from ...domain.interfaces import ConfigRepository, DeviceAdapterFactory
from ..config.mapping import device_to_config, merge
from ..config.schemas import DeviceConfigSchema
from .connection_pool import ConnectionPool

_log = logging.getLogger("sdnman.broker.server")


class BrokerError(Exception):
    """Carries an HTTP status code for a failed broker request."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class BrokerApi:
    """Transport-agnostic broker request handling.

    Resolves a device by id from the connection profiles, then uses the *real*
    device adapters (which reuse the pool's warm connections) to read or push
    configuration. Only the configuration payload crosses the IPC boundary; the
    web app already holds the connection profiles itself.
    """

    def __init__(
        self,
        profiles: ConfigRepository,
        adapters: DeviceAdapterFactory,
        pool: ConnectionPool | None = None,
    ) -> None:
        self._profiles = profiles
        self._adapters = adapters
        self._pool = pool

    def health(self) -> dict:
        connections = self._pool.snapshot() if self._pool else []
        return {"status": "ok", "connections": connections}

    def read_config(self, device_id: str) -> dict:
        device = self._require_device(device_id)
        adapter = self._adapters.for_device(device)
        read = adapter.fetch_config(device)
        return device_to_config(read).model_dump(mode="python")

    def apply_config(self, device_id: str, payload: dict) -> dict:
        device = self._require_device(device_id)
        try:
            config = DeviceConfigSchema.model_validate({**payload, "id": device_id})
        except Exception as exc:  # noqa: BLE001 - surface as 400
            raise BrokerError(400, f"invalid config payload: {exc}") from exc
        adapter = self._adapters.for_device(device)
        adapter.push_config(merge(device, config))
        return {"status": "applied", "device_id": device_id}

    def _require_device(self, device_id: str):
        device = self._profiles.get_device(device_id)
        if device is None:
            raise BrokerError(404, f"unknown device {device_id!r}")
        return device


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _api(self) -> BrokerApi:
        return self.server.api  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:  # quieten default logging
        # Unix-socket peers have no address; avoid BaseHTTPRequestHandler's
        # address_string() which indexes an empty client_address tuple.
        _log.debug(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            body = self._route(method, parts)
            self._send(200, body)
        except BrokerError as exc:
            self._send(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the client
            _log.exception("Broker request failed: %s %s", method, self.path)
            self._send(500, {"error": str(exc)})

    def _route(self, method: str, parts: list[str]) -> dict:
        if method == "GET" and parts == ["health"]:
            return self._api.health()
        if method == "GET" and len(parts) == 3 and parts[0] == "devices" and parts[2] == "config":
            return self._api.read_config(parts[1])
        if method == "POST" and len(parts) == 3 and parts[0] == "devices" and parts[2] == "apply":
            return self._api.apply_config(parts[1], self._read_json())
        raise BrokerError(404, f"no route for {method} /{'/'.join(parts)}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BrokerError(400, f"invalid JSON body: {exc}") from exc

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class UnixHttpServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded HTTP server bound to a Unix-domain socket.

    Each request is handled on its own thread so a slow device operation never
    blocks another caller. The socket is created with ``0600`` permissions so
    only the broker's own user (``appuser``) can talk to it.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path: str | Path, api: BrokerApi) -> None:
        self.api = api
        path = str(socket_path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)
        super().__init__(path, _Handler)
        os.chmod(path, 0o600)


def serve(socket_path: str | Path, api: BrokerApi) -> UnixHttpServer:
    """Create and return a (not yet serving) :class:`UnixHttpServer`."""
    server = UnixHttpServer(socket_path, api)
    _log.info("Broker listening on unix:%s", socket_path)
    return server
