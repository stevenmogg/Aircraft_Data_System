"""MGL Airtalk → FIX adapter via Nano 33 BLE USB dump.

The Nano is a receive-only tap (no TX onto Airtalk). This plugin is the sole
owner of that USB CDC port. It parses Nano `hex=` lines, decodes FF/32 heading
and FF/37 Euler10 attitude, and writes source-specific MGL_AT_* keys.
Canonical PITCH/ROLL/HEAD remain Stratux-owned.
"""

from __future__ import annotations

import glob
import os
import threading
import time
from collections import OrderedDict

import serial
import fixgw.plugin as plugin

from web.app.services.airtalk_frames import (
    FrameAssembler,
    decode_fix_values,
    parse_monitor_hex_line,
)

DEFAULT_PORT_GLOBS = (
    "/dev/serial/by-id/usb-Arduino_Nano_33_BLE*",
)

_GPS_HINTS = ("u-blox", "ublox", "gps", "gnss")


def _looks_like_gps(path: str) -> bool:
    name = os.path.basename(path).lower()
    if any(h in name for h in _GPS_HINTS):
        return True
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    for p in glob.glob("/dev/serial/by-id/*"):
        try:
            if os.path.realpath(p) == real and any(
                h in os.path.basename(p).lower() for h in _GPS_HINTS
            ):
                return True
        except OSError:
            continue
    return False


def _find_port(configured: str) -> str | None:
    """Return only the Nano Airtalk tap. Never fall back to ttyACM GPS dongles."""
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    for pattern in DEFAULT_PORT_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        if _looks_like_gps(path):
            continue
        return path
    return None


class MainThread(threading.Thread):
    def __init__(self, parent: "Plugin"):
        super().__init__(daemon=True)
        self.parent = parent
        self.log = parent.log
        self.getout = False
        self.port = str(parent.config.get("port", "")).strip()
        self.baud = int(parent.config.get("baud", 115200))
        self.receive_only = bool(parent.config.get("receive_only", True))
        self._fail_logged = False

    def run(self):
        self.log.info(
            "MGL Airtalk adapter USB %s @ %d (receive_only=%s)",
            self.port or "(auto)",
            self.baud,
            self.receive_only,
        )
        backoff = 1.0
        while not self.getout:
            port = _find_port(self.port)
            self.parent.status["port"] = port
            if not port:
                if not self._fail_logged:
                    self.log.warning("MGL Airtalk USB device not found")
                    self._fail_logged = True
                self.parent.status["link"] = "DOWN"
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            ser = None
            assembler = FrameAssembler()
            line_buf = ""
            try:
                ser = serial.Serial(
                    port,
                    self.baud,
                    timeout=0.2,
                    dsrdtr=False,
                    rtscts=False,
                )
                self._fail_logged = False
                backoff = 1.0
                self.parent.status["link"] = "UP"
                self.log.info("MGL Airtalk listening on %s", port)
                while not self.getout:
                    want = _find_port(self.port)
                    if want and os.path.realpath(want) != os.path.realpath(port):
                        self.log.info(
                            "MGL Airtalk switching %s -> %s", port, want
                        )
                        break
                    raw = ser.read(512)
                    now = time.time()
                    if not raw:
                        continue
                    self.parent.status["rx_bytes"] = (
                        int(self.parent.status.get("rx_bytes", 0)) + len(raw)
                    )
                    line_buf += raw.decode("ascii", errors="replace")
                    while "\n" in line_buf:
                        line, line_buf = line_buf.split("\n", 1)
                        line = line.strip("\r")
                        if not line or line.startswith("#"):
                            continue
                        chunk = parse_monitor_hex_line(line)
                        if not chunk:
                            continue
                        for frame in assembler.feed(chunk):
                            self._accept(frame, now)
            except Exception as e:
                if not self._fail_logged:
                    self.log.warning("MGL Airtalk serial error: %s", e)
                    self._fail_logged = True
                self.parent.status["link"] = "ERROR"
                self.parent.status["error"] = str(e)
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass

    def _accept(self, frame, now: float) -> None:
        st = self.parent.status
        st["rx_frames"] = int(st.get("rx_frames", 0)) + 1
        st["last_frame_ts"] = now
        if not frame.ok:
            st["bad_frames"] = int(st.get("bad_frames", 0)) + 1
            return
        st["ok_frames"] = int(st.get("ok_frames", 0)) + 1
        values = decode_fix_values(frame.dest, frame.msg_type, frame.data)
        write = self.parent.db_write
        for key, value in values.items():
            try:
                write(key, value)
            except Exception as e:
                self.log.debug("db_write %s failed: %s", key, e)
        if "MGL_AT_PITCH" in values:
            st["last_att_ts"] = now
        if "MGL_AT_HEAD" in values:
            st["last_hdg_ts"] = now

    def stop(self):
        self.getout = True


class Plugin(plugin.PluginBase):
    def __init__(self, name, config, config_meta):
        super().__init__(name, config, config_meta)
        self.thread = MainThread(self)
        self.status = OrderedDict(
            {
                "port": None,
                "link": "INIT",
                "rx_bytes": 0,
                "rx_frames": 0,
                "ok_frames": 0,
                "bad_frames": 0,
            }
        )

    def run(self):
        self.thread.start()

    def stop(self):
        self.thread.stop()
        if self.thread.is_alive():
            self.thread.join(2.0)
        if self.thread.is_alive():
            raise plugin.PluginFail

    def get_status(self):
        return self.status
