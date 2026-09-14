"""REST: flights catalogue and manifest."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from web.app.services import historian as hist_svc

router = APIRouter(prefix="/api", tags=["flights"])


@router.get("/flights")
def list_flights():
    return {"ok": True, "flights": hist_svc.list_flights()}


@router.get("/flights/{flight_id}")
def get_flight(flight_id: str):
    try:
        return {"ok": True, "flight": hist_svc.get_flight(flight_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/flights/{flight_id}/manifest")
def get_manifest(flight_id: str):
    try:
        return {"ok": True, "manifest": hist_svc.get_manifest(flight_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
