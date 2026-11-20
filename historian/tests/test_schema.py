"""Schema init tests (run on Mac or Pi)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from historian.database.repository import HistorianDB
from historian.database.schema import FIX_10HZ_COLUMNS, SCHEMA_VERSION


@pytest.fixture
def configs(tmp_path: Path) -> tuple[Path, Path]:
    h = tmp_path / "historian.yaml"
    a = tmp_path / "aircraft.yaml"
    db = tmp_path / "test.sqlite"
    h.write_text(
        f"""
historian:
  database_path: {db}
  aircraft_id: COZ
  fast_rate_hz: 10
  slow_rate_hz: 1
  fast_signals: {{}}
  slow_signals: {{}}
"""
    )
    a.write_text(
        """
aircraft:
  aircraft_id: COZ
  registration: VH-COZ
  type: Cozy III
  description: test
  notes: ""
configuration:
  configuration_id: COZ_CFG_001
  name: Baseline
  description: test cfg
  valid_from: "2026-08-01"
  valid_to: null
  items:
    - { category: avionics, item: ads_b, value: Stratux, units: "", notes: "" }
"""
    )
    return h, a


def test_init_schema_and_seed(configs):
    h, a = configs
    db = HistorianDB.from_config_files(h, a)
    created = db.init_schema_and_seed()
    assert created["schema"] is True
    assert created["aircraft"] is True
    assert created["configuration"] is True

    # idempotent
    created2 = db.init_schema_and_seed()
    assert created2["schema"] is False
    assert created2["aircraft"] is False

    st = db.status()
    assert st["schema_version"] == SCHEMA_VERSION
    assert st["rows_aircraft"] == 1
    assert st["rows_aircraft_configuration"] == 1
    assert st["rows_configuration_item"] == 1

    with db.connect() as conn:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(historian_10hz)").fetchall()
        }
        for c in FIX_10HZ_COLUMNS:
            assert c in cols
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "signal" in tables


def test_signal_columns_and_units(tmp_path: Path):
    h = tmp_path / "historian.yaml"
    a = tmp_path / "aircraft.yaml"
    dbp = tmp_path / "test.sqlite"
    h.write_text(
        f"""
historian:
  database_path: {dbp}
  aircraft_id: COZ
  signals:
    PITCH:
      column: fix_pitch
      units: deg
      type: float
      rate_hz: 10
      source: ahrs
    MGL_AT_PITCH:
      column: MGL_AT_PITCH
      units: deg
      type: float
      rate_hz: 10
      source: mgl_airtalk
    MGL_RDAC_TEMP:
      column: MGL_RDAC_TEMP
      units: degF
      type: float
      rate_hz: 10
      source: mgl_rdac
    MGL_NMEA_ALT:
      column: MGL_NMEA_ALT
      units: ft
      type: float
      rate_hz: 10
      source: mgl_nmea
    BTN1:
      column: BTN1
      units: ""
      type: bool
      rate_hz: 1
      source: generic
    MGL_NMEA_GGA_RAW:
      column: MGL_NMEA_GGA_RAW
      units: ""
      type: str
      rate_hz: 1
      source: mgl_nmea
"""
    )
    a.write_text(
        """
aircraft:
  aircraft_id: COZ
  registration: VH-COZ
  type: Cozy III
  description: test
  notes: ""
configuration:
  configuration_id: COZ_CFG_001
  name: Baseline
  description: test cfg
  valid_from: "2026-08-01"
  valid_to: null
  items: []
"""
    )
    db = HistorianDB.from_config_files(h, a)
    db.init_schema_and_seed()
    with db.connect() as conn:
        cols10 = {r[1] for r in conn.execute("PRAGMA table_info(historian_10hz)")}
        cols1 = {r[1] for r in conn.execute("PRAGMA table_info(historian_1hz)")}
        assert "fix_pitch" in cols10
        assert "MGL_AT_PITCH" in cols10
        assert "MGL_RDAC_TEMP" in cols10
        assert "MGL_NMEA_ALT" in cols10
        assert "BTN1" in cols1
        assert "MGL_NMEA_GGA_RAW" in cols1
        types1 = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(historian_1hz)")}
        assert types1["BTN1"].upper() == "INTEGER"
        assert types1["MGL_NMEA_GGA_RAW"].upper() == "TEXT"
        row = conn.execute(
            "SELECT units, type, rate_hz FROM signal WHERE fix_key='MGL_RDAC_TEMP'"
        ).fetchone()
        assert row["units"] == "degF"
        assert row["type"] == "float"
        assert row["rate_hz"] == 10
        nmea = conn.execute(
            "SELECT units FROM signal WHERE fix_key='MGL_NMEA_ALT'"
        ).fetchone()
        assert nmea["units"] == "ft"


def test_foreign_keys(configs):
    h, a = configs
    db = HistorianDB.from_config_files(h, a)
    db.init_schema_and_seed()
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO flight(flight_id, aircraft_id, created_at, updated_at) "
                "VALUES ('X', 'NOPE', 't', 't')"
            )
            conn.commit()
