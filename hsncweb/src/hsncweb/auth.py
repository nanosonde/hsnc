"""Authentication and authorization helpers for the Flask UI."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import current_app, flash, redirect, session, url_for


def current_user() -> dict[str, str] | None:
    return session.get("user")


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if current_user() is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            user = current_user()
            if user is None:
                return redirect(url_for("auth.login"))
            if user.get("role") not in roles:
                flash("You do not have permission to perform this action.", "error")
                return redirect(url_for("dashboard.index"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def login_user(username: str, display_name: str, role: str) -> None:
    # Make the session permanent so PERMANENT_SESSION_LIFETIME (set in the app
    # factory) bounds how long a leaked session cookie remains valid.
    session.permanent = True
    session["user"] = {
        "username": username,
        "display_name": display_name,
        "role": role,
    }


def logout_user() -> None:
    session.pop("user", None)


def is_admin() -> bool:
    user = current_user()
    return bool(user and user.get("role") == "admin")


def is_read_only() -> bool:
    """Return whether the global read-only mode is active."""
    return bool(current_app.config.get("READ_ONLY"))


def set_read_only(value: bool) -> None:
    current_app.config["READ_ONLY"] = bool(value)


def register_template_globals(app: Any) -> None:
    app.jinja_env.globals["current_user"] = current_user
    app.jinja_env.globals["is_admin"] = is_admin
    app.jinja_env.globals["is_read_only"] = is_read_only
