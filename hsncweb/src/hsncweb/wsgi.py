"""WSGI entry point for gunicorn: ``hsncweb.wsgi:app``."""

from __future__ import annotations

from .app import create_app
from .logging_config import configure_logging

configure_logging()

app = create_app()
