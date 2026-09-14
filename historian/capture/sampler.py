"""10 Hz / 1 Hz FIX sampler on a single monotonic timebase."""

from __future__ import annotations

import json
import logging
import signal
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from historian.capture.events import QualityTracker
from historian.capture.fix_client import FixClient
from historian.capture.timing import FlightClock, utc_iso
from historian.database.repository import HistorianDB, load_yaml

log = logging.getLogger("historian.sampler")

ACTIVE_FLIGHT_NAME = "active_flight.json"


class Sampler:
    def __init__(
        self,
        db: HistorianDB,
        historian_cfg: dict[str, Any],
        flight_id: str,
        stop_event: threading.Event | None = None,
    ):
        self.db = db
        self.cfg = historian_cfg
        self.flight_id = flight_id
        self.stop_event = stop_event or threading.Event()
        self.fast_map: dict[str, str] = dict(historian_cfg.get("fast_signals") or {})
        self.slow_map: dict[str, str] = dict(historian_cfg.get("slow_signals") or {})
        self.rate = float(historian_cfg.get("fast_rate_hz") or 10)
        self.tolerance = float(historian_cfg.get("sample_tolerance_s") or 0.05)
        self.commit_every = int(historian_cfg.get("commit_every_frames") or 10)
        fix = historian_cfg.get("fix") or {}
        self.fix = FixClient(
            host=fix.get("host", "127.0.0.1"),
            port=int(fix.get("port", 3490)),
        )
        self.clock = FlightClock(self.rate)
        self.quality = QualityTracker()
        self._on_frame: Callable[[int], None] | None = None

    def request_stop(self) -> None:
        self.stop_event.set()

    def run(self, max_frames: int | None = None) -> dict:
        keys = sorted(set(self.fast_map) | set(self.slow_map))
        log.info("connecting FIX for %d keys", len(keys))
        self.fix.connect(keys)
        self.clock.start()

        conn = self.db.connect()
        try:
            pending = 0
            while not self.stop_event.is_set():
                if max_frames is not None and self.clock.frame_number >= max_frames:
                    break
                frame, flight_time_s, hist_utc, overrun = self.clock.wait_next(
                    self.tolerance
                )
                samples = self.fix.read_many(keys)
                self._write_frame(conn, frame, flight_time_s, hist_utc, samples, overrun)
                pending += 1
                if pending >= self.commit_every:
                    conn.commit()
                    pending = 0
                if self._on_frame:
                    self._on_frame(frame)
            conn.commit()
        finally:
            try:
                self.fix.disconnect()
            except Exception:
                pass
            conn.close()

        return self.clock.stats.summary()

    def _write_frame(
        self,
        conn: sqlite3.Connection,
        frame: int,
        flight_time_s: float,
        hist_utc: str,
        samples: dict,
        overrun: bool,
    ) -> None:
        fast_cols = {}
        for fix_key, col in self.fast_map.items():
            s = samples.get(fix_key)
            val = None if s is None else s.value
            flags = "" if s is None else s.flags
            # Do not store values marked fail/bad as numbers — use NULL
            if s is not None and ("f" in flags or "b" in flags):
                val = None
            fast_cols[col] = val
            for ev in self.quality.update(fix_key, flags, None if s is None else s.value):
                self.db.insert_event(
                    conn,
                    self.flight_id,
                    hist_utc,
                    flight_time_s,
                    ev.event_type,
                    source="FIX_LIVE",
                    parameter=ev.parameter,
                    value=ev.value,
                    text=ev.text,
                )

        self.db.insert_10hz(
            conn,
            self.flight_id,
            frame,
            hist_utc,
            flight_time_s,
            fast_cols,
        )

        if frame % int(self.rate) == 0:
            slow_frame = frame // int(self.rate)
            slow_cols = {}
            for fix_key, col in self.slow_map.items():
                s = samples.get(fix_key)
                val = None if s is None else s.value
                flags = "" if s is None else s.flags
                if s is not None and ("f" in flags or "b" in flags):
                    val = None
                slow_cols[col] = val
            self.db.insert_1hz(
                conn,
                self.flight_id,
                slow_frame,
                hist_utc,
                float(slow_frame),
                slow_cols,
            )

        if overrun:
            self.db.insert_event(
                conn,
                self.flight_id,
                hist_utc,
                flight_time_s,
                "TIMING_OVERRUN",
                source="HISTORIAN",
                parameter=None,
                value=None,
                text=f"frame {frame} late > {self.tolerance}s",
            )


def active_flight_path(data_dir: Path) -> Path:
    return data_dir / ACTIVE_FLIGHT_NAME


def write_active_flight(data_dir: Path, flight_id: str, pid: int) -> None:
    path = active_flight_path(data_dir)
    path.write_text(
        json.dumps({"flight_id": flight_id, "pid": pid, "started_at": utc_iso()}) + "\n"
    )


def read_active_flight(data_dir: Path) -> dict | None:
    path = active_flight_path(data_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def clear_active_flight(data_dir: Path) -> None:
    path = active_flight_path(data_dir)
    if path.exists():
        path.unlink()


def run_flight_capture(
    historian_yaml: Path,
    aircraft_yaml: Path,
    duration_s: float | None = None,
    flight_id: str | None = None,
) -> str:
    """Create a flight (if needed) and run the sampler until duration or signal."""
    hcfg_full = load_yaml(historian_yaml)
    hist = hcfg_full.get("historian") or {}
    db = HistorianDB.from_config_files(historian_yaml, aircraft_yaml)
    db.init_schema_and_seed()

    data_dir = db.path.parent
    existing = read_active_flight(data_dir)
    if existing and existing.get("pid"):
        # stale pid check
        try:
            import os

            os.kill(int(existing["pid"]), 0)
            raise RuntimeError(
                f"capture already running for {existing.get('flight_id')} "
                f"(pid {existing['pid']}); use stop-flight first"
            )
        except ProcessLookupError:
            clear_active_flight(data_dir)
        except PermissionError:
            raise RuntimeError(
                f"capture already running for {existing.get('flight_id')} "
                f"(pid {existing['pid']})"
            )

    if flight_id is None:
        flight_id = db.start_flight(
            aircraft_id=hist.get("aircraft_id") or "COZ",
            configuration_id=(
                (load_yaml(aircraft_yaml).get("configuration") or {}).get(
                    "configuration_id"
                )
            ),
        )
    else:
        # ensure flight exists
        db.ensure_flight_started(flight_id)

    stop_event = threading.Event()

    def _handle_sig(signum, frame):
        log.info("signal %s — stopping capture", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    write_active_flight(data_dir, flight_id, os_getpid())
    max_frames = None
    if duration_s is not None:
        max_frames = int(round(float(duration_s) * float(hist.get("fast_rate_hz") or 10)))

    sampler = Sampler(db, hist, flight_id, stop_event=stop_event)
    log.info("flight %s capture start (max_frames=%s)", flight_id, max_frames)
    try:
        stats = sampler.run(max_frames=max_frames)
    finally:
        clear_active_flight(data_dir)
        db.finish_flight(flight_id, stats)
        log.info("flight %s capture end: %s", flight_id, stats)
    return flight_id


def os_getpid() -> int:
    import os

    return os.getpid()
