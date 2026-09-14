"""MGL Airtalk monitor REST API."""

from __future__ import annotations

from fastapi import APIRouter

from web.app.services.airtalk_monitor import get_monitor

router = APIRouter(prefix="/api/mgl-airtalk", tags=["mgl-airtalk"])


@router.get("/snapshot")
def snapshot():
    return get_monitor().snapshot()
