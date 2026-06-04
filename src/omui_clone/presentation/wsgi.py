"""WSGI entry point for gunicorn: ``omui_clone.presentation.wsgi:app``."""

from __future__ import annotations

from .app import create_app

app = create_app()
