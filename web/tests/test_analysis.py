import sqlite3

from web.app.services.historian import merge_slow_onto_fast, resolve_plot_defaults
from web.app.services import historian as hist_svc


def test_plot_defaults_prefer_mgl_pitch_roll_tas_alt():
    available = [
        "fix_pitch",
        "fix_roll",
        "fix_gs",
        "fix_alt",
        "MGL_AT_PITCH",
        "MGL_AT_ROLL",
        "MGL_NMEA_GS",
        "MGL_NMEA_ALT",
        "MGL_RDAC_RPM1",
    ]
    assert resolve_plot_defaults(available) == [
        "MGL_AT_PITCH",
        "MGL_AT_ROLL",
        "MGL_NMEA_GS",
        "MGL_NMEA_ALT",
    ]


def test_plot_defaults_fall_back_without_mgl():
    assert resolve_plot_defaults(["fix_pitch", "fix_roll", "fix_gs", "fix_alt"]) == [
        "fix_pitch",
        "fix_roll",
        "fix_gs",
        "fix_alt",
    ]


def test_plot_defaults_use_tas_when_present():
    available = ["MGL_AT_PITCH", "MGL_AT_ROLL", "TAS", "MGL_NMEA_GS", "MGL_NMEA_ALT"]
    assert resolve_plot_defaults(available) == [
        "MGL_AT_PITCH",
        "MGL_AT_ROLL",
        "TAS",
        "MGL_NMEA_ALT",
    ]


def test_merge_slow_onto_fast_locf():
    slow = [
        {"flight_time_s": 0.0, "BAT_VOLTAGE": 12.0},
        {"flight_time_s": 1.0, "BAT_VOLTAGE": 12.4},
    ]
    row, i = merge_slow_onto_fast({"flight_time_s": 0.3, "MGL_AT_PITCH": 1.0}, slow, 0)
    assert i == 0
    assert row["BAT_VOLTAGE"] == 12.0
    row, i = merge_slow_onto_fast({"flight_time_s": 1.2, "MGL_AT_PITCH": 2.0}, slow, i)
    assert i == 1
    assert row["BAT_VOLTAGE"] == 12.4
    assert row["MGL_AT_PITCH"] == 2.0


class _WrapDB:
    def __init__(self, path: str):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def test_export_includes_1hz_fields(tmp_path, monkeypatch):
    db_path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE flight (flight_id TEXT PRIMARY KEY);
        CREATE TABLE historian_10hz (
            flight_id TEXT, frame_number INTEGER, historian_time_utc TEXT, flight_time_s REAL,
            MGL_AT_PITCH REAL, MGL_NMEA_ALT REAL
        );
        CREATE TABLE historian_1hz (
            flight_id TEXT, frame_number INTEGER, historian_time_utc TEXT, flight_time_s REAL,
            BAT_VOLTAGE REAL, MGL_NMEA_RAW TEXT
        );
        INSERT INTO flight VALUES ('F1');
        INSERT INTO historian_10hz VALUES ('F1', 0, 't0', 0.0, 1.0, 1000.0);
        INSERT INTO historian_10hz VALUES ('F1', 1, 't1', 0.5, 1.5, 1001.0);
        INSERT INTO historian_1hz VALUES ('F1', 0, 's0', 0.0, 12.1, 'gga');
        INSERT INTO historian_1hz VALUES ('F1', 1, 's1', 1.0, 12.6, 'rmc');
        """
    )
    conn.close()
    monkeypatch.setattr(hist_svc, "_db", lambda: _WrapDB(str(db_path)))
    it = hist_svc.iter_export_csv("F1")
    names = next(it)
    rows = list(it)
    assert "MGL_AT_PITCH" in names
    assert "MGL_NMEA_ALT" in names
    assert "BAT_VOLTAGE" in names
    assert "MGL_NMEA_RAW" in names
    assert rows[0]["BAT_VOLTAGE"] == 12.1
    assert rows[0]["MGL_NMEA_RAW"] == "gga"
    assert rows[1]["BAT_VOLTAGE"] == 12.1
    assert len(rows) == 2


def test_plot_fields_fill_units_from_yaml(tmp_path, monkeypatch):
    db_path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE historian_10hz (
            flight_id TEXT, frame_number INTEGER, historian_time_utc TEXT, flight_time_s REAL,
            fix_pitch REAL
        );
        """
    )
    conn.close()
    monkeypatch.setattr(hist_svc, "_db", lambda: _WrapDB(str(db_path)))
    monkeypatch.setattr(
        hist_svc,
        "_hist_cfg",
        lambda: {
            "signals": {
                "STRX_PITCH": {"column": "fix_pitch", "units": "deg", "type": "float", "rate_hz": 10}
            }
        },
    )
    meta = hist_svc.list_plot_fields()
    pitch = next(f for f in meta["fields"] if f["column"] == "fix_pitch")
    assert pitch["units"] == "deg"
    assert pitch["fix_key"] == "STRX_PITCH"


