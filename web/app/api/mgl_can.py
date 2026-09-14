"""MGL CAN monitor REST API."""

from __future__ import annotations

from fastapi import APIRouter

from web.app.services.can_monitor import get_monitor

router = APIRouter(prefix="/api/mgl-can", tags=["mgl-can"])


@router.get("/snapshot")
def snapshot():
    return get_monitor().snapshot()


@router.post("/reload-config")
def reload_config():
    return get_monitor().reload_config()
