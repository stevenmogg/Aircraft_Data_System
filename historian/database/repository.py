"""SQLite access helpers for the Historian."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from historian.database.fix_catalog import load_signals_from_historian_cfg
from historian.database.migrations import get_schema_version, migrate, set_schema_version
from historian.database.schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
    ensure_signal_columns,
    quote_ident,
    table_columns,
)

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("PyYAML is required (pip install pyyaml)") from e


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")
    return data


class HistorianDB:
    def __init__(
        self,
        path: Path,
        aircraft_cfg: dict[str, Any] | None = None,
        signals: dict[str, dict[str, Any]] | None = None,
    ):
        self.path = Path(path)
        self.aircraft_cfg = aircraft_cfg or {}
        self.signals = signals or {}

    @classmethod
    def from_config_files(
        cls,
        historian_yaml: Path,
        aircraft_yaml: Path,
        db_path: Path | None = None,
    ) -> "HistorianDB":
        hcfg = load_yaml(historian_yaml)
        acfg = load_yaml(aircraft_yaml)
        hist = hcfg.get("historian") or {}
        path = Path(db_path) if db_path else Path(hist["database_path"])
        return cls(
            path,
            aircraft_cfg=acfg,
            signals=load_signals_from_historian_cfg(hist),
        )

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def init_schema_and_seed(self) -> dict[str, bool]:
        """Create schema if needed and seed aircraft/configuration. Idempotent."""
        created = {
            "schema": False,
            "aircraft": False,
            "configuration": False,
        }
        with self.connect() as conn:
            existing = get_schema_version(conn)
            if existing is None:
                conn.executescript(SCHEMA_SQL)
                set_schema_version(conn, SCHEMA_VERSION)
                created["schema"] = True
            else:
                migrate(conn)
            ensure_signal_columns(conn, self.signals)
            created["aircraft"] = self._seed_aircraft(conn)
            created["configuration"] = self._seed_configuration(conn)
            conn.commit()
        return created

    def _seed_aircraft(self, conn: sqlite3.Connection) -> bool:
        ac = self.aircraft_cfg.get("aircraft") or {}
        aircraft_id = ac.get("aircraft_id")
        if not aircraft_id:
            return False
        row = conn.execute(
            "SELECT 1 FROM aircraft WHERE aircraft_id=?", (aircraft_id,)
        ).fetchone()
        if row:
            return False
        conn.execute(
            """
            INSERT INTO aircraft(aircraft_id, registration, type, description, created_at, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                aircraft_id,
                ac.get("registration"),
                ac.get("type"),
                ac.get("description"),
                utc_now_iso(),
                ac.get("notes") or "",
            ),
        )
        return True

    def _seed_configuration(self, conn: sqlite3.Connection) -> bool:
        cfg = self.aircraft_cfg.get("configuration") or {}
        configuration_id = cfg.get("configuration_id")
        aircraft_id = (self.aircraft_cfg.get("aircraft") or {}).get("aircraft_id")
        if not configuration_id or not aircraft_id:
            return False
        row = conn.execute(
            "SELECT 1 FROM aircraft_configuration WHERE configuration_id=?",
            (configuration_id,),
        ).fetchone()
        if row:
            return False
        conn.execute(
            """
            INSERT INTO aircraft_configuration(
                configuration_id, aircraft_id, valid_from, valid_to,
                name, description, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                configuration_id,
                aircraft_id,
                cfg.get("valid_from"),
                cfg.get("valid_to"),
                cfg.get("name"),
                cfg.get("description"),
                cfg.get("notes") or "",
                utc_now_iso(),
            ),
        )
        for item in cfg.get("items") or []:
            conn.execute(
                """
                INSERT INTO configuration_item(
                    configuration_id, category, item, value, units, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    configuration_id,
                    item.get("category"),
                    item.get("item"),
                    item.get("value"),
                    item.get("units") or "",
                    item.get("notes") or "",
                ),
            )
        return True

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "database": str(self.path),
            "exists": self.path.exists(),
            "schema_version": None,
        }
        if not self.path.exists():
            return info
        with self.connect() as conn:
            info["schema_version"] = get_schema_version(conn)
            for table in (
                "aircraft",
                "aircraft_configuration",
                "configuration_item",
                "flight",
                "flight_source",
                "historian_10hz",
                "historian_1hz",
                "event",
                "signal",
            ):
                try:
                    n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                    info[f"rows_{table}"] = n
                except sqlite3.Error:
                    info[f"rows_{table}"] = "missing"
            open_flight = conn.execute(
                "SELECT flight_id FROM flight WHERE historian_end_utc IS NULL "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            info["open_flight_id"] = open_flight["flight_id"] if open_flight else None
            try:
                import os

                info["data_dir_dev"] = os.stat(self.path.parent).st_dev
            except OSError:
                pass
        return info

    def next_flight_id(self, aircraft_id: str, flight_date: str | None = None) -> str:
        """Allocate COZ-YYYYMMDD-NN for the given aircraft/date (UTC)."""
        if flight_date is None:
            flight_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        prefix = f"{aircraft_id}-{flight_date}-"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT flight_id FROM flight WHERE flight_id LIKE ?",
                (prefix + "%",),
            ).fetchall()
        seq = 1
        for row in rows:
            tail = str(row["flight_id"])[len(prefix) :]
            try:
                seq = max(seq, int(tail) + 1)
            except ValueError:
                continue
        return f"{prefix}{seq:02d}"

    def start_flight(
        self,
        aircraft_id: str,
        configuration_id: str | None = None,
        flight_id: str | None = None,
    ) -> str:
        now = utc_now_iso()
        flight_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if flight_id is None:
            flight_id = self.next_flight_id(
                aircraft_id, datetime.now(timezone.utc).strftime("%Y%m%d")
            )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO flight(
                    flight_id, aircraft_id, configuration_id, flight_date,
                    historian_start_utc, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    flight_id,
                    aircraft_id,
                    configuration_id,
                    flight_date,
                    now,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO flight_source(
                    source_id, flight_id, source_type, source_name,
                    nominal_rate_hz, imported_at, decoder_name, decoder_version, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{flight_id}-FIX_LIVE",
                    flight_id,
                    "FIX_LIVE",
                    "FIX-Gateway live sample",
                    10.0,
                    now,
                    "historian.capture",
                    "0.1.0",
                    "",
                ),
            )
            conn.execute(
                """
                INSERT INTO event(
                    flight_id, historian_time_utc, flight_time_s,
                    event_type, source, text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (flight_id, now, 0.0, "FLIGHT_START", "HISTORIAN", "capture started"),
            )
            conn.commit()
        return flight_id

    def ensure_flight_started(self, flight_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"unknown flight_id {flight_id}")

    def finish_flight(self, flight_id: str, timing_stats: dict[str, Any] | None = None) -> None:
        now = utc_now_iso()
        stats = timing_stats or {}
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE flight SET
                    historian_end_utc = ?,
                    updated_at = ?,
                    expected_10hz_frames = ?,
                    actual_10hz_frames = ?,
                    mean_sample_period_s = ?,
                    minimum_sample_period_s = ?,
                    maximum_sample_period_s = ?,
                    timing_overruns = ?
                WHERE flight_id = ?
                """,
                (
                    now,
                    now,
                    stats.get("expected_10hz_frames"),
                    stats.get("actual_10hz_frames"),
                    stats.get("mean_sample_period_s"),
                    stats.get("minimum_sample_period_s"),
                    stats.get("maximum_sample_period_s"),
                    stats.get("timing_overruns"),
                    flight_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO event(
                    flight_id, historian_time_utc, flight_time_s,
                    event_type, source, text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (flight_id, now, None, "FLIGHT_STOP", "HISTORIAN", "capture stopped"),
            )
            conn.commit()

    def insert_10hz(
        self,
        conn: sqlite3.Connection,
        flight_id: str,
        frame_number: int,
        historian_time_utc: str,
        flight_time_s: float,
        columns: dict[str, Any],
    ) -> None:
        cols = ["flight_id", "frame_number", "historian_time_utc", "flight_time_s"]
        vals: list[Any] = [flight_id, frame_number, historian_time_utc, flight_time_s]
        existing = table_columns(conn, "historian_10hz")
        for name, value in columns.items():
            if name in existing:
                cols.append(name)
                vals.append(value)
        placeholders = ",".join("?" for _ in cols)
        col_sql = ",".join(quote_ident(c) for c in cols)
        conn.execute(
            f"INSERT INTO historian_10hz ({col_sql}) VALUES ({placeholders})",
            vals,
        )

    def insert_1hz(
        self,
        conn: sqlite3.Connection,
        flight_id: str,
        frame_number: int,
        historian_time_utc: str,
        flight_time_s: float,
        columns: dict[str, Any],
    ) -> None:
        cols = ["flight_id", "frame_number", "historian_time_utc", "flight_time_s"]
        vals: list[Any] = [flight_id, frame_number, historian_time_utc, flight_time_s]
        existing = table_columns(conn, "historian_1hz")
        for name, value in columns.items():
            if name in existing:
                cols.append(name)
                vals.append(value)
        placeholders = ",".join("?" for _ in cols)
        col_sql = ",".join(quote_ident(c) for c in cols)
        conn.execute(
            f"INSERT INTO historian_1hz ({col_sql}) VALUES ({placeholders})",
            vals,
        )

    def insert_event(
        self,
        conn: sqlite3.Connection,
        flight_id: str,
        historian_time_utc: str,
        flight_time_s: float | None,
        event_type: str,
        source: str | None = None,
        parameter: str | None = None,
        value: str | None = None,
        text: str | None = None,
        metadata_json: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO event(
                flight_id, historian_time_utc, flight_time_s,
                event_type, source, parameter, value, text, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                flight_id,
                historian_time_utc,
                flight_time_s,
                event_type,
                source,
                parameter,
                value,
                text,
                metadata_json,
            ),
        )

    def flight_summary(self, flight_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            flight = conn.execute(
                "SELECT * FROM flight WHERE flight_id=?", (flight_id,)
            ).fetchone()
            if not flight:
                raise ValueError(f"unknown flight_id {flight_id}")
            n10 = conn.execute(
                "SELECT COUNT(*) AS n FROM historian_10hz WHERE flight_id=?",
                (flight_id,),
            ).fetchone()["n"]
            n1 = conn.execute(
                "SELECT COUNT(*) AS n FROM historian_1hz WHERE flight_id=?",
                (flight_id,),
            ).fetchone()["n"]
            ne = conn.execute(
                "SELECT COUNT(*) AS n FROM event WHERE flight_id=?",
                (flight_id,),
            ).fetchone()["n"]
            sample = conn.execute(
                """
                SELECT fix_pitch, fix_roll, fix_alt, flight_time_s
                FROM historian_10hz
                WHERE flight_id=? AND fix_pitch IS NOT NULL
                ORDER BY frame_number DESC LIMIT 1
                """,
                (flight_id,),
            ).fetchone()
            out = dict(flight)
            out["rows_10hz"] = n10
            out["rows_1hz"] = n1
            out["rows_event"] = ne
            if sample:
                out["last_fix_pitch"] = sample["fix_pitch"]
                out["last_fix_roll"] = sample["fix_roll"]
                out["last_fix_alt"] = sample["fix_alt"]
                out["last_flight_time_s"] = sample["flight_time_s"]
            return out
