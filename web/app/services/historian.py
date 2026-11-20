"""Historian daemon / SQLite access for the web layer."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from historian.control import ControlError, send_command, socket_path_from_cfg
from historian.database.repository import HistorianDB, load_yaml

HISTORIAN_YAML = Path("/cozy-data-system/config/historian/historian.yaml")
AIRCRAFT_YAML = Path("/cozy-data-system/config/historian/aircraft.yaml")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return f'"{name}"'


def _hist_cfg() -> dict[str, Any]:
    if HISTORIAN_YAML.exists():
        return load_yaml(HISTORIAN_YAML).get("historian") or {}
    return {}


def _sock():
    return socket_path_from_cfg(_hist_cfg())


def _db() -> HistorianDB:
    return HistorianDB.from_config_files(HISTORIAN_YAML, AIRCRAFT_YAML)


def historian_status() -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "state": "ERROR",
        "daemon": None,
        "database": None,
    }
    try:
        try:
            d = send_command({"cmd": "status"}, sock_path=_sock(), timeout=1.0)
            out["daemon"] = d
            state = d.get("state") or "idle"
            out["state"] = "RECORDING" if state == "recording" else "NOT RECORDING"
            out["flight_id"] = d.get("flight_id")
            out["ok"] = bool(d.get("ok"))
        except ControlError as e:
            out["daemon"] = {"ok": False, "error": str(e)}
            out["state"] = "ERROR"
            out["ok"] = False

        if HISTORIAN_YAML.exists() and AIRCRAFT_YAML.exists():
            st = _db().status()
            out["database"] = {
                "path": st.get("database"),
                "exists": st.get("exists"),
                "rows_flight": st.get("rows_flight"),
                "rows_historian_10hz": st.get("rows_historian_10hz"),
            }
            if st.get("exists"):
                out["ok"] = out.get("ok") or True
        return out
    except Exception as e:
        out["error"] = str(e)
        out["state"] = "ERROR"
        return out


def list_flights(limit: int = 100) -> list[dict[str, Any]]:
    try:
        db = _db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT flight_id, aircraft_id, configuration_id, flight_date,
                       origin, destination, historian_start_utc, historian_end_utc,
                       actual_10hz_frames, timing_overruns, notes, purpose
                FROM flight
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["recording"] = d.get("historian_end_utc") is None
                out.append(d)
            return out
    except Exception:
        return []


def get_flight(flight_id: str) -> dict[str, Any]:
    return _db().flight_summary(flight_id)


def get_manifest(flight_id: str) -> dict[str, Any]:
    db = _db()
    with db.connect() as conn:
        flight = conn.execute(
            "SELECT * FROM flight WHERE flight_id=?", (flight_id,)
        ).fetchone()
        if not flight:
            raise ValueError(f"unknown flight_id {flight_id}")
        sources = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM flight_source WHERE flight_id=? ORDER BY source_id",
                (flight_id,),
            ).fetchall()
        ]
        events_n = conn.execute(
            "SELECT COUNT(*) AS n FROM event WHERE flight_id=?", (flight_id,)
        ).fetchone()["n"]
        return {
            "flight": dict(flight),
            "sources": sources,
            "event_count": events_n,
        }


def start_recording(
    duration_s: float | None = None, flight_id: str | None = None
) -> dict[str, Any]:
    try:
        return send_command(
            {"cmd": "start", "duration_s": duration_s, "flight_id": flight_id},
            sock_path=_sock(),
            timeout=10.0,
        )
    except ControlError as e:
        return {"ok": False, "error": str(e)}


def stop_recording() -> dict[str, Any]:
    try:
        return send_command({"cmd": "stop"}, sock_path=_sock(), timeout=20.0)
    except ControlError as e:
        return {"ok": False, "error": str(e)}


def mark_event(text: str | None = None) -> dict[str, Any]:
    try:
        return send_command(
            {"cmd": "mark", "text": text},
            sock_path=_sock(),
            timeout=5.0,
        )
    except ControlError as e:
        return {"ok": False, "error": str(e)}


_META_COLS = frozenset(
    {"flight_id", "frame_number", "historian_time_utc", "flight_time_s"}
)
_TEXT_TYPES = frozenset({"TEXT", "BLOB", "CLOB"})
_STR_SIGNAL_TYPES = frozenset({"str", "string", "text"})

# Preferred Analysis defaults: MGL pitch, roll, TAS, altitude.
PLOT_DEFAULT_GROUPS = (
    ("MGL_AT_PITCH", "fix_pitch"),
    ("MGL_AT_ROLL", "fix_roll"),
    ("TAS", "MGL_AT_TAS", "MGL_NMEA_GS", "fix_gs"),
    ("MGL_NMEA_ALT", "fix_alt", "fix_palt"),
)

# GPS ground tracks shown on the Analysis map (lat/lon column pairs).
TRACK_SOURCES = (
    ("stratux", "Stratux GPS", "fix_lat", "fix_long", "#5ec8ff"),
    ("mgl_nmea", "MGL GPS", "MGL_NMEA_LAT", "MGL_NMEA_LONG", "#e0b45c"),
    ("avplan", "AvPlan", "avplan_lat", "avplan_lon", "#c084fc"),
)


def _pragma_columns(conn, table: str) -> list[tuple[str, str]]:
    try:
        return [
            (str(r[1]), str(r[2] or "").upper())
            for r in conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        ]
    except Exception:
        return []


def _signal_by_column(conn) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = conn.execute(
            """
            SELECT fix_key, column_name, units, type, rate_hz, source
            FROM signal
            """
        ).fetchall()
    except Exception:
        return out
    for r in rows:
        d = dict(r)
        col = d.get("column_name")
        if col:
            out[str(col)] = d
    return out


_LEGACY_UNITS = {
    "fix_lat": ("STRX_LAT", "deg"),
    "fix_long": ("STRX_LONG", "deg"),
    "fix_pitch": ("STRX_PITCH", "deg"),
    "fix_roll": ("STRX_ROLL", "deg"),
    "fix_head": ("STRX_HEAD", "deg"),
    "fix_alt": ("STRX_ALT", "ft"),
    "fix_palt": ("STRX_PALT", "ft"),
    "fix_vs": ("STRX_VS", "ft/min"),
    "fix_alat": ("STRX_ALAT", "g"),
    "fix_gs": ("STRX_GS", "knots"),
    "fix_track": ("STRX_TRACK", "deg"),
    "avplan_lat": ("avplan_lat", "deg"),
    "avplan_lon": ("avplan_lon", "deg"),
    "avplan_alt": ("avplan_alt", "ft"),
    "avplan_gs": ("avplan_gs", "knots"),
    "avplan_track": ("avplan_track", "deg"),
}


def _yaml_meta_by_column() -> dict[str, dict[str, Any]]:
    """column_name / FIX key → units and labels from historian.yaml."""
    try:
        from historian.database.fix_catalog import load_signals_from_historian_cfg

        sigs = load_signals_from_historian_cfg(_hist_cfg())
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, spec in sigs.items():
        meta = {
            "fix_key": key,
            "units": spec.get("units") or "",
            "type": spec.get("type") or "float",
            "rate_hz": int(spec.get("rate_hz") or 10),
            "source": spec.get("source") or "",
        }
        out[str(spec.get("column") or key)] = meta
        out[str(key)] = meta
    return out


def resolve_plot_defaults(available: list[str]) -> list[str]:
    """Pick up to four plot columns, preferring MGL pitch/roll/TAS/alt."""
    aset = set(available)
    chosen: list[str] = []
    used: set[str] = set()
    for group in PLOT_DEFAULT_GROUPS:
        hit = next((c for c in group if c in aset and c not in used), None)
        if hit:
            chosen.append(hit)
            used.add(hit)
    for col in available:
        if len(chosen) >= 4:
            break
        if col not in used:
            chosen.append(col)
            used.add(col)
    return chosen[:4]


def list_plot_fields() -> dict[str, Any]:
    """Numeric historian columns available to plot, plus resolved defaults."""
    db = _db()
    with db.connect() as conn:
        sigs = _signal_by_column(conn)
        yaml_meta = _yaml_meta_by_column()
        fields: list[dict[str, Any]] = []
        seen: set[str] = set()
        for table, default_rate in (("historian_10hz", 10), ("historian_1hz", 1)):
            for name, sql_type in _pragma_columns(conn, table):
                if name in _META_COLS or name in seen:
                    continue
                sql = sigs.get(name) or {}
                yml = yaml_meta.get(name) or {}
                legacy = _LEGACY_UNITS.get(name)
                sig_type = str(sql.get("type") or yml.get("type") or "").lower()
                if sql_type in _TEXT_TYPES or sig_type in _STR_SIGNAL_TYPES:
                    continue
                seen.add(name)
                fields.append(
                    {
                        "column": name,
                        "fix_key": sql.get("fix_key") or yml.get("fix_key") or (legacy[0] if legacy else name),
                        "units": sql.get("units") or yml.get("units") or (legacy[1] if legacy else ""),
                        "type": sql.get("type") or yml.get("type") or "float",
                        "rate_hz": int(sql.get("rate_hz") or yml.get("rate_hz") or default_rate),
                        "source": sql.get("source") or yml.get("source") or "",
                        "table": table,
                    }
                )
        available = [f["column"] for f in fields]
        return {
            "ok": True,
            "fields": fields,
            "defaults": resolve_plot_defaults(available),
        }


def available_series_columns(conn) -> set[str]:
    cols: set[str] = set()
    for table in ("historian_10hz", "historian_1hz"):
        for name, _typ in _pragma_columns(conn, table):
            if name not in _META_COLS:
                cols.add(name)
    return cols


def _locf(times: list[Any], slow_t: list[Any], slow_v: list[Any]) -> list[Any]:
    out: list[Any] = []
    j = -1
    n = len(slow_t)
    for t in times:
        if t is None:
            out.append(slow_v[j] if j >= 0 else None)
            continue
        while j + 1 < n and slow_t[j + 1] is not None and slow_t[j + 1] <= t:
            j += 1
        out.append(slow_v[j] if j >= 0 else None)
    return out


def series_10hz(
    flight_id: str, columns: list[str], max_points: int = 2000
) -> dict[str, Any]:
    db = _db()
    with db.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"unknown flight_id {flight_id}")
        fast_names = {name for name, _typ in _pragma_columns(conn, "historian_10hz")}
        slow_names = {name for name, _typ in _pragma_columns(conn, "historian_1hz")}
        fast_cols = [c for c in columns if c in fast_names]
        slow_cols = [c for c in columns if c in slow_names and c not in fast_names]
        quoted_fast = ", ".join(
            ["frame_number", "flight_time_s"]
            + [quote_ident(c) for c in fast_cols]
        )
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM historian_10hz WHERE flight_id=?",
            (flight_id,),
        ).fetchone()["n"]
        step = max(1, n // max_points) if n > max_points else 1
        rows = conn.execute(
            f"""
            SELECT {quoted_fast} FROM historian_10hz
            WHERE flight_id=? AND (frame_number % ?) = 0
            ORDER BY frame_number
            """,
            (flight_id, step),
        ).fetchall()
        times = [r["flight_time_s"] for r in rows]
        frames = [r["frame_number"] for r in rows]
        out: dict[str, Any] = {
            "flight_time_s": times,
            "frame_number": frames,
        }
        for c in columns:
            out[c] = []
        for r in rows:
            for c in fast_cols:
                out[c].append(r[c])
        if slow_cols and times:
            quoted_slow = ", ".join(
                ["flight_time_s"] + [quote_ident(c) for c in slow_cols]
            )
            slow_rows = conn.execute(
                f"""
                SELECT {quoted_slow} FROM historian_1hz
                WHERE flight_id=?
                ORDER BY flight_time_s, frame_number
                """,
                (flight_id,),
            ).fetchall()
            slow_t = [r["flight_time_s"] for r in slow_rows]
            for c in slow_cols:
                out[c] = _locf(times, slow_t, [r[c] for r in slow_rows])
        for c in columns:
            if not out[c]:
                out[c] = [None] * len(times)
        out["total_rows"] = n
        out["returned_rows"] = len(rows)
        out["downsample_step"] = step
        return out


def _valid_lat_lon(lat: Any, lon: Any) -> bool:
    try:
        la = float(lat)
        lo = float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(la) and math.isfinite(lo)):
        return False
    if abs(la) < 1e-8 and abs(lo) < 1e-8:
        return False
    return -90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0


def flight_tracks(flight_id: str, max_points: int = 2000) -> dict[str, Any]:
    """Downsampled lat/lon tracks that exist on a flight (Stratux, MGL, AvPlan)."""
    db = _db()
    with db.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"unknown flight_id {flight_id}")
        available = available_series_columns(conn)
    sources = [
        src
        for src in TRACK_SOURCES
        if src[2] in available and src[3] in available
    ]
    cols: list[str] = []
    seen: set[str] = set()
    for _sid, _label, lat_c, lon_c, _color in sources:
        for c in (lat_c, lon_c):
            if c not in seen:
                seen.add(c)
                cols.append(c)
    series = series_10hz(flight_id, cols, max_points=max_points)
    times = series.get("flight_time_s") or []
    tracks: list[dict[str, Any]] = []
    for sid, label, lat_c, lon_c, color in sources:
        lats = series.get(lat_c) or []
        lons = series.get(lon_c) or []
        n_valid = 0
        out_lat: list[Any] = []
        out_lon: list[Any] = []
        for la, lo in zip(lats, lons):
            if _valid_lat_lon(la, lo):
                out_lat.append(float(la))
                out_lon.append(float(lo))
                n_valid += 1
            else:
                out_lat.append(None)
                out_lon.append(None)
        if n_valid < 2:
            continue
        tracks.append(
            {
                "id": sid,
                "label": label,
                "color": color,
                "lat": out_lat,
                "lon": out_lon,
                "valid_points": n_valid,
            }
        )
    return {
        "ok": True,
        "flight_id": flight_id,
        "flight_time_s": times,
        "frame_number": series.get("frame_number") or [],
        "tracks": tracks,
        "total_rows": series.get("total_rows", 0),
        "returned_rows": series.get("returned_rows", 0),
    }


def merge_slow_onto_fast(
    fast: dict[str, Any],
    slow_rows: list[dict[str, Any]],
    index: int,
) -> tuple[dict[str, Any], int]:
    """Attach the latest 1 Hz row with flight_time_s <= fast time. Returns (row, new_index)."""
    t = fast.get("flight_time_s")
    i = index
    if t is not None:
        while i + 1 < len(slow_rows):
            st = slow_rows[i + 1].get("flight_time_s")
            if st is None or st > t:
                break
            i += 1
    row = dict(fast)
    if slow_rows and t is not None:
        st = slow_rows[i].get("flight_time_s")
        if st is not None and st <= t:
            for k, v in slow_rows[i].items():
                if k in _META_COLS or k in row:
                    continue
                row[k] = v
    return row, i


def iter_export_csv(flight_id: str):
    """Yield fieldnames, then one dict per 10 Hz row with 1 Hz fields merged in."""
    db = _db()
    with db.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"unknown flight_id {flight_id}")
        fast_cols = [name for name, _typ in _pragma_columns(conn, "historian_10hz")]
        slow_cols = [
            name
            for name, _typ in _pragma_columns(conn, "historian_1hz")
            if name not in _META_COLS and name not in fast_cols
        ]
        fieldnames = list(fast_cols) + slow_cols
        yield fieldnames
        slow_rows: list[dict[str, Any]] = []
        if slow_cols:
            quoted_slow = ", ".join(
                ["flight_time_s"] + [quote_ident(c) for c in slow_cols]
            )
            slow_rows = [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT {quoted_slow} FROM historian_1hz
                    WHERE flight_id=?
                    ORDER BY flight_time_s, frame_number
                    """,
                    (flight_id,),
                ).fetchall()
            ]
        quoted_fast = ", ".join(quote_ident(c) for c in fast_cols)
        cur = conn.execute(
            f"""
            SELECT {quoted_fast} FROM historian_10hz
            WHERE flight_id=?
            ORDER BY frame_number
            """,
            (flight_id,),
        )
        si = 0
        for r in cur:
            row, si = merge_slow_onto_fast(dict(r), slow_rows, si)
            yield row


