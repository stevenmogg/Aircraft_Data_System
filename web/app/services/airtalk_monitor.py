"""Background USB reader for the Nano 33 BLE Airtalk monitor."""

from __future__ import annotations

import glob
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from web.app.services.airtalk_frames import (
    FrameAssembler,
    decode_fields,
    dest_label,
    parse_monitor_hex_line,
    payload_hex,
    payload_views,
)

log = logging.getLogger("cozy.web.airtalk_monitor")

DEFAULT_PORT_GLOBS = (
    "/dev/serial/by-id/usb-Arduino_Nano_33_BLE*",
)
BAUD = int(os.environ.get("COZY_AIRTALK_BAUD", "115200"))
LOG_PATH = os.environ.get("COZY_AIRTALK_LOG", "/tmp/cozy-airtalk-frames.jsonl")
LOG_MAX_BYTES = 8 * 1024 * 1024
FIX_AT_KEYS = (
    "MGL_AT_PITCH",
    "MGL_AT_ROLL",
    "MGL_AT_HEAD",
    "MGL_AT_YAW",
    "MGL_AT_SLIP",
    "MGL_AT_G",
    "MGL_AT_TURN",
    "MGL_AT_MISC",
    "MGL_AT_HEAD_STATUS",
)


@dataclass
class MsgStats:
    dest: int
    msg_type: int
    length: int
    data: bytes = b""
    status: str = "OK"
    count: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0


@dataclass
class MonitorState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    port: str | None = None
    banner: str = ""
    invert: int | None = None
    uart: int | None = None
    rx_bytes: int = 0
    rx_frames: int = 0
    ok_count: int = 0
    bad_count: int = 0
    last_frame_ts: float | None = None
    last_e4_ts: float | None = None
    last_e6_ts: float | None = None
    bus_error: str | None = None
    messages: dict[str, MsgStats] = field(default_factory=dict)
    recent: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=40))
    started_ts: float = field(default_factory=time.time)


def find_port() -> str | None:
    env = os.environ.get("COZY_AIRTALK_PORT", "").strip()
    if env and os.path.exists(env):
        return env
    found: list[str] = []
    for pattern in DEFAULT_PORT_GLOBS:
        found.extend(sorted(glob.glob(pattern)))
    # Prefer by-id paths (stable) over raw ttyACM.
    by_id = [p for p in found if "/by-id/" in p]
    if by_id:
        return by_id[0]
    return found[0] if found else None


