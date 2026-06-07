"""WSGI entry point for gunicorn: ``sdnweb.wsgi:app``."""

from __future__ import annotations

from .app import create_app

app = create_app()
