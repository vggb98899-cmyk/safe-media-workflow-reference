from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStore:
    """Small durable store; every mutating decision is append-only auditable."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
              request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, target TEXT NOT NULL,
              schema_version INTEGER NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
              provider_task_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
              event TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases (
              lease_name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            """)

    def audit(self, request_id: str, event: str, **detail: Any) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO audit(request_id,event,detail,created_at) VALUES(?,?,?,?)",
                         (request_id, event, json.dumps(detail, sort_keys=True), now()))

    def get_plan(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def create_plan(self, *, request_id: str, fingerprint: str, target: str,
                    schema_version: int, payload: dict[str, Any]) -> dict[str, Any]:
        row = self.get_plan(request_id)
        if row:
            return row
        timestamp = now()
        with self._connect() as conn:
            conn.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?)",
                         (request_id, fingerprint, target, schema_version, json.dumps(payload, sort_keys=True),
                          "PREVIEWED", None, timestamp, timestamp))
        self.audit(request_id, "SNAPSHOT_CREATED", target=target, fingerprint=fingerprint)
        return self.get_plan(request_id)  # type: ignore[return-value]

    def transition(self, request_id: str, expected: set[str], state: str, **extra: Any) -> dict[str, Any]:
        row = self.get_plan(request_id)
        if not row or row["state"] not in expected:
            raise ValueError("invalid state transition")
        task_id = extra.get("provider_task_id", row["provider_task_id"])
        with self._connect() as conn:
            conn.execute("UPDATE plans SET state=?, provider_task_id=?, updated_at=? WHERE request_id=?",
                         (state, task_id, now(), request_id))
        self.audit(request_id, "STATE_CHANGED", previous=row["state"], current=state, **extra)
        return self.get_plan(request_id)  # type: ignore[return-value]

    def acquire_lease(self, name: str, owner: str, expires_at: str) -> bool:
        with self._connect() as conn:
            current = conn.execute("SELECT * FROM leases WHERE lease_name=?", (name,)).fetchone()
            if current and current["expires_at"] > now() and current["owner"] != owner:
                return False
            conn.execute("INSERT OR REPLACE INTO leases VALUES(?,?,?)", (name, owner, expires_at))
        return True
