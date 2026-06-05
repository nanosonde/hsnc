"""Flask application factory.

The web app holds no device connections: a separate Device Broker process
(``sdnman-ctl broker``) owns all device I/O and is the sole writer of the runtime
database. The web app reads the latest runtime snapshot and proxies any
configuration read/write to the broker over its Unix socket. There is no
in-process scheduler.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from ..infrastructure.container import Container, Settings
from .auth import register_template_globals
from .blueprints import (
    auth_bp,
    backup_bp,
    clients_bp,
    config_bp,
    dashboard_bp,
    devices_bp,
    topology_bp,
)
from .settings import settings_from_env

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_STATIC = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or settings_from_env()

    app = Flask(
        __name__,
        template_folder=str(_TEMPLATES),
        static_folder=str(_STATIC),
    )
    app.config["SECRET_KEY"] = os.environ.get("SDNMAN_SECRET_KEY", "dev-insecure-change-me")
    app.config["CONTAINER"] = Container(settings)
    app.config["SETTINGS"] = settings
    app.config["READ_ONLY"] = True

    register_template_globals(app)

    # Read-only mode only blocks applying configuration to physical devices.
    # Re-reads, config edits and reverts remain available.
    _READ_ONLY_BLOCKED = {
        "config.apply",
        "config.apply_device",
    }

    @app.before_request
    def _enforce_read_only():  # type: ignore[no-untyped-def]
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if not app.config.get("READ_ONLY"):
            return None
        if request.endpoint not in _READ_ONLY_BLOCKED:
            return None
        flash("Read-only mode is active \u2014 applying changes to devices is disabled.", "error")
        return redirect(request.referrer or url_for("dashboard.index"))

    @app.context_processor
    def inject_site_name() -> dict[str, str]:
        container: Container = app.config["CONTAINER"]
        return {"site_name": container.config.get_site().name}

    app.register_blueprint(auth_bp.bp)
    app.register_blueprint(dashboard_bp.bp)
    app.register_blueprint(devices_bp.bp)
    app.register_blueprint(clients_bp.bp)
    app.register_blueprint(topology_bp.bp)
    app.register_blueprint(backup_bp.bp)
    app.register_blueprint(config_bp.bp)

    _register_error_handlers(app)

    container: Container = app.config["CONTAINER"]

    @atexit.register
    def _shutdown() -> None:  # pragma: no cover - process teardown
        container.close()

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=500, message="Internal server error"), 500
