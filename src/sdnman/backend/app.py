"""Flask application factory for the REST backend.

The backend owns all device I/O and state: real device adapters push/read
configuration, a background poll loop scrapes live state into the runtime store,
and read endpoints serve the latest snapshot. The frontend never touches a device
or a database — it calls this HTTP API.

Use-case exceptions bubble up to a single error handler that emits the stable
``{"error": {"type", "message"}}`` envelope plus the mapped HTTP status, so the
frontend can re-raise the same-named exception and flash identical text.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from ..application.wire import error_envelope, status_for_exception
from ..infrastructure.container import Container, Settings
from ..presentation.settings import settings_from_env
from .api import bp as api_bp


def create_api_app(settings: Settings | None = None, container: Container | None = None) -> Flask:
    settings = settings or settings_from_env()

    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    app.config["CONTAINER"] = container or Container(settings)

    token = os.environ.get("SDNMAN_API_TOKEN", "").strip()
    if token:

        @app.before_request
        def _require_token():  # type: ignore[no-untyped-def]
            if request.path == "/api/health":
                return None
            if request.headers.get("Authorization") == f"Bearer {token}":
                return None
            return jsonify(
                {"error": {"type": "Unauthorized", "message": "Invalid API token."}}
            ), 401

    app.register_blueprint(api_bp)
    _register_error_handler(app)
    return app


def _register_error_handler(app: Flask) -> None:
    @app.errorhandler(Exception)
    def _handle(exc: Exception):  # type: ignore[no-untyped-def]
        if isinstance(exc, HTTPException):
            return jsonify(
                {"error": {"type": exc.name, "message": exc.description or exc.name}}
            ), exc.code
        return jsonify(error_envelope(exc)), status_for_exception(exc)
