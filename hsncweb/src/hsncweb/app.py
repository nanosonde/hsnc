"""Flask application factory.

The web app holds no device connections, no database and no use-case logic: it is
a pure presentation tier. Every read and write goes to the REST backend over HTTP
via :class:`~hsncweb.api_client.ApiClient`. The backend owns all
device I/O, polling and persistence.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from .api_client import ApiClient
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
from .settings import WebSettings, settings_from_env

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_STATIC = Path(__file__).resolve().parent / "static"


def create_app(settings: WebSettings | None = None, api_client: ApiClient | None = None) -> Flask:
    settings = settings or settings_from_env()

    app = Flask(
        __name__,
        template_folder=str(_TEMPLATES),
        static_folder=str(_STATIC),
    )
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["API"] = api_client or ApiClient(settings.api_base_url, settings.api_token)
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
        name = app.config.get("SITE_NAME")
        if name is None:
            name = app.config["API"].get_site()["name"]
            app.config["SITE_NAME"] = name
        return {"site_name": name}

    app.register_blueprint(auth_bp.bp)
    app.register_blueprint(dashboard_bp.bp)
    app.register_blueprint(devices_bp.bp)
    app.register_blueprint(clients_bp.bp)
    app.register_blueprint(topology_bp.bp)
    app.register_blueprint(backup_bp.bp)
    app.register_blueprint(config_bp.bp)

    _register_error_handlers(app)

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=500, message="Internal server error"), 500
