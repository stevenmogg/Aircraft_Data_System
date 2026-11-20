"""WebSocket /ws/live — FIX current-state snapshots at ~10 Hz."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.app.services import fix as fix_svc
from web.app.services import historian as hist_svc
from web.app.websocket.manager import manager

log = logging.getLogger("cozy.web.live")
router = APIRouter()

LIVE_KEYS = [
    "STRX_PITCH",
    "STRX_ROLL",
    "STRX_HEAD",
    "STRX_ALT",
    "STRX_PALT",
    "STRX_VS",
    "STRX_LAT",
    "STRX_LONG",
    "STRX_GS",
    "STRX_TRACK",
    "STRX_GPS_SATS_TRACKED",
    "STRX_GPS_FIX_TYPE",
    "STRX_ALAT",
    "MGL_AT_PITCH",
    "MGL_AT_ROLL",
    "MGL_AT_HEAD",
    "MGL_AT_YAW",
    "MGL_AT_SLIP",
    "MGL_AT_G",
    "MGL_RDAC_RPM1",
    "MGL_RDAC_RPM2",
    "MGL_RDAC_MAP_RAW",
    "MGL_RDAC_CURRENT_RAW",
    "MGL_RDAC_TEMP",
    "MGL_RDAC_OILT_RAW",
    "MGL_RDAC_OILP_RAW",
    "MGL_RDAC_FUELP_RAW",
    "MGL_RDAC_COOLANT_RAW",
    "MGL_RDAC_FUELLEVEL1_RAW",
    "MGL_RDAC_FUELLEVEL2_RAW",
    "MGL_RDAC_AUX1_RAW",
    "MGL_RDAC_AUX2_RAW",
    *[f"MGL_RDAC_TC{i}" for i in range(1, 13)],
    "MGL_NMEA_LAT",
    "MGL_NMEA_LONG",
    "MGL_NMEA_ALT",
    "MGL_NMEA_GS",
    "MGL_NMEA_TRACK",
    "MGL_NMEA_QUAL",
    "MGL_NMEA_SATS",
    "MGL_NMEA_HDOP",
    "MGL_NMEA_TIME",
    "MGL_NMEA_DATE",
    "MGL_NMEA_STATUS",
    "MGL_NMEA_MODE",
    "MGL_NMEA_VALID",
    "MGL_NMEA_CSUM_OK",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_state_message(samples: dict, hist: dict) -> dict:
    def val(key: str):
        s = samples.get(key)
        return None if s is None else s.value

    recording = hist.get("state") == "RECORDING"
    return {
        "type": "state",
        "timestamp": _utc_now(),
        "flight_time_s": None,  # filled when recording if known
        "mgl": {
            "pitch": val("MGL_AT_PITCH"),
            "roll": val("MGL_AT_ROLL"),
            "heading": val("MGL_AT_HEAD"),
            "yaw": val("MGL_AT_YAW"),
            "slip": val("MGL_AT_SLIP"),
            "g": val("MGL_AT_G"),
        },
        "rdac": {
            "rpm1": val("MGL_RDAC_RPM1"),
            "rpm2": val("MGL_RDAC_RPM2"),
            "map_raw": val("MGL_RDAC_MAP_RAW"),
            "current_raw": val("MGL_RDAC_CURRENT_RAW"),
            "temp": val("MGL_RDAC_TEMP"),
            "oilt_raw": val("MGL_RDAC_OILT_RAW"),
            "oilp_raw": val("MGL_RDAC_OILP_RAW"),
            "fuelp_raw": val("MGL_RDAC_FUELP_RAW"),
            "coolant_raw": val("MGL_RDAC_COOLANT_RAW"),
            "fuellevel1_raw": val("MGL_RDAC_FUELLEVEL1_RAW"),
            "fuellevel2_raw": val("MGL_RDAC_FUELLEVEL2_RAW"),
            "aux1_raw": val("MGL_RDAC_AUX1_RAW"),
            "aux2_raw": val("MGL_RDAC_AUX2_RAW"),
            **{f"tc{i}": val(f"MGL_RDAC_TC{i}") for i in range(1, 13)},
        },
        "attitude": {
            "pitch": val("STRX_PITCH"),
            "roll": val("STRX_ROLL"),
            "heading": val("STRX_HEAD"),
        },
        "air": {
            "ias": None,
            "tas": None,
            "pressure_altitude": val("STRX_PALT") if val("STRX_PALT") is not None else val("STRX_ALT"),
            "vs": val("STRX_VS"),
        },
        "position": {
            "lat": val("STRX_LAT"),
            "lon": val("STRX_LONG"),
            "gps_alt": val("STRX_ALT"),
            "groundspeed": val("STRX_GS"),
            "track": val("STRX_TRACK"),
            "sats": val("STRX_GPS_SATS_TRACKED"),
            "fix_type": val("STRX_GPS_FIX_TYPE"),
        },
        "nmea": {
            "lat": val("MGL_NMEA_LAT"),
            "lon": val("MGL_NMEA_LONG"),
            "alt": val("MGL_NMEA_ALT"),
            "groundspeed": val("MGL_NMEA_GS"),
            "track": val("MGL_NMEA_TRACK"),
            "qual": val("MGL_NMEA_QUAL"),
            "sats": val("MGL_NMEA_SATS"),
            "hdop": val("MGL_NMEA_HDOP"),
            "time": val("MGL_NMEA_TIME"),
            "date": val("MGL_NMEA_DATE"),
            "status": val("MGL_NMEA_STATUS"),
            "mode": val("MGL_NMEA_MODE"),
            "valid": val("MGL_NMEA_VALID"),
            "csum_ok": val("MGL_NMEA_CSUM_OK"),
        },
        "system": {
            "fix_ok": True,
            "historian_recording": recording,
            "historian_state": hist.get("state"),
            "flight_id": hist.get("flight_id") if recording else hist.get("flight_id"),
        },
    }


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await manager.connect(websocket)
    client = None
    try:
        from historian.capture.fix_client import FixClient

        client = FixClient(host="127.0.0.1", port=3490, timeout=2.0)
        # connect in thread pool — blocking netfix client
        await asyncio.to_thread(client.connect, LIVE_KEYS)
        await websocket.send_json(
            {
                "type": "status",
                "service": "websocket",
                "state": "connected",
            }
        )
        period = 0.1  # 10 Hz
        while True:
            try:
                samples = await asyncio.to_thread(client.read_many, LIVE_KEYS)
                hist = await asyncio.to_thread(hist_svc.historian_status)
                msg = build_state_message(samples, hist)
                await websocket.send_json(msg)
            except Exception as e:
                await websocket.send_json(
                    {
                        "type": "error",
                        "source": "fix",
                        "message": str(e),
                        "timestamp": _utc_now(),
                    }
                )
            # allow client ping / ignore inbound
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=period)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                raise
    except WebSocketDisconnect:
        log.info("live ws disconnected")
    except Exception as e:
        log.exception("live ws error")
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "source": "websocket",
                    "message": str(e),
                    "timestamp": _utc_now(),
                }
            )
        except Exception:
            pass
    finally:
        await manager.disconnect(websocket)
        if client is not None:
            try:
                await asyncio.to_thread(client.disconnect)
            except Exception:
                pass
