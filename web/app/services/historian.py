"""Historian daemon / SQLite access for the web layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from historian.control import ControlError, send_command, socket_path_from_cfg
from historian.database.repository import HistorianDB, load_yaml

HISTORIAN_YAML = Path("/cozy-data-system/config/historian/historian.yaml")
AIRCRAFT_YAML = Path("/cozy-data-system/config/historian/aircraft.yaml")


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
        col_sql = ", ".join(["frame_number", "flight_time_s", "historian_time_utc"] + columns)
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM historian_10hz WHERE flight_id=?",
            (flight_id,),
        ).fetchone()["n"]
        step = max(1, n // max_points) if n > max_points else 1
        rows = conn.execute(
            f"""
            SELECT {col_sql} FROM historian_10hz
            WHERE flight_id=? AND (frame_number % ?) = 0
            ORDER BY frame_number
            """,
            (flight_id, step),
        ).fetchall()
        out = {
            "flight_time_s": [],
            "frame_number": [],
        }
        for c in columns:
            out[c] = []
        for r in rows:
            out["flight_time_s"].append(r["flight_time_s"])
            out["frame_number"].append(r["frame_number"])
            for c in columns:
                out[c].append(r[c])
        out["total_rows"] = n
        out["returned_rows"] = len(rows)
        out["downsample_step"] = step
        return out


def export_10hz_csv_rows(flight_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    db = _db()
    with db.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"unknown flight_id {flight_id}")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(historian_10hz)").fetchall()]
        rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT {', '.join(cols)} FROM historian_10hz WHERE flight_id=? ORDER BY frame_number",
                (flight_id,),
            ).fetchall()
        ]
        return rows, cols
