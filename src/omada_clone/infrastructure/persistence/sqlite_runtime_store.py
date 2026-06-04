"""SQLite implementation of :class:`RuntimeStore`.

Stores time-series runtime data: device status snapshots, client sessions and
association-failure counts. A tiny ``schema_version`` table drives forward-only
migrations applied automatically at startup.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from ...domain.entities import (
    ApplyEvent,
    ApplyOutcome,
    AssociationFailure,
    Client,
    Device,
    FieldChange,
)
from ...domain.interfaces import ApplyHistoryStore, RuntimeStore

SCHEMA_VERSION = 2

_RUNTIME_TABLES = (
    "device_status",
    "client_session",
    "association_failure",
    "apply_event",
)


class SqliteRuntimeStore(RuntimeStore, ApplyHistoryStore):
    """Thread-safe SQLite runtime store with automatic migrations."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # -- migrations -------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL)"
            )
            row = cur.execute("SELECT version FROM schema_version").fetchone()
            current = row["version"] if row else 0

            if current < 1:
                self._apply_v1(cur)
            if current < 2:
                self._apply_v2(cur)

            cur.execute("DELETE FROM schema_version")
            cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()

    @staticmethod
    def _apply_v1(cur: sqlite3.Cursor) -> None:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS device_status (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at  TEXT NOT NULL,
                device_id    TEXT NOT NULL,
                name         TEXT NOT NULL,
                kind         TEXT NOT NULL,
                status       TEXT NOT NULL,
                ip           TEXT,
                uptime_secs  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_device_status_device
                ON device_status (device_id, recorded_at);

            CREATE TABLE IF NOT EXISTS client_session (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at   TEXT NOT NULL,
                client_id     TEXT NOT NULL,
                name          TEXT NOT NULL,
                mac           TEXT NOT NULL,
                ip            TEXT,
                status        TEXT NOT NULL,
                network       TEXT,
                ssid          TEXT,
                rx_bytes      INTEGER NOT NULL DEFAULT 0,
                tx_bytes      INTEGER NOT NULL DEFAULT 0,
                uptime_secs   INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_client_session_client
                ON client_session (client_id, recorded_at);

            CREATE TABLE IF NOT EXISTS association_failure (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at  TEXT NOT NULL,
                category     TEXT NOT NULL,
                count        INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_assoc_failure_time
                ON association_failure (recorded_at);
            """
        )

    @staticmethod
    def _apply_v2(cur: sqlite3.Cursor) -> None:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS apply_event (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                applied_at    TEXT NOT NULL,
                username      TEXT NOT NULL DEFAULT '',
                ok            INTEGER NOT NULL DEFAULT 0,
                details_json  TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_apply_event_time
                ON apply_event (applied_at);
            """
        )

    # -- RuntimeStore -----------------------------------------------------

    def record_device_status(self, device: Device, at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO device_status "
                "(recorded_at, device_id, name, kind, status, ip, uptime_secs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    at.isoformat(),
                    device.id,
                    device.name,
                    device.kind.value,
                    device.status.value,
                    str(device.ip) if device.ip else None,
                    device.uptime_seconds,
                ),
            )
            self._conn.commit()

    def record_client_session(self, client: Client, at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO client_session "
                "(recorded_at, client_id, name, mac, ip, status, network, ssid, "
                "rx_bytes, tx_bytes, uptime_secs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    at.isoformat(),
                    client.id,
                    client.name,
                    str(client.mac),
                    str(client.ip) if client.ip else None,
                    client.status.value,
                    client.network,
                    client.ssid,
                    client.downloaded.bytes,
                    client.uploaded.bytes,
                    client.uptime_seconds,
                ),
            )
            self._conn.commit()

    def record_association_failures(
        self, failures: Iterable[AssociationFailure], at: datetime
    ) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO association_failure (recorded_at, category, count) "
                "VALUES (?, ?, ?)",
                [(at.isoformat(), f.category, f.count) for f in failures],
            )
            self._conn.commit()

    def latest_association_failures(self) -> list[AssociationFailure]:
        with self._lock:
            row = self._conn.execute(
                "SELECT recorded_at FROM association_failure "
                "ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return []
            rows = self._conn.execute(
                "SELECT category, count FROM association_failure WHERE recorded_at = ?",
                (row["recorded_at"],),
            ).fetchall()
        return [AssociationFailure(r["category"], r["count"]) for r in rows]

    # -- ApplyHistoryStore ------------------------------------------------

    def record_apply_event(self, event: ApplyEvent) -> None:
        details = json.dumps(
            {
                "action": event.action,
                "outcomes": [
                    {
                        "device_id": o.device_id,
                        "device_name": o.device_name,
                        "ok": o.ok,
                        "message": o.message,
                        "changes": [
                            {"field": c.field, "old": c.old, "new": c.new}
                            for c in o.changes
                        ],
                    }
                    for o in event.outcomes
                ],
            }
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO apply_event (applied_at, username, ok, details_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    event.applied_at.isoformat(),
                    event.username,
                    1 if event.ok else 0,
                    details,
                ),
            )
            self._conn.commit()

    def list_apply_events(self, limit: int = 50) -> list[ApplyEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, applied_at, username, ok, details_json FROM apply_event "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        events: list[ApplyEvent] = []
        for row in rows:
            details = json.loads(row["details_json"])
            # Back-compat: legacy rows stored a bare list of outcomes; new rows
            # wrap them in a dict alongside the action type.
            if isinstance(details, dict):
                action = details.get("action", "apply")
                raw_outcomes = details.get("outcomes", [])
            else:
                action = "apply"
                raw_outcomes = details
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
                for o in raw_outcomes
            ]
            events.append(
                ApplyEvent(
                    id=row["id"],
                    applied_at=datetime.fromisoformat(row["applied_at"]),
                    username=row["username"],
                    ok=bool(row["ok"]),
                    action=action,
                    outcomes=outcomes,
                )
            )
        return events

    def export_rows(self) -> dict[str, list[dict]]:
        with self._lock:
            result: dict[str, list[dict]] = {}
            for table in _RUNTIME_TABLES:
                rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
                result[table] = [dict(r) for r in rows]
        return result

    def import_rows(self, tables: dict[str, list[dict]]) -> None:
        with self._lock:
            for table in _RUNTIME_TABLES:
                rows = tables.get(table, [])
                self._conn.execute(f"DELETE FROM {table}")
                for row in rows:
                    columns = [c for c in row.keys() if c != "id"]
                    if not columns:
                        continue
                    placeholders = ", ".join("?" for _ in columns)
                    column_list = ", ".join(columns)
                    self._conn.execute(
                        f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})",
                        [row[c] for c in columns],
                    )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
