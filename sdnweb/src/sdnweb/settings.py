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


def settings_from_env() -> WebSettings:
    return WebSettings(
        api_base_url=os.environ.get("SDNMAN_API_BASE_URL", "http://127.0.0.1:8081"),
        api_token=os.environ.get("SDNMAN_API_TOKEN", ""),
        secret_key=os.environ.get("SDNMAN_SECRET_KEY", "dev-insecure-change-me"),
    )

