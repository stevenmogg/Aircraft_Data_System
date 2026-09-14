"""WebSocket /ws/mgl-airtalk — live Airtalk monitor snapshots."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.app.services.airtalk_monitor import get_monitor

log = logging.getLogger("cozy.web.mgl_airtalk_ws")
router = APIRouter()


def _web_serial_enabled() -> bool:
    return os.environ.get("COZY_AIRTALK_WEB_SERIAL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@router.websocket("/ws/mgl-airtalk")
async def websocket_mgl_airtalk(websocket: WebSocket):
    await websocket.accept()
    monitor = get_monitor()
    # FIX-Gateway owns the Nano USB port. Only grab it when explicitly opted in.
    if _web_serial_enabled():
        monitor.start()
    try:
        await websocket.send_json(
            {
                "type": "status",
                "service": "mgl-airtalk",
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
                        "source": "mgl-airtalk",
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
        log.info("mgl-airtalk ws disconnected")
    except Exception:
        log.exception("mgl-airtalk ws error")
