"""JSONL implementation of :class:`ApplyHistoryStore`.

The apply/audit history is small, append-only and rarely written (only when a
configuration is applied), so a line-delimited JSON file is a better fit than a
SQLite table for a home deployment: human-readable, greppable, no schema or
migrations, and a single writer (the web app). Each line is one apply event.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from ..entities import ApplyEvent, ApplyOutcome, FieldChange
from ..interfaces import ApplyHistoryStore


def _event_to_dict(event: ApplyEvent) -> dict:
    return {
        "applied_at": event.applied_at.isoformat(),
        "username": event.username,
        "ok": event.ok,
        "action": event.action,
        "outcomes": [
            {
                "device_id": o.device_id,
                "device_name": o.device_name,
                "ok": o.ok,
                "message": o.message,
                "changes": [
                    {"field": c.field, "old": c.old, "new": c.new} for c in o.changes
                ],
            }
            for o in event.outcomes
        ],
    }


def _dict_to_event(data: dict, line_id: int) -> ApplyEvent:
    outcomes = [
        ApplyOutcome(
            device_id=o["device_id"],
            device_name=o["device_name"],
            ok=bool(o["ok"]),
            message=o.get("message", ""),
            changes=[
                FieldChange(c["field"], c["old"], c["new"])
                for c in o.get("changes", [])
            ],
        )
        for o in data.get("outcomes", [])
    ]
    return ApplyEvent(
        id=line_id,
        applied_at=datetime.fromisoformat(data["applied_at"]),
        username=data.get("username", ""),
        ok=bool(data.get("ok", False)),
        action=data.get("action", "apply"),
        outcomes=outcomes,
    )


class JsonlApplyHistoryStore(ApplyHistoryStore):
    """Append-only apply/audit history backed by a JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record_apply_event(self, event: ApplyEvent) -> None:
        line = json.dumps(_event_to_dict(event), default=str)
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()

    def list_apply_events(self, limit: int = 50) -> list[ApplyEvent]:
        with self._lock:
            if not self._path.exists():
                return []
            lines = self._path.read_text(encoding="utf-8").splitlines()
        events: list[ApplyEvent] = []
        for index, raw in enumerate(lines, start=1):
            raw = raw.strip()
            if not raw:
                continue
            events.append(_dict_to_event(json.loads(raw), index))
        events.reverse()  # newest first
        return events[:limit]

    # -- backup helpers ---------------------------------------------------

    def export_text(self) -> str:
        """Return the raw JSONL contents (empty string if no history yet)."""
        with self._lock:
            if not self._path.exists():
                return ""
            return self._path.read_text(encoding="utf-8")

    def import_text(self, text: str) -> None:
        """Replace the history file with the provided raw JSONL contents."""
        with self._lock:
            self._path.write_text(text, encoding="utf-8")

    def close(self) -> None:  # symmetry with SqliteRuntimeStore; nothing to do
        return None
