"""Centralised logging setup for the backend.

A single env var, ``HSNC_LOG_LEVEL``, controls how verbose the application's own
loggers are. The level is applied only to the ``hsnc`` logger tree, so raising it
to ``debug`` surfaces all application logging without unleashing noisy
third-party libraries (werkzeug, urllib3, paramiko) — the root logger stays at
its default ``WARNING``. ``paramiko`` remains separately gated behind
``HSNC_SSH_DEBUG`` (see :mod:`hsnc.devices.ssh_transport`).
"""

from __future__ import annotations

import logging
import os

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def resolve_level(name: str | None) -> int:
    """Map a level name (case-insensitive) to a ``logging`` constant.

    Unknown or empty values fall back to ``INFO`` so a typo never silences logs.
    """
    return _LEVELS.get((name or "").strip().lower(), logging.INFO)


def configure_logging(level: int | str | None = None) -> int:
    """Install a stderr handler and set the ``hsnc`` logger level.

    ``level`` defaults to the ``HSNC_LOG_LEVEL`` environment variable (then
    ``INFO``). The root logger keeps its default level so third-party libraries
    stay quiet; only the application's ``hsnc`` tree follows the requested level.
    Returns the resolved numeric level.
    """
    if level is None:
        resolved = resolve_level(os.environ.get("HSNC_LOG_LEVEL"))
    elif isinstance(level, str):
        resolved = resolve_level(level)
    else:
        resolved = level
    # basicConfig installs a root StreamHandler (no-op if one already exists)
    # without lowering the root level, so app logs actually emit under gunicorn.
    logging.basicConfig(format=_LOG_FORMAT)
    logging.getLogger("hsnc").setLevel(resolved)
    return resolved
