"""SQLite schema for Cozy Aircraft Historian (spec §5–§13, §53)."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

SCHEMA_VERSION = 2

# Legacy 10 Hz columns (prefix fix_). Extra FIX keys are ALTER'd from historian.yaml.
FIX_10HZ_COLUMNS = (
    "fix_lat",
    "fix_long",
    "fix_pitch",
    "fix_roll",
    "fix_head",
    "fix_alt",
    "fix_palt",
    "fix_vs",
    "fix_alat",
    "fix_gs",
    "fix_track",
)

FIX_1HZ_COLUMNS: tuple[str, ...] = ()  # populated when slow_signals are configured


def _real_cols(names: tuple[str, ...]) -> str:
    if not names:
        return ""
    return ",\n    ".join(f"{n} REAL" for n in names) + ","


SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aircraft (
    aircraft_id  TEXT PRIMARY KEY,
    registration TEXT,
    type         TEXT,
    description  TEXT,
    created_at   TEXT NOT NULL,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS aircraft_configuration (
    configuration_id TEXT PRIMARY KEY,
    aircraft_id      TEXT NOT NULL REFERENCES aircraft(aircraft_id),
    valid_from       TEXT,
    valid_to         TEXT,
    name             TEXT,
    description      TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configuration_item (
    configuration_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    configuration_id      TEXT NOT NULL REFERENCES aircraft_configuration(configuration_id),
    category              TEXT NOT NULL,
    item                  TEXT NOT NULL,
    value                 TEXT,
    units                 TEXT,
    notes                 TEXT
);

CREATE TABLE IF NOT EXISTS flight (
    flight_id              TEXT PRIMARY KEY,
    aircraft_id            TEXT NOT NULL REFERENCES aircraft(aircraft_id),
    configuration_id       TEXT REFERENCES aircraft_configuration(configuration_id),
    flight_date            TEXT,
    origin                 TEXT,
    destination            TEXT,
    flight_rules           TEXT,
    planned_departure_utc  TEXT,
    block_off_utc          TEXT,
    wheels_off_utc         TEXT,
    wheels_on_utc          TEXT,
    block_on_utc           TEXT,
    historian_start_utc    TEXT,
    historian_end_utc      TEXT,
    pilot                  TEXT,
    pob                    INTEGER,
    performance_profile    TEXT,
    purpose                TEXT,
    description            TEXT,
    notes                  TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    -- timing diagnostics (spec §52); filled at stop-flight
    expected_10hz_frames   INTEGER,
    actual_10hz_frames     INTEGER,
    mean_sample_period_s   REAL,
    minimum_sample_period_s REAL,
    maximum_sample_period_s REAL,
    timing_overruns        INTEGER
);

CREATE TABLE IF NOT EXISTS flight_source (
    source_id          TEXT PRIMARY KEY,
    flight_id          TEXT NOT NULL REFERENCES flight(flight_id),
    source_type        TEXT NOT NULL,
    source_name        TEXT,
    filename           TEXT,
    file_hash          TEXT,
    original_start_time TEXT,
    original_end_time  TEXT,
    nominal_rate_hz    REAL,
    imported_at        TEXT,
    decoder_name       TEXT,
    decoder_version    TEXT,
    notes              TEXT
);

CREATE TABLE IF NOT EXISTS historian_10hz (
    flight_id           TEXT NOT NULL,
    frame_number        INTEGER NOT NULL,
    historian_time_utc  TEXT NOT NULL,
    flight_time_s       REAL NOT NULL,
    {_real_cols(FIX_10HZ_COLUMNS)}
    PRIMARY KEY (flight_id, frame_number),
    FOREIGN KEY (flight_id) REFERENCES flight(flight_id)
);

CREATE TABLE IF NOT EXISTS historian_1hz (
    flight_id           TEXT NOT NULL,
    frame_number        INTEGER NOT NULL,
    historian_time_utc  TEXT NOT NULL,
    flight_time_s       REAL NOT NULL,
    PRIMARY KEY (flight_id, frame_number),
    FOREIGN KEY (flight_id) REFERENCES flight(flight_id)
);

CREATE TABLE IF NOT EXISTS event (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_id           TEXT NOT NULL REFERENCES flight(flight_id),
    historian_time_utc  TEXT NOT NULL,
    flight_time_s       REAL,
    event_type          TEXT NOT NULL,
    source              TEXT,
    parameter           TEXT,
    value               TEXT,
    text                TEXT,
    metadata_json       TEXT
);

CREATE TABLE IF NOT EXISTS signal (
    fix_key      TEXT PRIMARY KEY,
    column_name  TEXT NOT NULL,
    units        TEXT,
    type         TEXT NOT NULL,
    rate_hz      INTEGER NOT NULL,
    source       TEXT
);

CREATE INDEX IF NOT EXISTS idx_h10_flight_time
    ON historian_10hz(flight_id, historian_time_utc);
CREATE INDEX IF NOT EXISTS idx_h1_flight_time
    ON historian_1hz(flight_id, historian_time_utc);
CREATE INDEX IF NOT EXISTS idx_event_flight_time
    ON event(flight_id, historian_time_utc);
CREATE INDEX IF NOT EXISTS idx_flight_source_flight
    ON flight_source(flight_id);
"""

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return f'"{name}"'


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({quote_ident(table)})")}


def ensure_signal_columns(
    conn: sqlite3.Connection, signals: dict[str, dict[str, Any]]
) -> None:
    """ADD COLUMN for each historian.yaml signal and upsert the signal catalogue."""
    from historian.database.fix_catalog import sqlite_type

    existing = {
        "historian_10hz": table_columns(conn, "historian_10hz"),
        "historian_1hz": table_columns(conn, "historian_1hz"),
    }
    for key, spec in signals.items():
        col = spec["column"]
        table = "historian_10hz" if int(spec.get("rate_hz") or 10) == 10 else "historian_1hz"
        sql_type = sqlite_type(spec.get("type") or "float")
        if col not in existing[table]:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {quote_ident(col)} {sql_type}"
            )
            existing[table].add(col)
        conn.execute(
            """
            INSERT INTO signal(fix_key, column_name, units, type, rate_hz, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(fix_key) DO UPDATE SET
                column_name=excluded.column_name,
                units=excluded.units,
                type=excluded.type,
                rate_hz=excluded.rate_hz,
                source=excluded.source
            """,
            (
                key,
                col,
                spec.get("units") if spec.get("units") is not None else "",
                spec.get("type") or "float",
                int(spec.get("rate_hz") or 10),
                spec.get("source") or "",
            ),
        )