class AirtalkMonitorService:
    def __init__(self) -> None:
        self.state = MonitorState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fix_client = None
        self._fix_cache: dict[str, Any] = {"ok": False, "keys": {}}
        self._fix_cache_ts = 0.0

    def _fix_attitude(self) -> dict[str, Any]:
        now = time.time()
        if now - self._fix_cache_ts < 0.4:
            return self._fix_cache
        out: dict[str, Any] = {"ok": False, "keys": {}, "error": None}
        try:
            from historian.capture.fix_client import FixClient

            if self._fix_client is None or not self._fix_client.is_connected():
                client = FixClient(host="127.0.0.1", port=3490, timeout=1.0)
                client.connect(FIX_AT_KEYS)
                self._fix_client = client
            samples = self._fix_client.read_many(FIX_AT_KEYS)
            keys = {
                k: (None if s is None else s.value) for k, s in samples.items()
            }
            out = {"ok": True, "keys": keys, "error": None}
        except Exception as e:
            out = {"ok": False, "keys": {}, "error": str(e)}
            self._fix_client = None
        self._fix_cache = out
        self._fix_cache_ts = now
        return out

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="airtalk-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _append_log(self, rec: str) -> None:
        try:
            path = LOG_PATH
            if path and os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
                os.replace(path, path + ".old")
            with open(path, "a", encoding="utf-8") as f:
                f.write(rec)
        except OSError:
            pass

    def _note_banner(self, line: str) -> None:
        with self.state.lock:
            if line.startswith("# nano_airtalk_monitor"):
                self.state.banner = line[2:].strip()
            if "invert=" in line:
                try:
                    part = line.split("invert=", 1)[1]
                    self.state.invert = int(part.split()[0].rstrip("\r"))
                except (ValueError, IndexError):
                    pass
            if "uart=" in line:
                try:
                    part = line.split("uart=", 1)[1]
                    self.state.uart = int(part.split()[0].rstrip("\r"))
                except (ValueError, IndexError):
                    pass

    def _accept_frame(self, frame, now: float) -> None:
        with self.state.lock:
            self.state.rx_frames += 1
            self.state.last_frame_ts = now
            if frame.ok:
                self.state.ok_count += 1
                if frame.dest == 0xE4:
                    self.state.last_e4_ts = now
                if frame.dest == 0xE6:
                    self.state.last_e6_ts = now
            else:
                self.state.bad_count += 1
            key = frame.key()
            st = self.state.messages.get(key)
            if st is None:
                st = MsgStats(
                    dest=frame.dest,
                    msg_type=frame.msg_type,
                    length=frame.length,
                    first_ts=now,
                )
                self.state.messages[key] = st
            st.count += 1
            st.data = frame.data
            st.length = frame.length
            st.status = frame.status
            st.last_ts = now
            rec = {
                "t": now,
                "check": frame.status,
                "dest": f"{frame.dest:02X}",
                "type": f"{frame.msg_type:02X}",
                "len": frame.length,
                "data": payload_hex(frame.data),
            }
            self.state.recent.append(rec)
        if frame.ok:
            self._append_log(
                f'{{"t":{now:.3f},"dest":"{frame.dest:02X}","type":"{frame.msg_type:02X}",'
                f'"len":{frame.length},"data":"{payload_hex(frame.data)}"}}\n'
            )

    def _run(self) -> None:
        try:
            import serial  # type: ignore
        except ImportError:
            with self.state.lock:
                self.state.bus_error = "pyserial not installed"
                self.state.running = False
            return

        backoff = 1.0
        while not self._stop.is_set():
            port = find_port()
            with self.state.lock:
                self.state.port = port
                self.state.running = True
            if not port:
                with self.state.lock:
                    self.state.bus_error = "Nano Airtalk USB not found"
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            ser = None
            assembler = FrameAssembler()
            line_buf = ""
            try:
                ser = serial.Serial(
                    port,
                    BAUD,
                    timeout=0.2,
                    dsrdtr=False,
                    rtscts=False,
                )
                with self.state.lock:
                    self.state.bus_error = None
                backoff = 1.0
                log.info("airtalk monitor listening on %s", port)
                time.sleep(0.3)
                try:
                    ser.reset_input_buffer()
                    ser.write(b"help\n")
                    ser.flush()
                except Exception:
                    pass
                last_stats = 0.0
                while not self._stop.is_set():
                    raw = ser.read(512)
                    now = time.time()
                    if raw:
                        with self.state.lock:
                            self.state.rx_bytes += len(raw)
                        text = raw.decode("ascii", errors="replace")
                        line_buf += text
                        while "\n" in line_buf:
                            line, line_buf = line_buf.split("\n", 1)
                            line = line.strip("\r")
                            if line.startswith("#"):
                                self._note_banner(line)
                                continue
                            chunk = parse_monitor_hex_line(line)
                            if not chunk:
                                continue
                            for frame in assembler.feed(chunk):
                                self._accept_frame(frame, now)
                    if now - last_stats > 5.0:
                        last_stats = now
                        try:
                            ser.write(b"stats\n")
                            ser.flush()
                        except Exception:
                            pass
            except Exception as e:
                log.warning("airtalk monitor serial error: %s", e)
                with self.state.lock:
                    self.state.bus_error = str(e)
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 10.0)
            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass

        with self.state.lock:
            self.state.running = False

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self.state.lock:
            age = (
                None
                if self.state.last_frame_ts is None
                else int((now - self.state.last_frame_ts) * 1000)
            )
            link = {
                "port": self.state.port,
                "baud": BAUD,
                "status": "UP" if self.state.port and not self.state.bus_error else "DOWN",
                "running": self.state.running,
                "banner": self.state.banner,
                "invert": self.state.invert,
                "uart": self.state.uart,
                "rx_bytes": self.state.rx_bytes,
                "rx_frames": self.state.rx_frames,
                "ok_count": self.state.ok_count,
                "bad_count": self.state.bad_count,
                "last_frame_age_ms": age,
                "last_sp2_age_ms": (
                    None
                    if self.state.last_e4_ts is None
                    else int((now - self.state.last_e4_ts) * 1000)
                ),
                "last_sp7_age_ms": (
                    None
                    if self.state.last_e6_ts is None
                    else int((now - self.state.last_e6_ts) * 1000)
                ),
                "bus_error": self.state.bus_error,
                "log_path": LOG_PATH,
            }
            items = list(self.state.messages.values())
            recent = list(self.state.recent)

        messages: list[dict[str, Any]] = []
        for st in sorted(items, key=lambda s: (s.dest, s.msg_type)):
            elapsed = max(st.last_ts - st.first_ts, 1e-6)
            rate = (st.count - 1) / elapsed if st.count > 1 else 0.0
            views = payload_views(st.data)
            decoded = decode_fields(st.dest, st.msg_type, st.data)
            messages.append(
                {
                    "key": f"{st.dest:02X}:{st.msg_type:02X}",
                    "dest": f"{st.dest:02X}",
                    "dest_int": st.dest,
                    "label": dest_label(st.dest),
                    "type": f"{st.msg_type:02X}",
                    "len": st.length,
                    "check": st.status,
                    "rate_hz": round(rate, 2),
                    "age_ms": int((now - st.last_ts) * 1000),
                    "count": st.count,
                    "data": views["hex"],
                    "bytes": views["bytes"],
                    "i16le": views["i16le"],
                    "i16be": views["i16be"],
                    "u16le": views["u16le"],
                    "u16be": views["u16be"],
                    "decoded": decoded,
                }
            )

        return {
            "type": "mgl_airtalk_update",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "airtalk": link,
            "fix": self._fix_attitude(),
            "messages": messages,
            "recent": recent[-20:],
        }


_monitor: AirtalkMonitorService | None = None
_monitor_lock = threading.Lock()


def get_monitor() -> AirtalkMonitorService:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = AirtalkMonitorService()
        return _monitor
