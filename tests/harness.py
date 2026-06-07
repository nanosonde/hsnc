"""Test harness: drive the web app against an in-process REST backend.

Builds an :class:`ApiClient` whose transport is a Flask test client bound to the
real backend app (mock container). This lets web-route and api-client tests
exercise the full HTTP wire path without sockets or threads.
"""

from __future__ import annotations

from typing import Any

from sdnman.backend.app import create_api_app
from sdnman.infrastructure.container import Container, Settings
from sdnman.presentation.api_client import ApiClient


class FlaskTestTransport:
    """ApiClient transport that routes requests through a Flask test client."""

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


def backend_api_client(settings: Settings) -> tuple[ApiClient, Container]:
    """Return an ApiClient wired to a freshly-polled mock backend container."""
    container = Container(settings, profile="api")
    # Seed the runtime snapshot the way the poll loop would on a live system.
    container.poll_device_state.execute()
    app = create_api_app(settings, container=container)
    return ApiClient(transport=FlaskTestTransport(app.test_client())), container
