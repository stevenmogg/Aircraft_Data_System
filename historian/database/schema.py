"""SQLite schema for Cozy Aircraft Historian (spec §5–§13, §53)."""

from __future__ import annotations

SCHEMA_VERSION = 1

# Wide-table FIX columns for Stage 1 live capture (prefix fix_).
# Secondary sources (mgl_*, avplan_*) are added in later schema versions.
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

CREATE INDEX IF NOT EXISTS idx_h10_flight_time
    ON historian_10hz(flight_id, historian_time_utc);
CREATE INDEX IF NOT EXISTS idx_h1_flight_time
    ON historian_1hz(flight_id, historian_time_utc);
CREATE INDEX IF NOT EXISTS idx_event_flight_time
    ON event(flight_id, historian_time_utc);
CREATE INDEX IF NOT EXISTS idx_flight_source_flight
    ON flight_source(flight_id);
"""
