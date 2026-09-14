"""MGL NMEA monitor REST API."""

from __future__ import annotations

from fastapi import APIRouter

from web.app.services.nmea_monitor import get_monitor

router = APIRouter(prefix="/api/mgl-nmea", tags=["mgl-nmea"])


@router.get("/snapshot")
def snapshot():
    return get_monitor().snapshot()
