"""Background SocketCAN listener for MGL commissioning monitor."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from web.app.services.mgl_decode import (
    DecodeMap,
    device_family,
    parse_id,
    payload_hex,
)

log = logging.getLogger("cozy.web.can_monitor")

CHANNEL = os.environ.get("COZY_CAN_CHANNEL", "can0")


@dataclass
class IdStats:
    can_id: int
    count: int = 0
    dlc: int = 0
    data: bytes = b""
    first_ts: float = 0.0
    last_ts: float = 0.0
    extended: bool = False
    is_error: bool = False


@dataclass
class MonitorState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    channel: str = CHANNEL
    interface_ok: bool = False
    interface_detail: str = ""
    bitrate: int | None = None
    listen_only: bool | None = None
    rx_count: int = 0
    error_count: int = 0
    last_frame_ts: float | None = None
    ids: dict[int, IdStats] = field(default_factory=dict)
    bus_error: str | None = None
    started_ts: float = field(default_factory=time.time)


class CanMonitorService:
    def __init__(self) -> None:
        self.state = MonitorState()
        self.map = DecodeMap()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="can-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def reload_config(self) -> dict[str, Any]:
        self.map.reload()
        return {
            "ok": self.map.error is None,
            "path": str(self.map.path) if self.map.path else None,
            "error": self.map.error,
            "message_rules": self.map.message_rule_count,
        }

    def _link_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "ok": False,
            "detail": "",
            "bitrate": None,
            "listen_only": None,
        }
        try:
            br = subprocess.run(
                ["ip", "-br", "link", "show", self.state.channel],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            detail = subprocess.run(
                ["ip", "-details", "link", "show", self.state.channel],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            br_out = (br.stdout or "").strip()
            out = (detail.stdout or "") + (detail.stderr or "")
            info["detail"] = out.strip() or br_out
            if br.returncode != 0 and detail.returncode != 0:
                return info
            # ip -br: "can0 UP ..."
            toks = br_out.split()
            info["ok"] = len(toks) >= 2 and toks[1] == "UP"
            parts = out.replace("\n", " ").split()
            if "bitrate" in parts:
                try:
                    info["bitrate"] = int(parts[parts.index("bitrate") + 1])
                except (ValueError, IndexError):
                    pass
            info["listen_only"] = "LISTEN-ONLY" in out
            return info
        except Exception as e:
            info["detail"] = str(e)
            return info

    def _run(self) -> None:
        try:
            import can
        except ImportError:
            with self.state.lock:
                self.state.bus_error = "python-can not installed"
                self.state.running = False
            return

        backoff = 1.0
        while not self._stop.is_set():
            link = self._link_info()
            with self.state.lock:
                self.state.interface_ok = bool(link["ok"])
                self.state.interface_detail = link["detail"]
                self.state.bitrate = link["bitrate"]
                self.state.listen_only = link["listen_only"]
                self.state.running = True

            if not link["ok"]:
                with self.state.lock:
                    self.state.bus_error = f"{self.state.channel} not UP"
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            bus = None
            try:
                bus = can.Bus(channel=self.state.channel, interface="socketcan")
                with self.state.lock:
                    self.state.bus_error = None
                backoff = 1.0
                log.info("can monitor listening on %s", self.state.channel)
                while not self._stop.is_set():
                    self.map.maybe_reload()
                    msg = bus.recv(timeout=0.5)
                    if msg is None:
                        continue
                    now = time.time()
                    with self.state.lock:
                        self.state.rx_count += 1
                        self.state.last_frame_ts = now
                        if getattr(msg, "is_error_frame", False):
                            self.state.error_count += 1
                        st = self.state.ids.get(msg.arbitration_id)
                        if st is None:
                            st = IdStats(
                                can_id=msg.arbitration_id,
                                first_ts=now,
                            )
                            self.state.ids[msg.arbitration_id] = st
                        st.count += 1
                        st.dlc = msg.dlc
                        st.data = bytes(msg.data)
                        st.last_ts = now
                        st.extended = bool(msg.is_extended_id)
                        st.is_error = bool(getattr(msg, "is_error_frame", False))
            except Exception as e:
                log.warning("can monitor bus error: %s", e)
                with self.state.lock:
                    self.state.bus_error = str(e)
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 10.0)
            finally:
                if bus is not None:
                    try:
                        bus.shutdown()
                    except Exception:
                        pass

        with self.state.lock:
            self.state.running = False

    def snapshot(self) -> dict[str, Any]:
        self.map.maybe_reload()
        now = time.time()
        with self.state.lock:
            link = {
                "interface": self.state.channel,
                "status": "UP" if self.state.interface_ok else "DOWN",
                "bitrate": self.state.bitrate or self.map.bitrate,
                "listen_only": self.state.listen_only,
                "rx_count": self.state.rx_count,
                "error_count": self.state.error_count,
                "last_frame_age_ms": (
                    None
                    if self.state.last_frame_ts is None
                    else int((now - self.state.last_frame_ts) * 1000)
                ),
                "bus_error": self.state.bus_error,
                "map_error": self.map.error,
                "map_path": str(self.map.path) if self.map.path else None,
                "running": self.state.running,
            }
            id_items = list(self.state.ids.values())

        messages: list[dict[str, Any]] = []
        mapped: list[dict[str, Any]] = []
        for st in sorted(id_items, key=lambda s: (-s.count, s.can_id)):
            device, msg = parse_id(st.can_id)
            elapsed = max(st.last_ts - st.first_ts, 1e-6)
            rate = (st.count - 1) / elapsed if st.count > 1 else 0.0
            has_map = self.map.has_mapping(device, msg)
            family = self.map.device_label(device) if device in self.map.devices else device_family(device)
            messages.append(
                {
                    "can_id": f"0x{st.can_id:X}",
                    "can_id_int": st.can_id,
                    "device_address": device,
                    "message_id": msg,
                    "family": family,
                    "dlc": st.dlc,
                    "rate_hz": round(rate, 2),
                    "age_ms": int((now - st.last_ts) * 1000),
                    "payload": payload_hex(st.data),
                    "extended": st.extended,
                    "decoder": "mapped" if has_map else "UNKNOWN",
                    "count": st.count,
                }
            )
            if has_map and not st.is_error:
                for row in self.map.decode_frame(st.can_id, st.data):
                    row["age_ms"] = int((now - st.last_ts) * 1000)
                    row["family"] = family
                    mapped.append(row)

        return {
            "type": "mgl_can_update",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "can": link,
            "messages": messages,
            "mapped": mapped,
        }


_monitor: CanMonitorService | None = None
_monitor_lock = threading.Lock()


def get_monitor() -> CanMonitorService:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = CanMonitorService()
            _monitor.start()
        return _monitor