def test_flight_tracks_lists_valid_gps_sources(tmp_path, monkeypatch):
    db_path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE flight (flight_id TEXT PRIMARY KEY);
        CREATE TABLE historian_10hz (
            flight_id TEXT, frame_number INTEGER, historian_time_utc TEXT, flight_time_s REAL,
            fix_lat REAL, fix_long REAL,
            MGL_NMEA_LAT REAL, MGL_NMEA_LONG REAL,
            avplan_lat REAL, avplan_lon REAL
        );
        INSERT INTO flight VALUES ('F1');
        INSERT INTO historian_10hz VALUES ('F1', 0, 't0', 0.0, -37.8, 144.97, -37.81, 144.98, -37.82, 144.99);
        INSERT INTO historian_10hz VALUES ('F1', 1, 't1', 0.1, 0.0, 0.0, -37.80, 144.97, -37.81, 144.98);
        INSERT INTO historian_10hz VALUES ('F1', 2, 't2', 0.2, -37.79, 144.96, -37.79, 144.96, NULL, NULL);
        INSERT INTO historian_10hz VALUES ('F1', 3, 't3', 0.3, -37.78, 144.95, NULL, NULL, NULL, NULL);
        """
    )
    conn.close()
    monkeypatch.setattr(hist_svc, "_db", lambda: _WrapDB(str(db_path)))
    payload = hist_svc.flight_tracks("F1")
    ids = [t["id"] for t in payload["tracks"]]
    assert ids == ["stratux", "mgl_nmea", "avplan"]
    by_id = {t["id"]: t for t in payload["tracks"]}
    assert by_id["stratux"]["color"] == "#5ec8ff"
    assert by_id["mgl_nmea"]["label"] == "MGL GPS"
    assert by_id["avplan"]["valid_points"] == 2
    assert by_id["stratux"]["lat"][1] is None
    assert payload["flight_time_s"] == [0.0, 0.1, 0.2, 0.3]


def test_flight_tracks_skips_sources_with_one_point(tmp_path, monkeypatch):
    db_path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE flight (flight_id TEXT PRIMARY KEY);
        CREATE TABLE historian_10hz (
            flight_id TEXT, frame_number INTEGER, historian_time_utc TEXT, flight_time_s REAL,
            fix_lat REAL, fix_long REAL
        );
        INSERT INTO flight VALUES ('F1');
        INSERT INTO historian_10hz VALUES ('F1', 0, 't0', 0.0, -37.8, 144.97);
        INSERT INTO historian_10hz VALUES ('F1', 1, 't1', 0.1, 0.0, 0.0);
        """
    )
    conn.close()
    monkeypatch.setattr(hist_svc, "_db", lambda: _WrapDB(str(db_path)))
    payload = hist_svc.flight_tracks("F1")
    assert payload["tracks"] == []


def test_plot_fields_legacy_units_without_yaml(tmp_path, monkeypatch):
    db_path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE historian_10hz (
            flight_id TEXT, frame_number INTEGER, historian_time_utc TEXT, flight_time_s REAL,
            fix_gs REAL
        );
        """
    )
    conn.close()
    monkeypatch.setattr(hist_svc, "_db", lambda: _WrapDB(str(db_path)))
    monkeypatch.setattr(hist_svc, "_hist_cfg", lambda: {})
    gs = next(f for f in hist_svc.list_plot_fields()["fields"] if f["column"] == "fix_gs")
    assert gs["units"] == "knots"
    assert gs["fix_key"] == "STRX_GS"
