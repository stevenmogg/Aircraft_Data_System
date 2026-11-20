import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from historian.importers.avplan_gpx import (
    match_track_to_frames,
    merge_avplan_into_flight,
    parse_avplan_gpx_file,
    suggest_gpx_for_flight,
    summarize_gpx,
)
from historian.importers.avplan_gpx import TrackPoint


GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="AvPlan" version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><time>2026-09-14T01:00:00Z</time></metadata>
  <rte><name>Home to APL</name></rte>
  <trk>
    <name>Track Log</name>
    <trkseg>
      <trkpt lat="-37.81" lon="144.97"><ele>30.48</ele><time>2026-09-14T01:10:00.000Z</time>
        <extensions><speed>25.72</speed><course>180</course></extensions>
      </trkpt>
      <trkpt lat="-37.82" lon="144.98"><ele>60.96</ele><time>2026-09-14T01:10:00.200Z</time></trkpt>
    </trkseg>
  </trk>
  <extensions>
    <AvPlanPlanDetails xmlns="avplan">
      <AvPlanRules>VFR</AvPlanRules>
      <AvPlanOrigin>Home</AvPlanOrigin>
      <AvPlanDestination>APL</AvPlanDestination>
      <AvPlanPerformanceProfile>55%</AvPlanPerformanceProfile>
    </AvPlanPlanDetails>
  </extensions>
</gpx>
"""


def test_parse_track_and_manifest(tmp_path: Path):
    p = tmp_path / "Home_APL_2110.gpx"
    p.write_text(GPX)
    g = parse_avplan_gpx_file(p)
    assert g.has_track
    assert g.origin == "Home"
    assert g.destination == "APL"
    assert g.day == "2026-09-14"
    assert len(g.track_points) == 2
    assert abs((g.track_points[0].alt_ft or 0) - 100) < 0.1
    assert (g.track_points[0].gs_kt or 0) > 40


def test_summarize_empty_track_is_not_has_track():
    nav = Path(__file__).resolve().parents[2] / "navigation" / "avplan" / "Home_APL_1824.gpx"
    if not nav.is_file():
        return
    s = summarize_gpx(nav)
    assert s["has_track"] is False
    assert s["origin"] == "Home"


def test_same_day_suggestion():
    files = [
        {"name": "a.gpx", "has_track": True, "day": "2026-09-14"},
        {"name": "b.gpx", "has_track": True, "day": "2026-09-13"},
        {"name": "c.gpx", "has_track": False, "day": "2026-09-14"},
    ]
    out = suggest_gpx_for_flight({"historian_start_utc": "2026-09-14T01:05:00Z"}, files)
    assert out[0]["name"] == "a.gpx"
    assert out[0]["suggested"] is True
    assert out[1]["suggested"] is False


def test_match_nearest_frame():
    t0 = datetime(2026, 9, 14, 1, 10, tzinfo=timezone.utc).timestamp()
    frames = [(0, t0), (1, t0 + 0.1), (2, t0 + 0.2)]
    pts = [
        TrackPoint("t", t0 + 0.03, -37.0, 144.0),
        TrackPoint("t", t0 + 0.19, -37.1, 144.1),
    ]
    matched, err, unmatched = match_track_to_frames(frames, pts)
    assert unmatched == 0
    assert 0 in matched
    assert 2 in matched


def _flight_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE flight (
            flight_id TEXT PRIMARY KEY,
            aircraft_id TEXT,
            origin TEXT,
            destination TEXT,
            flight_rules TEXT,
            pob INTEGER,
            performance_profile TEXT,
            wheels_off_utc TEXT,
            historian_start_utc TEXT,
            historian_end_utc TEXT,
            updated_at TEXT
        );
        CREATE TABLE historian_10hz (
            flight_id TEXT,
            frame_number INTEGER,
            historian_time_utc TEXT,
            flight_time_s REAL,
            PRIMARY KEY (flight_id, frame_number)
        );
        CREATE TABLE flight_source (
            source_id TEXT PRIMARY KEY,
            flight_id TEXT,
            source_type TEXT,
            source_name TEXT,
            filename TEXT,
            file_hash TEXT,
            original_start_time TEXT,
            original_end_time TEXT,
            nominal_rate_hz REAL,
            imported_at TEXT,
            decoder_name TEXT,
            decoder_version TEXT,
            notes TEXT
        );
        INSERT INTO flight(
            flight_id, aircraft_id, historian_start_utc, historian_end_utc, updated_at
        ) VALUES (
            'COZ-20260914-01', 'COZ',
            '2026-09-14T01:05:00.000Z', '2026-09-14T01:20:00.000Z',
            '2026-09-14T01:20:00Z'
        );
        INSERT INTO historian_10hz VALUES
            ('COZ-20260914-01', 0, '2026-09-14T01:10:00.000Z', 300.0),
            ('COZ-20260914-01', 1, '2026-09-14T01:10:00.100Z', 300.1),
            ('COZ-20260914-01', 2, '2026-09-14T01:10:00.200Z', 300.2);
        """
    )
    conn.commit()
    return conn


