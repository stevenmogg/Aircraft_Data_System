"""Historian daemon: idle until start-flight; Start/Stop over a Unix socket."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Any

from historian.capture.sampler import (
    Sampler,
    clear_active_flight,
    write_active_flight,
)
from historian.control import DEFAULT_SOCKET, socket_path_from_cfg
from historian.database.repository import HistorianDB, load_yaml

log = logging.getLogger("historian.daemon")


class HistorianDaemon:
    def __init__(
        self,
        historian_yaml: Path,
        aircraft_yaml: Path,
        sock_path: Path | None = None,
    ):
        self.historian_yaml = historian_yaml
        self.aircraft_yaml = aircraft_yaml
        hcfg = load_yaml(historian_yaml)
        self.hist = hcfg.get("historian") or {}
        self.acfg = load_yaml(aircraft_yaml)
        self.db = HistorianDB.from_config_files(historian_yaml, aircraft_yaml)
        self.sock_path = sock_path or socket_path_from_cfg(self.hist)
        self._stop_daemon = threading.Event()
        self._lock = threading.RLock()
        self._state = "idle"  # idle | recording
        self._flight_id: str | None = None
        self._sampler: Sampler | None = None
        self._capture_thread: threading.Thread | None = None
        self._last_summary: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._server: socket.socket | None = None

    def run(self) -> None:
        self.db.init_schema_and_seed()
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.sock_path.exists():
            self.sock_path.unlink()

        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.sock_path))
        os.chmod(self.sock_path, 0o660)
        self._server.listen(5)
        self._server.settimeout(1.0)
        log.info(
            "historian daemon idle (waiting for start) socket=%s",
            self.sock_path,
        )

        try:
            while not self._stop_daemon.is_set():
                try:
                    conn, _ = self._server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_daemon.is_set():
                        break
                    raise
                threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                ).start()
        finally:
            self._shutdown()

    def _on_signal(self, signum, frame) -> None:
        log.info("signal %s — shutting down daemon", signum)
        self._stop_daemon.set()

    def _shutdown(self) -> None:
        with self._lock:
            if self._state == "recording":
                self._stop_capture_locked()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self.sock_path.exists():
            try:
                self.sock_path.unlink()
            except OSError:
                pass
        log.info("historian daemon stopped")

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5.0)
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            if not buf:
                return
            try:
                req = json.loads(buf.decode("utf-8").strip())
            except json.JSONDecodeError:
                self._send(conn, {"ok": False, "error": "invalid json"})
                return
            if not isinstance(req, dict) or "cmd" not in req:
                self._send(conn, {"ok": False, "error": "missing cmd"})
                return
            resp = self._dispatch(req)
            self._send(conn, resp)
        except Exception as e:
            log.exception("client handler error")
            try:
                self._send(conn, {"ok": False, "error": str(e)})
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _send(conn: socket.socket, obj: dict[str, Any]) -> None:
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def _dispatch(self, req: dict[str, Any]) -> dict[str, Any]:
        cmd = str(req["cmd"]).lower()
        if cmd in ("ping", "status"):
            return self._status()
        if cmd == "start":
            return self._start(
                duration_s=req.get("duration_s"),
                flight_id=req.get("flight_id"),
            )
        if cmd == "stop":
            return self._stop()
        if cmd == "mark":
            return self._mark(text=req.get("text") or req.get("label"))
        return {"ok": False, "error": f"unknown cmd {cmd}"}

    def _status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "state": self._state,
                "flight_id": self._flight_id,
                "daemon_pid": os.getpid(),
                "last_summary": self._last_summary,
                "last_error": self._last_error,
                "socket": str(self.sock_path),
            }

    def _start(
        self, duration_s: float | None = None, flight_id: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if self._state == "recording":
                return {
                    "ok": False,
                    "error": "already recording",
                    "state": self._state,
                    "flight_id": self._flight_id,
                }
            try:
                self._last_error = None
                if flight_id is None:
                    flight_id = self.db.start_flight(
                        aircraft_id=self.hist.get("aircraft_id") or "COZ",
                        configuration_id=(
                            (self.acfg.get("configuration") or {}).get(
                                "configuration_id"
                            )
                        ),
                    )
                else:
                    self.db.ensure_flight_started(flight_id)

                stop_event = threading.Event()
                sampler = Sampler(self.db, self.hist, flight_id, stop_event=stop_event)
                max_frames = None
                if duration_s is not None:
                    rate = float(self.hist.get("fast_rate_hz") or 10)
                    max_frames = int(round(float(duration_s) * rate))

                self._flight_id = flight_id
                self._sampler = sampler
                self._state = "recording"
                write_active_flight(self.db.path.parent, flight_id, os.getpid())

                def _run():
                    stats = None
                    err = None
                    try:
                        log.info(
                            "capture start flight=%s max_frames=%s",
                            flight_id,
                            max_frames,
                        )
                        stats = sampler.run(max_frames=max_frames)
                    except Exception as e:
                        err = str(e)
                        log.exception("capture failed")
                    finally:
                        with self._lock:
                            clear_active_flight(self.db.path.parent)
                            try:
                                self.db.finish_flight(flight_id, stats)
                            except Exception:
                                log.exception("finish_flight failed")
                            self._last_summary = stats
                            self._last_error = err
                            self._state = "idle"
                            self._sampler = None
                            self._capture_thread = None
                            # keep flight_id as last completed id for status
                            log.info(
                                "capture end flight=%s stats=%s err=%s",
                                flight_id,
                                stats,
                                err,
                            )

                t = threading.Thread(target=_run, name="historian-capture", daemon=True)
                self._capture_thread = t
                t.start()
                return {
                    "ok": True,
                    "state": "recording",
                    "flight_id": flight_id,
                }
            except Exception as e:
                self._state = "idle"
                self._flight_id = None
                self._sampler = None
                self._last_error = str(e)
                log.exception("start failed")
                return {"ok": False, "error": str(e), "state": "idle"}

    def _stop(self) -> dict[str, Any]:
        with self._lock:
            if self._state != "recording" or self._sampler is None:
                return {
                    "ok": True,
                    "state": "idle",
                    "flight_id": self._flight_id,
                    "message": "not recording",
                }
            flight_id = self._flight_id
            thread = self._capture_thread
            self._stop_capture_locked()
        if thread is not None:
            thread.join(timeout=15.0)
        # brief wait for finish_flight in capture thread
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with self._lock:
                if self._state == "idle":
                    break
            time.sleep(0.05)
        with self._lock:
            return {
                "ok": True,
                "state": self._state,
                "flight_id": flight_id,
                "last_summary": self._last_summary,
                "last_error": self._last_error,
            }

    def _stop_capture_locked(self) -> None:
        if self._sampler is not None:
            self._sampler.request_stop()

    def _mark(self, text: str | None = None) -> dict[str, Any]:
        from historian.capture.timing import utc_iso

        with self._lock:
            if self._state != "recording" or not self._flight_id:
                return {
                    "ok": False,
                    "error": "not recording — MARK requires an active flight",
                    "state": self._state,
                }
            flight_id = self._flight_id
        # Approximate flight_time from DB last frame if available
        flight_time_s = None
        try:
            with self.db.connect() as conn:
                row = conn.execute(
                    "SELECT MAX(flight_time_s) AS t FROM historian_10hz WHERE flight_id=?",
                    (flight_id,),
                ).fetchone()
                if row and row["t"] is not None:
                    flight_time_s = float(row["t"])
                now = utc_iso()
                self.db.insert_event(
                    conn,
                    flight_id,
                    now,
                    flight_time_s,
                    "PILOT_MARK",
                    source="WEB",
                    parameter=None,
                    value=None,
                    text=text or "MARK",
                )
                conn.commit()
        except Exception as e:
            return {"ok": False, "error": str(e), "state": "recording", "flight_id": flight_id}
        return {
            "ok": True,
            "event_type": "PILOT_MARK",
            "flight_id": flight_id,
            "text": text or "MARK",
            "flight_time_s": flight_time_s,
        }


def run_daemon(historian_yaml: Path, aircraft_yaml: Path) -> None:
    HistorianDaemon(historian_yaml, aircraft_yaml).run()
