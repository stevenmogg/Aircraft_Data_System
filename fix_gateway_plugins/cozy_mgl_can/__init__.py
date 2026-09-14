"""MGL CAN → FIX adapter (receive-only SocketCAN).

Decodes frames with config/mgl_can/decode_map.yaml and writes numeric
fix_key values (MGL_RDAC_*). Does not transmit. Failure to open can0 is
degraded, not fatal to FIX-Gateway.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from pathlib import Path

import can
import fixgw.plugin as plugin

from web.app.services.mgl_decode import DecodeMap, RdacCompensator, fields_to_fix


class MainThread(threading.Thread):
    def __init__(self, parent: "Plugin"):
        super().__init__(daemon=True)
        self.parent = parent
        self.log = parent.log
        self.getout = False
        self.interface = str(parent.config.get("interface", "socketcan"))
        self.channel = str(parent.config.get("channel", "can0"))
        map_path = parent.config.get("decode_map")
        self.map = DecodeMap(Path(map_path) if map_path else None)
        self._rdac = RdacCompensator()
        self._fail_logged = False

    def run(self):
        self.log.info(
            "MGL CAN adapter %s/%s receive_only (map=%s)",
            self.interface,
            self.channel,
            self.map.path,
        )
        backoff = 1.0
        while not self.getout:
            bus = None
            try:
                bus = can.ThreadSafeBus(self.channel, interface=self.interface)
                self.parent.status["link"] = "UP"
                self.parent.status["error"] = None
                self._fail_logged = False
                backoff = 1.0
                self.log.info("MGL CAN listening on %s", self.channel)
                while not self.getout:
                    msg = bus.recv(1.0)
                    if msg is None:
                        continue
                    self._accept(msg)
            except Exception as e:
                if not self._fail_logged:
                    self.log.warning("MGL CAN open/read failed: %s", e)
                    self._fail_logged = True
                self.parent.status["link"] = "DOWN"
                self.parent.status["error"] = str(e)
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
            finally:
                if bus is not None:
                    try:
                        bus.shutdown()
                    except Exception:
                        pass

    def _accept(self, msg) -> None:
        st = self.parent.status
        st["rx_frames"] = int(st.get("rx_frames", 0)) + 1
        st["last_frame_ts"] = time.time()
        if getattr(msg, "is_error_frame", False):
            st["error_frames"] = int(st.get("error_frames", 0)) + 1
            return
        fields = self.map.decode_frame(int(msg.arbitration_id), bytes(msg.data))
        if not fields:
            st["unknown_frames"] = int(st.get("unknown_frames", 0)) + 1
            return
        values = self._rdac.apply(fields_to_fix(fields))
        if not values:
            return
        write = self.parent.db_write
        for key, value in values.items():
            try:
                write(key, value)
            except Exception as e:
                self.log.debug("db_write %s failed: %s", key, e)
        st["decoded_frames"] = int(st.get("decoded_frames", 0)) + 1

    def stop(self):
        self.getout = True


class Plugin(plugin.PluginBase):
    def __init__(self, name, config, config_meta):
        super().__init__(name, config, config_meta)
        self.thread = MainThread(self)
        self.status = OrderedDict(
            {
                "channel": config.get("channel", "can0"),
                "link": "INIT",
                "rx_frames": 0,
                "decoded_frames": 0,
                "unknown_frames": 0,
                "error_frames": 0,
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
