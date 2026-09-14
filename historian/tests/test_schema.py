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
