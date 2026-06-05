"""SQLite implementation of :class:`RuntimeStore`.

Stores time-series runtime data: device status snapshots, client sessions and
association-failure counts. A tiny ``schema_version`` table drives forward-only
migrations applied automatically at startup. Apply/audit history lives elsewhere
(:class:`JsonlApplyHistoryStore`), so this database has a single writer (the
Device Broker) and can be pruned on a retention window.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from ...domain.entities import (
    AssociationFailure,
    Client,
    Device,
)
from ...domain.enums import ConnectionType, DeviceStatus
from ...domain.interfaces import RuntimeStore
from ...domain.value_objects import DataVolume, IpAddress, MacAddress

SCHEMA_VERSION = 2

_RUNTIME_TABLES = (
    "device_status",
    "client_session",
    "association_failure",
)


class SqliteRuntimeStore(RuntimeStore):
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
        self._conn.execute("PRAGMA busy_timeout=5000")
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

            if current >= SCHEMA_VERSION:
                # Already current: do not write, so read-only consumers (the web
                # process) never contend with the broker for the write lock.
                return

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
        # Associate client sessions with their device and preserve enough fields
        # to reconstruct a Client for the web read path (latest_clients).
        existing = {row["name"] for row in cur.execute("PRAGMA table_info(client_session)")}
        if "device_id" not in existing:
            cur.execute("ALTER TABLE client_session ADD COLUMN device_id TEXT NOT NULL DEFAULT ''")
        if "connection" not in existing:
            cur.execute("ALTER TABLE client_session ADD COLUMN connection TEXT NOT NULL DEFAULT ''")
        if "ap_or_port" not in existing:
            cur.execute("ALTER TABLE client_session ADD COLUMN ap_or_port TEXT NOT NULL DEFAULT ''")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_session_device "
            "ON client_session (device_id, recorded_at)"
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

    def record_client_session(
        self, client: Client, at: datetime, device_id: str = ""
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO client_session "
                "(recorded_at, client_id, name, mac, ip, status, network, ssid, "
                "rx_bytes, tx_bytes, uptime_secs, device_id, connection, ap_or_port) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    device_id,
                    client.connection.value,
                    client.ap_or_port,
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

    # -- web read path ----------------------------------------------------

    def latest_device_status(self, device: Device) -> Device:
        from dataclasses import replace

        with self._lock:
            row = self._conn.execute(
                "SELECT status, ip, uptime_secs FROM device_status "
                "WHERE device_id = ? ORDER BY recorded_at DESC LIMIT 1",
                (device.id,),
            ).fetchone()
        if row is None:
            return replace(device, status=DeviceStatus.UNKNOWN)
        return replace(
            device,
            status=DeviceStatus(row["status"]),
            ip=IpAddress(row["ip"]) if row["ip"] else device.ip,
            uptime_seconds=int(row["uptime_secs"] or 0),
        )

    def latest_clients(self, device: Device) -> list[Client]:
        with self._lock:
            latest = self._conn.execute(
                "SELECT recorded_at FROM client_session "
                "WHERE device_id = ? ORDER BY recorded_at DESC LIMIT 1",
                (device.id,),
            ).fetchone()
            if latest is None:
                return []
            rows = self._conn.execute(
                "SELECT * FROM client_session WHERE device_id = ? AND recorded_at = ?",
                (device.id, latest["recorded_at"]),
            ).fetchall()
        return [self._row_to_client(r, device) for r in rows]

    @staticmethod
    def _row_to_client(row: sqlite3.Row, device: Device) -> Client:
        keys = row.keys()
        connection = row["connection"] if "connection" in keys and row["connection"] else None
        return Client(
            id=row["client_id"],
            name=row["name"],
            mac=MacAddress(row["mac"]),
            connection=ConnectionType(connection) if connection else ConnectionType.WIRED,
            status=DeviceStatus(row["status"]),
            ip=IpAddress(row["ip"]) if row["ip"] else None,
            network=row["network"] or "LAN",
            ssid=row["ssid"] or "",
            ap_or_port=(row["ap_or_port"] if "ap_or_port" in keys else "") or device.name,
            downloaded=DataVolume(int(row["rx_bytes"] or 0)),
            uploaded=DataVolume(int(row["tx_bytes"] or 0)),
            uptime_seconds=int(row["uptime_secs"] or 0),
            site_id=device.site_id,
        )

    # -- retention --------------------------------------------------------

    def prune(self, cutoff: datetime) -> int:
        """Delete runtime rows recorded before ``cutoff``; return rows removed."""
        iso = cutoff.isoformat()
        removed = 0
        with self._lock:
            for table in _RUNTIME_TABLES:
                cur = self._conn.execute(
                    f"DELETE FROM {table} WHERE recorded_at < ?", (iso,)
                )
                removed += cur.rowcount
            self._conn.commit()
        return removed

    # -- backup -----------------------------------------------------------

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
