"""Flight data series + CSV export."""

from __future__ import annotations

import csv
import io
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from web.app.services import historian as hist_svc

router = APIRouter(prefix="/api", tags=["export"])

MAX_PLOT_COLUMNS = 4


def _validate_series_columns(requested: list[str], available: set[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in requested:
        if c not in seen:
            seen.add(c)
            out.append(c)
    if not out:
        raise HTTPException(400, detail="select at least one column")
    if len(out) > MAX_PLOT_COLUMNS:
        raise HTTPException(400, detail=f"at most {MAX_PLOT_COLUMNS} columns")
    bad = [c for c in out if c not in available]
    if bad:
        raise HTTPException(400, detail=f"unsupported columns: {bad}")
    return out


@router.get("/flights/{flight_id}/plot-fields")
def flight_plot_fields(flight_id: str):
    try:
        hist_svc.get_flight(flight_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    return hist_svc.list_plot_fields()


@router.get("/flights/{flight_id}/series")
def flight_series(
    flight_id: str,
    columns: str = Query(""),
    max_points: int = Query(2000, ge=10, le=20000),
):
    db = hist_svc._db()
    with db.connect() as conn:
        available = hist_svc.available_series_columns(conn)
        exists = conn.execute(
            "SELECT 1 FROM flight WHERE flight_id=?", (flight_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, detail=f"unknown flight_id {flight_id}")
    raw = [c.strip() for c in columns.split(",") if c.strip()]
    if not raw:
        raw = hist_svc.list_plot_fields().get("defaults") or []
    cols = _validate_series_columns(raw, available)
    try:
        return {
            "ok": True,
            "flight_id": flight_id,
            "columns": cols,
            "series": hist_svc.series_10hz(flight_id, cols, max_points=max_points),
        }
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e


@router.get("/flights/{flight_id}/tracks")
def flight_tracks(flight_id: str, max_points: int = Query(2000, ge=10, le=20000)):
    try:
        return hist_svc.flight_tracks(flight_id, max_points=max_points)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e


@router.get("/export/{flight_id}")
def export_flight_csv(flight_id: str):
    try:
        it = hist_svc.iter_export_csv(flight_id)
        fieldnames = next(it)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e

    def generate():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for row in it:
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"{flight_id}_10hz.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
