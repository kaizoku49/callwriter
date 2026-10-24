"""Small local SQLite store for read-only paper-tracking history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).resolve().parents[2] / "callwriter.sqlite3"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracked_calls (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                symbol TEXT,
                instrument_key TEXT,
                details TEXT NOT NULL
            );
            """
        )


def load_tracked() -> dict[str, dict]:
    init_db()
    with _connect() as connection:
        rows = connection.execute("SELECT id, data FROM tracked_calls ORDER BY updated_at DESC").fetchall()
    result = {}
    for row in rows:
        try:
            result[row["id"]] = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
    return result


def save_tracked(item: dict) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO tracked_calls(id, data, updated_at) VALUES (?, ?, ?)",
            (item["id"], json.dumps(item, default=str), _now()),
        )


def delete_tracked(item_id: str) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM tracked_calls WHERE id = ?", (item_id,))


def record_event(event_type: str, symbol: str | None = None, instrument_key: str | None = None, details: dict[str, Any] | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO paper_history(created_at, event_type, symbol, instrument_key, details) VALUES (?, ?, ?, ?, ?)",
            (_now(), event_type, symbol, instrument_key, json.dumps(details or {}, default=str)),
        )


def history(limit: int = 200) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, created_at, event_type, symbol, instrument_key, details FROM paper_history ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
    result = []
    for row in rows:
        try:
            details = json.loads(row["details"])
        except json.JSONDecodeError:
            details = {}
        result.append({**dict(row), "details": details})
    return result
