"""REST: Historian start/stop via control socket."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.app.services import historian as hist_svc

router = APIRouter(prefix="/api/historian", tags=["historian"])


class StartBody(BaseModel):
    duration_s: float | None = None
    flight_id: str | None = None


@router.post("/start")
def start_recording(body: StartBody | None = None):
    body = body or StartBody()
    resp = hist_svc.start_recording(duration_s=body.duration_s, flight_id=body.flight_id)
    if not resp.get("ok"):
        raise HTTPException(status_code=409, detail=resp.get("error") or resp)
    return resp


@router.post("/stop")
def stop_recording():
    resp = hist_svc.stop_recording()
    if not resp.get("ok"):
        raise HTTPException(status_code=409, detail=resp.get("error") or resp)
    return resp
