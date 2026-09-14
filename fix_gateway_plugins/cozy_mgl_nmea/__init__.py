"""MGL Extreme NMEA 0183 → FIX adapter (GPIO UART, receive-only).

Reads /dev/serial0 at 19200 8N1 (MAX3232 TTL into Pi pin 10 / GPIO15 RX).
Writes source-specific MGL_NMEA_* keys. Canonical LAT/LONG/GS/TRACK remain
Stratux (USB GPS). Never transmits on the UART.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict

import serial
import fixgw.plugin as plugin

from web.app.services.mgl_nmea import parse_line

DEFAULT_PORT = "/dev/serial0"
DEFAULT_BAUD = 19200


class MainThread(threading.Thread):
    def __init__(self, parent: "Plugin"):
        super().__init__(daemon=True)
        self.parent = parent
        self.log = parent.log
        self.getout = False
        self.port = str(parent.config.get("port", DEFAULT_PORT)).strip() or DEFAULT_PORT
        self.baud = int(parent.config.get("baud", DEFAULT_BAUD))
        self._fail_logged = False

    def run(self):
        self.log.info(
            "MGL NMEA adapter %s @ %d (receive_only)",
            self.port,
            self.baud,
        )
        backoff = 1.0
        while not self.getout:
            self.parent.status["port"] = self.port
            if not os.path.exists(self.port):
                if not self._fail_logged:
                    self.log.warning("MGL NMEA port not found: %s", self.port)
                    self._fail_logged = True
                self.parent.status["link"] = "DOWN"
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            ser = None
            buf = ""
            try:
                ser = serial.Serial(
                    self.port,
                    self.baud,
                    timeout=0.4,
                    write_timeout=0,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                    exclusive=True,
                )
                self._fail_logged = False
                backoff = 1.0
                self.parent.status["link"] = "UP"
                self.parent.status["error"] = None
                self.log.info("MGL NMEA listening on %s", self.port)
                while not self.getout:
                    raw = ser.read(512)
                    if not raw:
                        continue
                    self.parent.status["rx_bytes"] = (
                        int(self.parent.status.get("rx_bytes", 0)) + len(raw)
                    )
                    buf += raw.decode("ascii", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._accept(line.strip("\r"))
                    if len(buf) > 4096:
                        buf = buf[-1024:]
            except Exception as e:
                if not self._fail_logged:
                    self.log.warning("MGL NMEA serial error: %s", e)
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

    def _accept(self, line: str) -> None:
        if not line:
            return
        values = parse_line(line)
        if not values:
            return
        st = self.parent.status
        st["rx_sentences"] = int(st.get("rx_sentences", 0)) + 1
        st["last_sentence"] = values.get("MGL_NMEA_TYPE")
        st["last_ts"] = time.time()
        if not values.get("MGL_NMEA_CSUM_OK"):
            st["bad_csum"] = int(st.get("bad_csum", 0)) + 1
        else:
            st["ok_sentences"] = int(st.get("ok_sentences", 0)) + 1
        write = self.parent.db_write
        for key, value in values.items():
            try:
                write(key, value)
            except Exception as e:
                self.log.debug("db_write %s failed: %s", key, e)

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
                "rx_sentences": 0,
                "ok_sentences": 0,
                "bad_csum": 0,
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
