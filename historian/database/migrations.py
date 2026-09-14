"""Schema version helpers / future migrations."""

from __future__ import annotations

import sqlite3

from historian.database.schema import SCHEMA_VERSION


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if not row:
        return None
    val = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if not val:
        return None
    try:
        return int(val[0])
    except (TypeError, ValueError):
        return None


def set_schema_version(conn: sqlite3.Connection, version: int = SCHEMA_VERSION) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(version),),
    )


def migrate(conn: sqlite3.Connection) -> int:
    """Apply migrations up to SCHEMA_VERSION. v1 is create-only via schema SQL."""
    current = get_schema_version(conn)
    if current is None:
        return SCHEMA_VERSION
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema_version {current} is newer than code {SCHEMA_VERSION}"
        )
    # Future: if current < SCHEMA_VERSION: run ALTER scripts
    return current
