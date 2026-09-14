"""MGL Extreme NMEA traffic monitor — reads FIX, does not open serial0."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from web.app.services.mgl_nmea import display_fields, parse_line

log = logging.getLogger("cozy.web.nmea_monitor")

RECENT_MAX = 40
POLL_S = 0.1
FIX_KEYS = ("MGL_NMEA_GGA_RAW", "MGL_NMEA_RMC_RAW")


def _rate_hz(count: int, first_ts: float | None, last_ts: float | None) -> float:
    if count < 2 or first_ts is None or last_ts is None:
        return 0.0
    elapsed = max(last_ts - first_ts, 1e-6)
    return round((count - 1) / elapsed, 2)


class SentenceTrack:
    def __init__(self, name: str):
        self.name = name
        self.last_raw = ""
        self.count = 0
        self.first_ts: float | None = None
        self.last_ts: float | None = None
        self.parsed: dict[str, Any] = {}
        self.recent: deque[dict[str, Any]] = deque(maxlen=RECENT_MAX)

    def accept(self, raw: str, now: float) -> bool:
        text = (raw or "").strip()
        if not text or text == self.last_raw:
            return False
        self.last_raw = text
        self.parsed = parse_line(text)
        self.count += 1
        if self.first_ts is None:
            self.first_ts = now
        self.last_ts = now
        self.recent.appendleft(
            {
                "raw": text,
                "ts": now,
                "csum_ok": bool(self.parsed.get("MGL_NMEA_CSUM_OK")),
            }
        )
        return True

    def as_dict(self, now: float) -> dict[str, Any]:
        parsed = self.parsed
        age_ms = None if self.last_ts is None else int((now - self.last_ts) * 1000)
        return {
            "type": self.name,
            "talker": parsed.get("MGL_NMEA_TALKER") or "",
            "raw": self.last_raw or "",
            "csum_ok": parsed.get("MGL_NMEA_CSUM_OK"),
            "count": self.count,
            "rate_hz": _rate_hz(self.count, self.first_ts, self.last_ts),
            "age_ms": age_ms,
            "fields": display_fields(parsed, self.name) if parsed else [],
            "recent": list(self.recent),
        }


class NmeaMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.gga = SentenceTrack("GGA")
        self.rmc = SentenceTrack("RMC")
        self.fix_ok = False
        self.fix_error: str | None = None
        self.rx_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="nmea-monitor", daemon=True
        )
        self._thread.start()

    def apply_raws(self, gga_raw: str, rmc_raw: str, now: float | None = None) -> None:
        """Update tracks from latest FIX strings (also used by tests)."""
        stamp = time.time() if now is None else now
        with self._lock:
            if self.gga.accept(gga_raw, stamp):
                self.rx_count += 1
            if self.rmc.accept(rmc_raw, stamp):
                self.rx_count += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            return {
                "type": "mgl_nmea_update",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "nmea": {
                    "source": "FIX MGL_NMEA_*",
                    "status": "UP" if self.fix_ok else "DOWN",
                    "error": self.fix_error,
                    "rx_count": self.rx_count,
                    "running": bool(self._thread and self._thread.is_alive()),
                },
                "gga": self.gga.as_dict(now),
                "rmc": self.rmc.as_dict(now),
            }

    def _run(self) -> None:
        client = None
        backoff = 1.0
        while not self._stop.is_set():
            try:
                from historian.capture.fix_client import FixClient

                client = FixClient(host="127.0.0.1", port=3490, timeout=2.0)
                client.connect(FIX_KEYS)
                with self._lock:
                    self.fix_ok = True
                    self.fix_error = None
                backoff = 1.0
                log.info("nmea monitor connected to FIX")
                while not self._stop.is_set():
                    samples = client.read_many(FIX_KEYS)
                    gga = (samples.get("MGL_NMEA_GGA_RAW") or None)
                    rmc = (samples.get("MGL_NMEA_RMC_RAW") or None)
                    gga_raw = "" if gga is None else (gga.raw or "")
                    rmc_raw = "" if rmc is None else (rmc.raw or "")
                    gga_raw = gga_raw.strip().strip('"').strip("'")
                    rmc_raw = rmc_raw.strip().strip('"').strip("'")
                    if gga_raw in ("None", "-"):
                        gga_raw = ""
                    if rmc_raw in ("None", "-"):
                        rmc_raw = ""
                    self.apply_raws(gga_raw, rmc_raw)
                    self._stop.wait(POLL_S)
            except Exception as e:
                with self._lock:
                    self.fix_ok = False
                    self.fix_error = str(e)
                log.debug("nmea monitor FIX error: %s", e)
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 10.0)
            finally:
                if client is not None:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    client = None


_monitor: NmeaMonitor | None = None
_monitor_lock = threading.Lock()


def get_monitor() -> NmeaMonitor:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = NmeaMonitor()
        return _monitor
