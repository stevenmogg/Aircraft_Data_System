"""Flight data series + CSV export."""

from __future__ import annotations

import csv
import io
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from web.app.services import historian as hist_svc

router = APIRouter(prefix="/api", tags=["export"])

ALLOWED_SERIES = {
    "fix_pitch",
    "fix_roll",
    "fix_head",
    "fix_alt",
    "fix_palt",
    "fix_vs",
    "fix_lat",
    "fix_long",
    "fix_gs",
    "fix_track",
    "fix_alat",
}


@router.get("/flights/{flight_id}/series")
def flight_series(
    flight_id: str,
    columns: str = Query("fix_pitch,fix_roll,fix_alt"),
    max_points: int = Query(2000, ge=10, le=20000),
):
    cols = [c.strip() for c in columns.split(",") if c.strip()]
    bad = [c for c in cols if c not in ALLOWED_SERIES]
    if bad:
        raise HTTPException(400, detail=f"unsupported columns: {bad}")
    try:
        return {
            "ok": True,
            "flight_id": flight_id,
            "series": hist_svc.series_10hz(flight_id, cols, max_points=max_points),
        }
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e


@router.get("/export/{flight_id}")
def export_flight_csv(flight_id: str):
    try:
        rows, fieldnames = hist_svc.export_10hz_csv_rows(flight_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e

    def generate():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames)
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for row in rows:
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
