"""Flask application factory.

The web app holds no device connections, no database and no use-case logic: it is
a pure presentation tier. Every read and write goes to the REST backend over HTTP
via :class:`~hsncweb.api_client.ApiClient`. The backend owns all
device I/O, polling and persistence.
"""

from __future__ import annotations

import logging
from datetime import timedelta
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
from .csrf import init_csrf
from .ratelimit import LoginRateLimiter
from .settings import DEFAULT_SECRET_KEY, WebSettings, settings_from_env

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_STATIC = Path(__file__).resolve().parent / "static"

_logger = logging.getLogger(__name__)


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
    app.config["LOGIN_RATELIMITER"] = LoginRateLimiter(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
    )

    # Session-cookie hardening. HTTPONLY and SameSite=Lax are always safe and
    # mitigate XSS cookie theft and cross-site form submission; Secure (HTTPS
    # only) is opt-in via HSNC_SESSION_COOKIE_SECURE so plain-HTTP deployments
    # keep working. Sessions expire so a leaked cookie does not last forever.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        # Reject oversized request bodies before they are read into memory,
        # capping the cost of a malicious or accidental huge backup upload.
        MAX_CONTENT_LENGTH=settings.max_upload_mb * 1024 * 1024,
    )

    if settings.secret_key == DEFAULT_SECRET_KEY:
        _logger.warning(
            "HSNC_SECRET_KEY is unset; using the built-in insecure development "
            "key. Set HSNC_SECRET_KEY to a random value in any shared or "
            "production deployment to prevent session-cookie forgery."
        )

    register_template_globals(app)
    init_csrf(app)

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
    @app.errorhandler(400)
    def bad_request(error):  # type: ignore[no-untyped-def]
        message = getattr(error, "description", "Bad request") or "Bad request"
        return render_template("error.html", code=400, message=message), 400

    @app.errorhandler(404)
    def not_found(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(413)
    def payload_too_large(_error):  # type: ignore[no-untyped-def]
        return (
            render_template(
                "error.html", code=413, message="Uploaded file is too large."
            ),
            413,
        )

    @app.errorhandler(500)
    def server_error(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=500, message="Internal server error"), 500
