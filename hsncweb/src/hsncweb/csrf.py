"""Lightweight, dependency-free CSRF protection for the Flask UI.

Every state-changing request (POST/PUT/PATCH/DELETE) must carry a token that
matches the one stored in the user's signed session. Templates emit the token
with the ``csrf_field()`` global (a hidden form input); HTMX requests may instead
send it in the ``X-CSRFToken`` header.

Protection is disabled automatically under ``app.testing`` (mirroring Flask-WTF)
so the golden-HTML byte-identity tests stay deterministic. Set
``app.config["CSRF_ENABLED"]`` explicitly to override.
"""

from __future__ import annotations

import hmac
import secrets

from flask import Flask, abort, request, session
from markupsafe import Markup

_SESSION_KEY = "_csrf_token"
_FORM_FIELD = "csrf_token"  # noqa: S105 - field name, not a secret
_HEADER = "X-CSRFToken"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _enabled() -> bool:
    from flask import current_app

    return bool(current_app.config.get("CSRF_ENABLED", not current_app.testing))


def _ensure_token() -> str:
    token = session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = token
    return token


def csrf_token() -> str:
    """Return the session CSRF token, or ``""`` when protection is disabled."""
    if not _enabled():
        return ""
    return _ensure_token()


def csrf_field() -> Markup:
    """Render a hidden input carrying the CSRF token (empty when disabled)."""
    token = csrf_token()
    if not token:
        return Markup("")
    return Markup(f'<input type="hidden" name="{_FORM_FIELD}" value="{token}">')


def init_csrf(app: Flask) -> None:
    """Install the CSRF before-request guard and template globals."""

    @app.before_request
    def _protect():  # type: ignore[no-untyped-def]
        if not _enabled():
            return None
        if request.method in _SAFE_METHODS:
            return None
        expected = session.get(_SESSION_KEY)
        sent = request.form.get(_FORM_FIELD) or request.headers.get(_HEADER, "")
        if not expected or not sent or not hmac.compare_digest(expected, sent):
            abort(400, description="CSRF validation failed.")
        return None

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["csrf_field"] = csrf_field