def test_merge_writes_avplan_columns(tmp_path: Path):
    db = tmp_path / "h.sqlite"
    conn = _flight_db(db)
    gpx = tmp_path / "Home_APL_2110.gpx"
    gpx.write_text(GPX)
    result = merge_avplan_into_flight(conn, "COZ-20260914-01", gpx, copy_dir=tmp_path / "imp")
    assert result["ok"] is True
    assert result["frames_updated"] == 2
    row = conn.execute(
        "SELECT avplan_lat, avplan_alt, origin FROM historian_10hz "
        "JOIN flight USING (flight_id) WHERE frame_number=0"
    ).fetchone()
    assert row["avplan_lat"] == -37.81
    assert abs(row["avplan_alt"] - 100) < 0.2
    assert row["origin"] == "Home"
    src = conn.execute("SELECT source_type FROM flight_source").fetchone()
    assert src["source_type"] == "AVPLAN_GPX"
    assert (tmp_path / "imp" / "COZ-20260914-01" / "avplan.gpx").is_file()


def _standalone_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE aircraft (aircraft_id TEXT PRIMARY KEY);
        INSERT INTO aircraft VALUES ('COZ');
        CREATE TABLE flight (
            flight_id TEXT PRIMARY KEY,
            aircraft_id TEXT NOT NULL,
            flight_date TEXT,
            origin TEXT,
            destination TEXT,
            flight_rules TEXT,
            wheels_off_utc TEXT,
            wheels_on_utc TEXT,
            historian_start_utc TEXT,
            historian_end_utc TEXT,
            pob INTEGER,
            performance_profile TEXT,
            purpose TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            expected_10hz_frames INTEGER,
            actual_10hz_frames INTEGER,
            mean_sample_period_s REAL,
            minimum_sample_period_s REAL,
            maximum_sample_period_s REAL,
            timing_overruns INTEGER
        );
        CREATE TABLE historian_10hz (
            flight_id TEXT,
            frame_number INTEGER,
            historian_time_utc TEXT,
            flight_time_s REAL,
            fix_lat REAL,
            fix_long REAL,
            fix_alt REAL,
            fix_gs REAL,
            fix_track REAL,
            PRIMARY KEY (flight_id, frame_number)
        );
        CREATE TABLE flight_source (
            source_id TEXT PRIMARY KEY,
            flight_id TEXT,
            source_type TEXT,
            source_name TEXT,
            filename TEXT,
            file_hash TEXT,
            original_start_time TEXT,
            original_end_time TEXT,
            nominal_rate_hz REAL,
            imported_at TEXT,
            decoder_name TEXT,
            decoder_version TEXT,
            notes TEXT
        );
        CREATE TABLE event (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT,
            historian_time_utc TEXT,
            flight_time_s REAL,
            event_type TEXT,
            source TEXT,
            text TEXT
        );
        """
    )
    conn.commit()
    return conn


def test_create_flight_from_gpx_alone(tmp_path: Path):
    from historian.importers.avplan_gpx import create_flight_from_avplan_gpx

    conn = _standalone_db(tmp_path / "h.sqlite")
    gpx = tmp_path / "Home_APL_2110.gpx"
    gpx.write_text(GPX)
    result = create_flight_from_avplan_gpx(
        conn, gpx, aircraft_id="COZ", copy_dir=tmp_path / "imp"
    )
    assert result["ok"] is True
    assert result["created"] is True
    assert result["flight_id"] == "COZ-20260914-01"
    assert result["frames_created"] == 2
    flight = conn.execute("SELECT * FROM flight WHERE flight_id=?", ("COZ-20260914-01",)).fetchone()
    assert flight["origin"] == "Home"
    assert flight["destination"] == "APL"
    assert flight["flight_rules"] == "VFR"
    assert flight["historian_end_utc"] is not None
    row0 = conn.execute(
        "SELECT * FROM historian_10hz WHERE flight_id=? AND frame_number=0",
        ("COZ-20260914-01",),
    ).fetchone()
    assert row0["avplan_lat"] == -37.81
    assert abs((row0["avplan_alt"] or 0) - 100) < 0.2
    assert row0["fix_lat"] == -37.81
    assert row0["flight_time_s"] == 0.0
    row1 = conn.execute(
        "SELECT flight_time_s FROM historian_10hz WHERE frame_number=1"
    ).fetchone()
    assert abs(row1["flight_time_s"] - 0.2) < 0.001
    src = conn.execute("SELECT notes, nominal_rate_hz FROM flight_source").fetchone()
    assert "standalone" in src["notes"]
    assert (tmp_path / "imp" / "COZ-20260914-01" / "avplan.gpx").is_file()


def test_create_flight_rejects_duplicate_hash(tmp_path: Path):
    from historian.importers.avplan_gpx import create_flight_from_avplan_gpx

    conn = _standalone_db(tmp_path / "h.sqlite")
    gpx = tmp_path / "Home_APL_2110.gpx"
    gpx.write_text(GPX)
    create_flight_from_avplan_gpx(conn, gpx, aircraft_id="COZ")
    try:
        create_flight_from_avplan_gpx(conn, gpx, aircraft_id="COZ")
        raise AssertionError("expected duplicate import to fail")
    except ValueError as e:
        assert "already imported" in str(e)


def test_create_flight_rejects_plan_only_gpx(tmp_path: Path):
    from historian.importers.avplan_gpx import create_flight_from_avplan_gpx

    conn = _standalone_db(tmp_path / "h.sqlite")
    gpx = tmp_path / "plan.gpx"
    gpx.write_text(
        """<?xml version="1.0"?><gpx><rte><name>Plan</name></rte></gpx>"""
    )
    try:
        create_flight_from_avplan_gpx(conn, gpx, aircraft_id="COZ")
        raise AssertionError("expected plan-only GPX to fail")
    except ValueError as e:
        assert "no timed track" in str(e)
