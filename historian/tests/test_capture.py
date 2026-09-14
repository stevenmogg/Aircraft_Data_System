"""Unit tests for timing / quality / flight id (no FIX required)."""

from __future__ import annotations

from pathlib import Path

from historian.capture.events import QualityTracker
from historian.capture.timing import FlightClock
from historian.database.repository import HistorianDB


def _configs(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "t.sqlite"
    h = tmp_path / "h.yaml"
    a = tmp_path / "a.yaml"
    h.write_text(
        f"""
historian:
  database_path: {db}
  aircraft_id: COZ
  fast_rate_hz: 10
  slow_rate_hz: 1
  fast_signals: {{PITCH: fix_pitch}}
  slow_signals: {{}}
"""
    )
    a.write_text(
        """
aircraft:
  aircraft_id: COZ
  registration: VH-COZ
  type: Cozy III
  description: t
  notes: ""
configuration:
  configuration_id: COZ_CFG_001
  name: Baseline
  description: t
  valid_from: "2026-08-01"
  valid_to: null
  items: []
"""
    )
    return h, a


def test_flight_clock_alignment():
    clock = FlightClock(10.0)
    clock.start()
    f0, t0, _, _ = clock.wait_next(0.2)
    f1, t1, _, _ = clock.wait_next(0.2)
    assert f0 == 0 and abs(t0 - 0.0) < 1e-9
    assert f1 == 1 and abs(t1 - 0.1) < 1e-9


def test_quality_transitions():
    q = QualityTracker()
    assert q.update("PITCH", "", 1.0) == []
    ev = q.update("PITCH", "o", 1.0)
    assert len(ev) == 1 and ev[0].event_type == "PARAMETER_STALE"
    ev = q.update("PITCH", "", 1.0)
    assert len(ev) == 1 and ev[0].event_type == "PARAMETER_RECOVERED"


def test_start_finish_flight(tmp_path: Path):
    h, a = _configs(tmp_path)
    db = HistorianDB.from_config_files(h, a)
    db.init_schema_and_seed()
    fid = db.start_flight("COZ", "COZ_CFG_001")
    assert fid.startswith("COZ-")
    with db.connect() as conn:
        db.insert_10hz(
            conn,
            fid,
            0,
            "2026-08-07T00:00:00.000Z",
            0.0,
            {"fix_pitch": 1.5, "fix_roll": -2.0},
        )
        db.insert_1hz(conn, fid, 0, "2026-08-07T00:00:00.000Z", 0.0, {})
        conn.commit()
    db.finish_flight(fid, {"actual_10hz_frames": 1, "timing_overruns": 0})
    s = db.flight_summary(fid)
    assert s["rows_10hz"] == 1
    assert s["rows_1hz"] == 1
    assert s["last_fix_pitch"] == 1.5
