"""Flask application factory and background scheduler wiring."""

from __future__ import annotations

import atexit
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, render_template

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
    app.config["SECRET_KEY"] = os.environ.get("OMADA_SECRET_KEY", "dev-insecure-change-me")
    app.config["CONTAINER"] = Container(settings)
    app.config["SETTINGS"] = settings

    register_template_globals(app)

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
    _start_scheduler(app, settings)

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(_error):  # type: ignore[no-untyped-def]
        return render_template("error.html", code=500, message="Internal server error"), 500


def _start_scheduler(app: Flask, settings: Settings) -> None:
    # Avoid double-scheduling under the Werkzeug reloader's parent process.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return

    container: Container = app.config["CONTAINER"]
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        container.poll_device_state.execute,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="poll_device_state",
        next_run_time=None,
    )
    scheduler.start()
    app.config["SCHEDULER"] = scheduler

    # Prime one immediate poll so the dashboard has data on first load.
    try:
        container.poll_device_state.execute()
    except Exception:  # noqa: BLE001 - never block startup on a poll error
        app.logger.exception("Initial device poll failed")

    @atexit.register
    def _shutdown() -> None:  # pragma: no cover - process teardown
        scheduler.shutdown(wait=False)
        container.close()
