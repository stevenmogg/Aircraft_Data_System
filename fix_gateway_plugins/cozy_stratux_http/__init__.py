"""Stratux → FIX adapter via HTTP /getSituation.

Upstream fixgw.plugins.stratux reads GDL90 UDP (msg 0x4C). Stratux only fills
real pitch/roll in that message when GPS is valid (isAHRSValid). Without GPS,
GDL90 sends 0x7FFF sentinels even though /getSituation has live AHRS.

This plugin polls Stratux's JSON API so AHRS works on the bench without GPS,
and publishes GPS ownship (STRX_LAT/STRX_LONG/STRX_GS/STRX_TRACK/…) when Stratux has a fix.
"""

from __future__ import annotations

import math
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict

import fixgw.plugin as plugin

try:
    import json
except ImportError:  # pragma: no cover
    import simplejson as json

# Stratux ahrs.Invalid sentinel
INVALID = 3276.7


def _valid(val) -> bool:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return False
    return abs(v - INVALID) >= 0.01


def _safe_write(write, key: str, value) -> None:
    """Write FIX key; ignore missing keys so optional GPS fields never crash the plugin."""
    try:
        write(key, value)
    except Exception:
        pass


class MainThread(threading.Thread):
    def __init__(self, parent: "Plugin"):
        super().__init__(daemon=True)
        self.parent = parent
        self.log = parent.log
        self.getout = False
        self.url = parent.config.get("url", "http://127.0.0.1/getSituation")
        self.interval = float(parent.config.get("interval", 0.1))
        self.timeout = float(parent.config.get("timeout", 1.0))
        self._fail_logged = False

    def run(self):
        self.log.info("Stratux HTTP adapter polling %s every %.2fs", self.url, self.interval)
        while not self.getout:
            try:
                with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self._publish(data)
                self._fail_logged = False
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                if not self._fail_logged:
                    self.log.warning("Stratux HTTP read failed: %s", e)
                    self._fail_logged = True
            time.sleep(self.interval)

    def _publish(self, d: dict):
        write = self.parent.db_write

        pitch = d.get("AHRSPitch")
        roll = d.get("AHRSRoll")
        if _valid(pitch):
            write("STRX_PITCH", float(pitch))
        if _valid(roll):
            write("STRX_ROLL", float(roll))

        head = d.get("AHRSGyroHeading")
        if _valid(head):
            write("STRX_HEAD", float(head))

        slip = d.get("AHRSSlipSkid")
        if _valid(slip):
            # Match stock Stratux GDL90 plugin: ALAT = -sin(slip_skid deg)
            write("STRX_ALAT", -math.sin(float(slip) * math.pi / 180.0))

        # Baro is independent of GPS / isAHRSValid — keep on STRX_PALT always.
        if d.get("BaroPressureAltitude") is not None:
            write("STRX_PALT", float(d["BaroPressureAltitude"]))
            # Until GPS altitude is available, also publish baro as STRX_ALT.
            if not (
                d.get("GPSFixQuality", 0)
                and d.get("GPSAltitudeMSL") is not None
                and _valid(d.get("GPSLatitude"))
            ):
                write("STRX_ALT", float(d["BaroPressureAltitude"]))
        if d.get("BaroVerticalSpeed") is not None:
            write("STRX_VS", float(d["BaroVerticalSpeed"]))

        # GPS ownship when Stratux has a usable fix
        fix_q = int(d.get("GPSFixQuality") or 0)
        lat = d.get("GPSLatitude")
        lon = d.get("GPSLongitude")
        if fix_q >= 1 and _valid(lat) and _valid(lon):
            write("STRX_LAT", float(lat))
            write("STRX_LONG", float(lon))
            _safe_write(write, "STRX_GPS_FIX_TYPE", fix_q)

            if d.get("GPSGroundSpeed") is not None:
                write("STRX_GS", float(d["GPSGroundSpeed"]))
            if d.get("GPSTrueCourse") is not None and _valid(d.get("GPSTrueCourse")):
                write("STRX_TRACK", float(d["GPSTrueCourse"]))
                # Prefer GPS track for HEAD when AHRS mag/gyro heading is invalid
                if not _valid(head):
                    write("STRX_HEAD", float(d["GPSTrueCourse"]))

            if d.get("GPSAltitudeMSL") is not None:
                write("STRX_ALT", float(d["GPSAltitudeMSL"]))
            if d.get("GPSHeightAboveEllipsoid") is not None:
                _safe_write(write, "STRX_GPS_ELLIPSOID_ALT", float(d["GPSHeightAboveEllipsoid"]))
            if d.get("GPSVerticalSpeed") is not None and d.get("BaroVerticalSpeed") is None:
                write("STRX_VS", float(d["GPSVerticalSpeed"]))

            sats = d.get("GPSSatellitesTracked")
            if sats is None:
                sats = d.get("GPSSatellites")
            if sats is not None:
                _safe_write(write, "STRX_GPS_SATS_TRACKED", int(sats))

            if d.get("GPSHorizontalAccuracy") is not None:
                _safe_write(write, "STRX_GPS_ACCURACY_HORIZ", float(d["GPSHorizontalAccuracy"]))
            if d.get("GPSVerticalAccuracy") is not None:
                _safe_write(write, "STRX_GPS_ACCURACY_VERTICAL", float(d["GPSVerticalAccuracy"]))

            self.parent.status["gps"] = {
                "fix_quality": fix_q,
                "lat": float(lat),
                "lon": float(lon),
                "sats": sats,
            }
        else:
            self.parent.status["gps"] = {"fix_quality": fix_q, "lat": None, "lon": None}

    def stop(self):
        self.getout = True


class Plugin(plugin.PluginBase):
    def __init__(self, name, config, config_meta):
        super().__init__(name, config, config_meta)
        self.thread = MainThread(self)
        self.status = OrderedDict()

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
