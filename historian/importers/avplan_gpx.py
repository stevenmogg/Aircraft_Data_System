"""AvPlan GPX — parse route + track, merge track onto Historian 10 Hz frames."""

from __future__ import annotations

import hashlib
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MS_TO_KNOTS = 1.9438444924406
M_TO_FT = 3.280839895
MAX_SYNC_MS = 500.0
AVPLAN_COLUMNS = (
    "avplan_lat",
    "avplan_lon",
    "avplan_alt",
    "avplan_gs",
    "avplan_track",
    "avplan_hdop",
    "avplan_source_time",
    "avplan_sync_error_ms",
)
# Copy track onto FIX columns so Analysis defaults (GS / Alt / track) have data.
_FIX_FROM_TRACK = (
    ("fix_lat", "lat"),
    ("fix_long", "lon"),
    ("fix_alt", "alt_ft"),
    ("fix_gs", "gs_kt"),
    ("fix_track", "track_deg"),
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_gpx_time(text: str | None) -> datetime | None:
    if not text:
        return None
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_historian_time(text: str | None) -> datetime | None:
    return parse_gpx_time(text)


@dataclass
class TrackPoint:
    time_utc: str | None
    t_epoch: float | None
    lat: float
    lon: float
    alt_ft: float | None = None
    gs_kt: float | None = None
    track_deg: float | None = None
    hdop: float | None = None


@dataclass
class GpxFlight:
    path: Path
    route_name: str = ""
    origin: str | None = None
    destination: str | None = None
    rules: str | None = None
    aircraft: str | None = None
    pob: int | None = None
    performance_profile: str | None = None
    metadata_time_utc: str | None = None
    track_points: list[TrackPoint] = field(default_factory=list)

    @property
    def has_track(self) -> bool:
        return any(p.t_epoch is not None for p in self.track_points)

    @property
    def track_start_utc(self) -> str | None:
        timed = [p.time_utc for p in self.track_points if p.time_utc]
        return timed[0] if timed else None

    @property
    def track_end_utc(self) -> str | None:
        timed = [p.time_utc for p in self.track_points if p.time_utc]
        return timed[-1] if timed else None

    @property
    def day(self) -> str | None:
        for value in (self.track_start_utc, self.metadata_time_utc):
            if value and len(value) >= 10:
                return value[:10]
        return None


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    s = el.text.strip()
    return s or None


def _float(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def _int(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(float(text.strip()))
    except ValueError:
        return None


def parse_avplan_gpx_file(path: Path) -> GpxFlight:
    tree = ET.parse(path)
    root = tree.getroot()
    flight = GpxFlight(path=path, route_name=path.stem)

    for el in root.iter():
        tag = _local(el.tag)
        if tag == "metadata":
            for child in el:
                if _local(child.tag) == "time":
                    dt = parse_gpx_time(_text(child))
                    flight.metadata_time_utc = iso_z(dt)
        elif tag == "rte":
            for child in el:
                if _local(child.tag) == "name" and _text(child):
                    flight.route_name = _text(child) or flight.route_name
        elif tag == "AvPlanPlanDetails":
            for child in el:
                ct = _local(child.tag)
                val = _text(child)
                if ct == "AvPlanOrigin":
                    flight.origin = val
                elif ct == "AvPlanDestination":
                    flight.destination = val
                elif ct == "AvPlanRules":
                    flight.rules = val
                elif ct == "AvPlanAircraft":
                    flight.aircraft = val
                elif ct == "AvPlanPerformanceProfile":
                    flight.performance_profile = val
        elif tag == "AvPlanLegDetails":
            for child in el:
                if _local(child.tag) == "AvPlanPOB":
                    flight.pob = _int(_text(child))
        elif tag == "trkpt":
            pt = _parse_trkpt(el)
            if pt is not None:
                flight.track_points.append(pt)

    flight.track_points.sort(key=lambda p: (p.t_epoch is None, p.t_epoch or 0.0))
    return flight


def _parse_trkpt(el: ET.Element) -> TrackPoint | None:
    try:
        lat = float(el.attrib["lat"])
        lon = float(el.attrib["lon"])
    except (KeyError, ValueError):
        return None
    time_utc = None
    t_epoch = None
    alt_ft = None
    gs_kt = None
    track_deg = None
    hdop = None
    for child in el:
        tag = _local(child.tag)
        if tag == "time":
            dt = parse_gpx_time(_text(child))
            if dt is not None:
                time_utc = iso_z(dt)
                t_epoch = dt.timestamp()
        elif tag == "ele":
            metres = _float(_text(child))
            if metres is not None:
                alt_ft = metres * M_TO_FT
        elif tag == "course":
            track_deg = _float(_text(child))
        elif tag == "speed":
            ms = _float(_text(child))
            if ms is not None:
                gs_kt = ms * MS_TO_KNOTS
        elif tag == "hdop":
            hdop = _float(_text(child))
        elif tag == "extensions":
            for ext in child.iter():
                et = _local(ext.tag)
                if et == "speed" and gs_kt is None:
                    ms = _float(_text(ext))
                    if ms is not None:
                        gs_kt = ms * MS_TO_KNOTS
                elif et in ("course", "Track") and track_deg is None:
                    track_deg = _float(_text(ext))
                elif et == "hdop" and hdop is None:
                    hdop = _float(_text(ext))
    return TrackPoint(
        time_utc=time_utc,
        t_epoch=t_epoch,
        lat=lat,
        lon=lon,
        alt_ft=alt_ft,
        gs_kt=gs_kt,
        track_deg=track_deg,
        hdop=hdop,
    )


def summarize_gpx(path: Path) -> dict[str, Any]:
    g = parse_avplan_gpx_file(path)
    st = path.stat()
    return {
        "name": path.name,
        "bytes": st.st_size,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "route_name": g.route_name,
        "origin": g.origin,
        "destination": g.destination,
        "rules": g.rules,
        "aircraft": g.aircraft,
        "pob": g.pob,
        "has_track": g.has_track,
        "track_points": len(g.track_points),
        "track_start_utc": g.track_start_utc,
        "track_end_utc": g.track_end_utc,
        "metadata_time_utc": g.metadata_time_utc,
        "day": g.day,
    }


def flight_day(flight: dict[str, Any]) -> str | None:
    for key in ("historian_start_utc", "flight_date"):
        val = flight.get(key)
        if val and len(str(val)) >= 10:
            return str(val)[:10]
    return None


def suggest_gpx_for_flight(
    flight: dict[str, Any], files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Same UTC day + has track first; others follow."""
    day = flight_day(flight)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in files:
        score = 0
        if item.get("has_track"):
            score += 2
        if day and item.get("day") == day:
            score += 4
        ranked.append((score, item))
    ranked.sort(key=lambda x: (-x[0], x[1].get("name") or ""))
    out = []
    for score, item in ranked:
        row = dict(item)
        row["same_day"] = bool(day and item.get("day") == day)
        row["suggested"] = score >= 6
        out.append(row)
    return out


def ensure_avplan_columns(conn: sqlite3.Connection) -> None:
    existing = {
        r[1] for r in conn.execute("PRAGMA table_info(historian_10hz)").fetchall()
    }
    types = {
        "avplan_lat": "REAL",
        "avplan_lon": "REAL",
        "avplan_alt": "REAL",
        "avplan_gs": "REAL",
        "avplan_track": "REAL",
        "avplan_hdop": "REAL",
        "avplan_source_time": "TEXT",
        "avplan_sync_error_ms": "REAL",
    }
    for name in AVPLAN_COLUMNS:
        if name not in existing:
            conn.execute(f'ALTER TABLE historian_10hz ADD COLUMN "{name}" {types[name]}')


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def match_track_to_frames(
    frames: list[tuple[int, float]],
    points: list[TrackPoint],
    max_sync_ms: float = MAX_SYNC_MS,
) -> tuple[dict[int, TrackPoint], dict[int, float], int]:
    """Map frame_number → closest track point within max_sync_ms."""
    by_frame: dict[int, TrackPoint] = {}
    err_ms: dict[int, float] = {}
    unmatched = 0
    if not frames:
        return by_frame, err_ms, len([p for p in points if p.t_epoch is not None])
    i = 0
    n = len(frames)
    for pt in points:
        if pt.t_epoch is None:
            unmatched += 1
            continue
        while i + 1 < n and abs(frames[i + 1][1] - pt.t_epoch) <= abs(
            frames[i][1] - pt.t_epoch
        ):
            i += 1
        frame_n, t = frames[i]
        delta = abs(t - pt.t_epoch) * 1000.0
        if delta > max_sync_ms:
            unmatched += 1
            continue
        prev = err_ms.get(frame_n)
        if prev is None or delta < prev:
            by_frame[frame_n] = pt
            err_ms[frame_n] = delta
    return by_frame, err_ms, unmatched


def merge_avplan_into_flight(
    conn: sqlite3.Connection,
    flight_id: str,
    gpx_path: Path,
    *,
    copy_dir: Path | None = None,
) -> dict[str, Any]:
    flight_row = conn.execute(
        "SELECT * FROM flight WHERE flight_id=?", (flight_id,)
    ).fetchone()
    if not flight_row:
        raise ValueError(f"unknown flight_id {flight_id}")
    flight = dict(flight_row)
    if flight.get("historian_end_utc") is None:
        raise ValueError("flight is still recording — stop record before merge")

    parsed = parse_avplan_gpx_file(gpx_path)
    if not parsed.has_track:
        raise ValueError(f"{gpx_path.name} has no timed track points")

    ensure_avplan_columns(conn)
    rows = conn.execute(
        """
        SELECT frame_number, historian_time_utc FROM historian_10hz
        WHERE flight_id=? ORDER BY frame_number
        """,
        (flight_id,),
    ).fetchall()
    frames: list[tuple[int, float]] = []
    for r in rows:
        dt = parse_historian_time(r["historian_time_utc"] if not isinstance(r, tuple) else r[1])
        if dt is None:
            continue
        frame_n = r["frame_number"] if not isinstance(r, tuple) else r[0]
        frames.append((int(frame_n), dt.timestamp()))

    matched, errors, unmatched = match_track_to_frames(frames, parsed.track_points)
    if not matched:
        raise ValueError(
            "no AvPlan track times fell within 500 ms of a historian frame "
            "(check clocks / same flight)"
        )

    nulls = ", ".join(f'"{c}"=NULL' for c in AVPLAN_COLUMNS)
    conn.execute(
        f'UPDATE historian_10hz SET {nulls} WHERE flight_id=?',
        (flight_id,),
    )
    sql = (
        "UPDATE historian_10hz SET "
        "avplan_lat=?, avplan_lon=?, avplan_alt=?, avplan_gs=?, avplan_track=?, "
        "avplan_hdop=?, avplan_source_time=?, avplan_sync_error_ms=? "
        "WHERE flight_id=? AND frame_number=?"
    )
    for frame_n, pt in matched.items():
        conn.execute(
            sql,
            (
                pt.lat,
                pt.lon,
                pt.alt_ft,
                pt.gs_kt,
                pt.track_deg,
                pt.hdop,
                pt.time_utc,
                round(errors[frame_n], 1),
                flight_id,
                frame_n,
            ),
        )

    stored = str(gpx_path)
    if copy_dir is not None:
        dest_dir = copy_dir / flight_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "avplan.gpx"
        dest.write_bytes(gpx_path.read_bytes())
        stored = str(dest)

    digest = _file_sha256(gpx_path)
    source_id = f"{flight_id}_AVPLAN_GPX"
    conn.execute("DELETE FROM flight_source WHERE source_id=?", (source_id,))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO flight_source(
            source_id, flight_id, source_type, source_name, filename, file_hash,
            original_start_time, original_end_time, nominal_rate_hz, imported_at,
            decoder_name, decoder_version, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            flight_id,
            "AVPLAN_GPX",
            parsed.route_name,
            gpx_path.name,
            digest,
            parsed.track_start_utc,
            parsed.track_end_utc,
            None,
            now,
            "avplan_gpx",
            "1",
            f"matched={len(matched)} unmatched={unmatched}",
        ),
    )

    def fill(col: str, value: Any) -> None:
        if value is None:
            return
        current = flight.get(col)
        if current is None or current == "":
            conn.execute(
                f'UPDATE flight SET "{col}"=?, updated_at=? WHERE flight_id=?',
                (value, now, flight_id),
            )

    fill("origin", parsed.origin)
    fill("destination", parsed.destination)
    fill("flight_rules", parsed.rules)
    fill("pob", parsed.pob)
    fill("performance_profile", parsed.performance_profile)
    if parsed.track_start_utc and not flight.get("wheels_off_utc"):
        fill("wheels_off_utc", parsed.track_start_utc)

    errs = list(errors.values())
    conn.commit()
    return {
        "ok": True,
        "flight_id": flight_id,
        "gpx": gpx_path.name,
        "route_name": parsed.route_name,
        "track_points": len(parsed.track_points),
        "frames_updated": len(matched),
        "track_unmatched": unmatched,
        "mean_sync_error_ms": round(sum(errs) / len(errs), 1) if errs else None,
        "max_sync_error_ms": round(max(errs), 1) if errs else None,
        "file_hash": digest,
        "stored_copy": stored,
        "same_day": flight_day(flight) == parsed.day,
    }


def _row_val(row: Any, key: str, idx: int = 0) -> Any:
    if isinstance(row, sqlite3.Row):
        return row[key]
    if isinstance(row, dict):
        return row[key]
    return row[idx]


def next_flight_id(conn: sqlite3.Connection, aircraft_id: str, day_compact: str) -> str:
    """Allocate COZ-YYYYMMDD-NN for the given aircraft/date."""
    prefix = f"{aircraft_id}-{day_compact}-"
    rows = conn.execute(
        "SELECT flight_id FROM flight WHERE flight_id LIKE ?",
        (prefix + "%",),
    ).fetchall()
    seq = 1
    for row in rows:
        tail = str(_row_val(row, "flight_id"))[len(prefix) :]
        try:
            seq = max(seq, int(tail) + 1)
        except ValueError:
            continue
    return f"{prefix}{seq:02d}"


def _resolve_aircraft_id(conn: sqlite3.Connection, aircraft_id: str | None) -> str:
    if aircraft_id:
        try:
            row = conn.execute(
                "SELECT aircraft_id FROM aircraft WHERE aircraft_id=?",
                (aircraft_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return aircraft_id
        if row:
            return aircraft_id
        raise ValueError(f"unknown aircraft_id {aircraft_id}")
    try:
        row = conn.execute(
            "SELECT aircraft_id FROM aircraft ORDER BY aircraft_id LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return "COZ"
    if not row:
        raise ValueError("no aircraft in historian database — run historian init-db")
    return str(_row_val(row, "aircraft_id"))


def _existing_avplan_flight(conn: sqlite3.Connection, digest: str) -> str | None:
    try:
        row = conn.execute(
            """
            SELECT flight_id FROM flight_source
            WHERE file_hash=? AND source_type='AVPLAN_GPX'
            ORDER BY imported_at
            LIMIT 1
            """,
            (digest,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return str(_row_val(row, "flight_id"))


def _timed_points(parsed: GpxFlight) -> list[TrackPoint]:
    return [p for p in parsed.track_points if p.t_epoch is not None]


def _sample_periods(points: list[TrackPoint]) -> tuple[float | None, float | None, float | None]:
    dts = [
        points[i].t_epoch - points[i - 1].t_epoch  # type: ignore[operator]
        for i in range(1, len(points))
        if points[i].t_epoch is not None and points[i - 1].t_epoch is not None
    ]
    dts = [d for d in dts if d > 0]
    if not dts:
        return None, None, None
    return (sum(dts) / len(dts), min(dts), max(dts))


def create_flight_from_avplan_gpx(
    conn: sqlite3.Connection,
    gpx_path: Path,
    *,
    aircraft_id: str | None = None,
    copy_dir: Path | None = None,
    flight_id: str | None = None,
) -> dict[str, Any]:
    """Create a closed historian flight whose 10 Hz rows are the AvPlan track.

    Use this when there is no FIX live capture — historic iPad-only logs, or a
    future flight that only produced a GPX. Does not invent extra samples: one
    frame per timed track point. Lat/lon/alt/GS/track are stored on avplan_*
    and copied onto matching fix_* columns so Analysis can plot them.
    """
    parsed = parse_avplan_gpx_file(gpx_path)
    points = _timed_points(parsed)
    if not points:
        raise ValueError(f"{gpx_path.name} has no timed track points")

    digest = _file_sha256(gpx_path)
    already = _existing_avplan_flight(conn, digest)
    if already:
        raise ValueError(f"GPX already imported as {already}")

    aid = _resolve_aircraft_id(conn, aircraft_id)
    day = parsed.day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_compact = day.replace("-", "")[:8]
    if flight_id is None:
        flight_id = next_flight_id(conn, aid, day_compact)

    exists = conn.execute(
        "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
    ).fetchone()
    if exists:
        raise ValueError(f"flight_id {flight_id} already exists")

    ensure_avplan_columns(conn)
    t0 = points[0].t_epoch or 0.0
    t1 = points[-1].t_epoch or t0
    start_utc = points[0].time_utc or parsed.track_start_utc
    end_utc = points[-1].time_utc or parsed.track_end_utc
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mean_dt, min_dt, max_dt = _sample_periods(points)
    n = len(points)

    flight_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(flight)").fetchall()
    }
    flight_values: dict[str, Any] = {
        "flight_id": flight_id,
        "aircraft_id": aid,
        "flight_date": day,
        "origin": parsed.origin,
        "destination": parsed.destination,
        "flight_rules": parsed.rules,
        "wheels_off_utc": start_utc,
        "wheels_on_utc": end_utc,
        "historian_start_utc": start_utc,
        "historian_end_utc": end_utc,
        "pob": parsed.pob,
        "performance_profile": parsed.performance_profile,
        "purpose": parsed.route_name or None,
        "notes": "Created from AvPlan GPX only (no FIX live capture).",
        "created_at": now,
        "updated_at": now,
        "expected_10hz_frames": n,
        "actual_10hz_frames": n,
        "mean_sample_period_s": mean_dt,
        "minimum_sample_period_s": min_dt,
        "maximum_sample_period_s": max_dt,
        "timing_overruns": 0,
    }
    ins_cols = [c for c in flight_values if c in flight_cols]
    if "flight_id" not in ins_cols or "aircraft_id" not in ins_cols:
        raise ValueError("flight table is missing flight_id/aircraft_id")
    placeholders = ",".join("?" for _ in ins_cols)
    col_sql = ",".join(f'"{c}"' for c in ins_cols)
    conn.execute(
        f"INSERT INTO flight ({col_sql}) VALUES ({placeholders})",
        [flight_values[c] for c in ins_cols],
    )

    existing = {
        r[1] for r in conn.execute("PRAGMA table_info(historian_10hz)").fetchall()
    }
    cols = ["flight_id", "frame_number", "historian_time_utc", "flight_time_s"]
    avplan_cols = [c for c in AVPLAN_COLUMNS if c in existing]
    mirror_cols = [c for c, _attr in _FIX_FROM_TRACK if c in existing]
    cols.extend(avplan_cols)
    cols.extend(mirror_cols)
    placeholders = ",".join("?" for _ in cols)
    col_sql = ",".join(f'"{c}"' for c in cols)
    rows: list[tuple[Any, ...]] = []
    skipped = 0
    for i, pt in enumerate(points):
        if pt.time_utc is None or pt.t_epoch is None:
            skipped += 1
            continue
        values: list[Any] = [
            flight_id,
            i,
            pt.time_utc,
            round(pt.t_epoch - t0, 3),
        ]
        avplan_vals = {
            "avplan_lat": pt.lat,
            "avplan_lon": pt.lon,
            "avplan_alt": pt.alt_ft,
            "avplan_gs": pt.gs_kt,
            "avplan_track": pt.track_deg,
            "avplan_hdop": pt.hdop,
            "avplan_source_time": pt.time_utc,
            "avplan_sync_error_ms": 0.0,
        }
        values.extend(avplan_vals[c] for c in avplan_cols)
        attr = {name: getattr(pt, attr_name) for name, attr_name in _FIX_FROM_TRACK}
        values.extend(attr[c] for c in mirror_cols)
        rows.append(tuple(values))
    conn.executemany(
        f"INSERT INTO historian_10hz ({col_sql}) VALUES ({placeholders})",
        rows,
    )

    stored = str(gpx_path)
    if copy_dir is not None:
        dest_dir = copy_dir / flight_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "avplan.gpx"
        dest.write_bytes(gpx_path.read_bytes())
        stored = str(dest)

    nominal_hz = round(1.0 / mean_dt, 3) if mean_dt else None
    conn.execute(
        """
        INSERT INTO flight_source(
            source_id, flight_id, source_type, source_name, filename, file_hash,
            original_start_time, original_end_time, nominal_rate_hz, imported_at,
            decoder_name, decoder_version, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"{flight_id}_AVPLAN_GPX",
            flight_id,
            "AVPLAN_GPX",
            parsed.route_name,
            gpx_path.name,
            digest,
            start_utc,
            end_utc,
            nominal_hz,
            now,
            "avplan_gpx",
            "1",
            f"standalone frames={len(rows)} skipped={skipped}",
        ),
    )
    try:
        conn.execute(
            """
            INSERT INTO event(
                flight_id, historian_time_utc, flight_time_s,
                event_type, source, text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                flight_id,
                start_utc,
                0.0,
                "FLIGHT_IMPORT",
                "AVPLAN_GPX",
                f"Created from {gpx_path.name}",
            ),
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()
    duration_s = round(t1 - t0, 3)
    return {
        "ok": True,
        "created": True,
        "flight_id": flight_id,
        "gpx": gpx_path.name,
        "route_name": parsed.route_name,
        "origin": parsed.origin,
        "destination": parsed.destination,
        "track_points": len(parsed.track_points),
        "frames_created": len(rows),
        "duration_s": duration_s,
        "mean_sample_period_s": round(mean_dt, 3) if mean_dt else None,
        "nominal_rate_hz": nominal_hz,
        "file_hash": digest,
        "stored_copy": stored,
        "historian_start_utc": start_utc,
        "historian_end_utc": end_utc,
    }
