"""GET /api/status — live system / FIX / Historian / GPS / network state."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from fastapi import APIRouter

from web.app.services import external_data as ext_svc
from web.app.services import fix as fix_svc
from web.app.services import historian as hist_svc
from web.app.services import system as sys_svc
from web.app.services import wifi as wifi_svc

router = APIRouter(prefix="/api", tags=["status"])


def _stratux_gps() -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "reachable": False}
    try:
        with urllib.request.urlopen("http://127.0.0.1/getStatus", timeout=1.0) as resp:
            st = json.loads(resp.read().decode("utf-8"))
        out["reachable"] = True
        out["GPS_connected"] = st.get("GPS_connected")
        out["GPS_solution"] = st.get("GPS_solution")
        out["GPS_satellites_tracked"] = st.get("GPS_satellites_tracked")
        out["GPS_satellites_locked"] = st.get("GPS_satellites_locked")
        out["GPS_satellites_seen"] = st.get("GPS_satellites_seen")
        out["CPUTemp"] = st.get("CPUTemp")
        out["IMUConnected"] = st.get("IMUConnected")
        out["BMPConnected"] = st.get("BMPConnected")
    except Exception as e:
        out["error"] = str(e)
        return out

    try:
        with urllib.request.urlopen("http://127.0.0.1/getSituation", timeout=1.0) as resp:
            sit = json.loads(resp.read().decode("utf-8"))
        out["lat"] = sit.get("GPSLatitude")
        out["lon"] = sit.get("GPSLongitude")
        out["fix_quality"] = sit.get("GPSFixQuality")
        out["alt_msl"] = sit.get("GPSAltitudeMSL")
        out["gs"] = sit.get("GPSGroundSpeed")
        out["track"] = sit.get("GPSTrueCourse")
        out["pitch"] = sit.get("AHRSPitch")
        out["roll"] = sit.get("AHRSRoll")
        out["ok"] = bool(out.get("GPS_connected"))
    except Exception as e:
        out["situation_error"] = str(e)
    return out


def _wifi_live(wifi: dict[str, Any]) -> dict[str, Any]:
    """Runtime link state only (not configured network lists)."""
    ifaces = []
    for iface in wifi.get("interfaces") or []:
        ifaces.append(
            {
                "iface": iface.get("iface"),
                "role": iface.get("role"),
                "state": iface.get("state"),
                "ssid": iface.get("ssid"),
                "ip_address": iface.get("ip_address") or iface.get("addr"),
            }
        )
    ap = wifi.get("stratux") or {}
    return {
        "ok": True,
        "interfaces": ifaces,
        "ap_ssid": ap.get("ap_ssid") if ap.get("ok") else None,
        "wifi_mode": ap.get("wifi_mode") if ap.get("ok") else None,
    }


@router.get("/status")
def get_status():
    fix = fix_svc.fix_status()
    samples = fix.get("samples") or {}
    for k, v in samples.items():
        fix[f"sample_{k}"] = v

    wifi_full = wifi_svc.wifi_configuration()
    ext = ext_svc.external_data_status()
    system = sys_svc.system_status()
    hist = hist_svc.historian_status()
    gps = _stratux_gps()

    return {
        "ok": True,
        "fix": fix,
        "historian": hist,
        "system": system,
        "gps": gps,
        "wifi": _wifi_live(wifi_full),
        "external_data": {
            "collection_state": ext.get("collection_state"),
            "card_mounted": ext.get("card_mounted"),
            "installed": ext.get("installed"),
            "last_sync": ext.get("last_sync"),
            "import_enigma": ext.get("import_enigma"),
        },
    }