def export_10hz_csv_rows(flight_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    it = iter_export_csv(flight_id)
    fieldnames = next(it)
    return list(it), fieldnames


FLIGHT_PLANS_DIR = Path("/cozy-data-system/data/flight-plans")
AVPLAN_IMPORT_DIR = Path("/cozy-data-system/data/historian/imports")


def list_avplan_gpx(flight_id: str | None = None) -> dict[str, Any]:
    from historian.importers.avplan_gpx import (
        suggest_gpx_for_flight,
        summarize_gpx,
    )

    files: list[dict[str, Any]] = []
    if FLIGHT_PLANS_DIR.is_dir():
        for p in sorted(FLIGHT_PLANS_DIR.glob("*.gpx")):
            if p.name.startswith("."):
                continue
            try:
                files.append(summarize_gpx(p))
            except Exception as e:
                files.append({"name": p.name, "error": str(e), "has_track": False})
    flight = None
    if flight_id:
        try:
            flight = get_flight(flight_id)
            files = suggest_gpx_for_flight(flight, files)
        except ValueError:
            flight = None
    return {
        "ok": True,
        "flight_id": flight_id,
        "flight": flight,
        "gpx": files,
        "flight_plans_dir": str(FLIGHT_PLANS_DIR),
    }


def _avplan_gpx_path(gpx_name: str) -> Path:
    safe = Path(gpx_name).name
    if safe != gpx_name or not safe.lower().endswith(".gpx"):
        raise ValueError("gpx_name must be a .gpx file in the flight-plans folder")
    path = FLIGHT_PLANS_DIR / safe
    if not path.is_file():
        raise FileNotFoundError(f"not found: {safe}")
    return path


def import_avplan_gpx(flight_id: str, gpx_name: str) -> dict[str, Any]:
    from historian.importers.avplan_gpx import merge_avplan_into_flight

    path = _avplan_gpx_path(gpx_name)
    db = _db()
    with db.connect() as conn:
        return merge_avplan_into_flight(
            conn, flight_id, path, copy_dir=AVPLAN_IMPORT_DIR
        )


def create_flight_from_avplan(gpx_name: str) -> dict[str, Any]:
    from historian.importers.avplan_gpx import create_flight_from_avplan_gpx

    path = _avplan_gpx_path(gpx_name)
    db = _db()
    aircraft_id = (db.aircraft_cfg.get("aircraft") or {}).get("aircraft_id")
    with db.connect() as conn:
        return create_flight_from_avplan_gpx(
            conn,
            path,
            aircraft_id=aircraft_id,
            copy_dir=AVPLAN_IMPORT_DIR,
        )
