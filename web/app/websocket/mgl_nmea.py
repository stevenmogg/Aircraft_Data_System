"""WebSocket /ws/mgl-nmea — live MGL Extreme NMEA snapshots."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.app.services.nmea_monitor import get_monitor

log = logging.getLogger("cozy.web.mgl_nmea_ws")
router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@router.websocket("/ws/mgl-nmea")
async def websocket_mgl_nmea(websocket: WebSocket):
    await websocket.accept()
    monitor = get_monitor()
    monitor.start()
    try:
        await websocket.send_json(
            {
                "type": "status",
                "service": "mgl-nmea",
                "state": "connected",
                "timestamp": _utc_now(),
            }
        )
        period = 0.25
        while True:
            try:
                snap = await asyncio.to_thread(monitor.snapshot)
                await websocket.send_json(snap)
            except Exception as e:
                await websocket.send_json(
                    {
                        "type": "error",
                        "source": "mgl-nmea",
                        "message": str(e),
                        "timestamp": _utc_now(),
                    }
                )
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=period)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                raise
    except WebSocketDisconnect:
        log.info("mgl-nmea ws disconnected")
    except Exception:
        log.exception("mgl-nmea ws error")
