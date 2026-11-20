"""AvPlan GPX listing and manual merge into a Historian flight."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from web.app.services import historian as hist_svc

router = APIRouter(prefix="/api/avplan", tags=["avplan"])


class ImportBody(BaseModel):
    flight_id: str
    gpx_name: str


class CreateBody(BaseModel):
    gpx_name: str


def _avplan_http_error(e: Exception) -> HTTPException:
    if isinstance(e, FileNotFoundError):
        return HTTPException(404, detail=str(e))
    if isinstance(e, ValueError) and "already imported" in str(e):
        return HTTPException(409, detail=str(e))
    return HTTPException(400, detail=str(e))


@router.get("/gpx")
def list_gpx(flight_id: str | None = Query(default=None)):
    return hist_svc.list_avplan_gpx(flight_id)


@router.post("/import")
def import_gpx(body: ImportBody):
    try:
        return hist_svc.import_avplan_gpx(body.flight_id, body.gpx_name)
    except (FileNotFoundError, ValueError) as e:
        raise _avplan_http_error(e) from e


@router.post("/create-flight")
def create_flight(body: CreateBody):
    try:
        return hist_svc.create_flight_from_avplan(body.gpx_name)
    except (FileNotFoundError, ValueError) as e:
        raise _avplan_http_error(e) from e
