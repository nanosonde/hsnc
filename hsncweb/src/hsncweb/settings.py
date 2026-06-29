"""Web frontend settings: how to reach the backend, resolved from the environment.

The frontend holds no device or persistence configuration — it only needs to know
where the REST backend lives and how to authenticate to it, plus its own Flask
secret key. This type is self-contained and shares nothing with the backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSettings:
    """Runtime configuration for the web frontend."""

    api_base_url: str = "http://127.0.0.1:8081"
    api_token: str = ""
    secret_key: str = "dev-insecure-change-me"
    session_cookie_secure: bool = False
    max_upload_mb: int = 25


DEFAULT_SECRET_KEY = "dev-insecure-change-me"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def settings_from_env() -> WebSettings:
    return WebSettings(
        api_base_url=os.environ.get("HSNC_API_BASE_URL", "http://127.0.0.1:8081"),
        api_token=os.environ.get("HSNC_API_TOKEN", ""),
        secret_key=os.environ.get("HSNC_SECRET_KEY", DEFAULT_SECRET_KEY),
        session_cookie_secure=_env_flag("HSNC_SESSION_COOKIE_SECURE", False),
        max_upload_mb=_env_int("HSNC_MAX_UPLOAD_MB", 25),
    )

