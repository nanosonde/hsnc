"""Wire contract for the REST split: JSON serialization + error envelope.

The backend serializes application DTOs (and :class:`ApplyEvent`) into JSON-safe
structures with :func:`to_jsonable`, and maps raised exceptions to a stable
``{"error": {"type", "message"}}`` envelope plus an HTTP status. The frontend
parses these back into its own view types.

Only declared dataclass *fields* are serialized; computed ``@property`` values
(``total_pages``, ``ok``, ``has_changes``, ...) are intentionally omitted because
the frontend recomputes them from the same fields. The error map is keyed by
exception *class name* so the two tiers stay decoupled — each may define its own
exception classes with matching names.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import Any


def to_jsonable(obj: Any) -> Any:
    """Recursively convert DTOs / collections into JSON-safe primitives."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_jsonable(value) for key, value in obj.items()}
    return str(obj)


#: Exception class name -> HTTP status. Keyed by name (not the class) so neither
#: tier has to import the other's exception types.
ERROR_STATUS: dict[str, int] = {
    "DeviceNotFoundError": 404,
    "ConfigEditError": 400,
    "ValueError": 400,
    "SshError": 502,
}

#: Status used when no entry in :data:`ERROR_STATUS` matches.
DEFAULT_ERROR_STATUS = 500


def status_for_exception(exc: BaseException) -> int:
    """Return the HTTP status for ``exc`` by walking its class hierarchy."""
    for cls in type(exc).__mro__:
        status = ERROR_STATUS.get(cls.__name__)
        if status is not None:
            return status
    return DEFAULT_ERROR_STATUS


def error_envelope(exc: BaseException) -> dict[str, dict[str, str]]:
    """Build the JSON error envelope carried in a failure response body."""
    return {"error": {"type": type(exc).__name__, "message": str(exc)}}
