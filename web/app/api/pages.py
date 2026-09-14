"""HTML page routes (Jinja)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.app.templating import TEMPLATES

router = APIRouter(tags=["pages"])


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/live", status_code=302)


@router.get("/live", response_class=HTMLResponse)
def live_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "live.html", {"active": "live"})


@router.get("/flights", response_class=HTMLResponse)
def flights_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "flights.html", {"active": "flights"})


@router.get("/flights/{flight_id}", response_class=HTMLResponse)
def flight_detail_page(request: Request, flight_id: str):
    return TEMPLATES.TemplateResponse(
        request,
        "flight_detail.html",
        {"active": "flights", "flight_id": flight_id},
    )


@router.get("/status", response_class=HTMLResponse)
def status_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "status.html", {"active": "status"})


@router.get("/configuration", response_class=HTMLResponse)
def configuration_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "configuration.html", {"active": "configuration"}
    )


@router.get("/analysis", response_class=HTMLResponse)
def analysis_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "analysis.html", {"active": "analysis"})


@router.get("/debug/mgl", include_in_schema=False)
def mgl_hub():
    return RedirectResponse(url="/debug/mgl/can", status_code=302)


@router.get("/debug/mgl/can", response_class=HTMLResponse)
def mgl_can_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "mgl_can.html", {"active": "mgl", "mgl_tab": "can"}
    )


@router.get("/debug/mgl/airtalk", response_class=HTMLResponse)
def mgl_airtalk_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "mgl_airtalk.html", {"active": "mgl", "mgl_tab": "airtalk"}
    )


@router.get("/debug/mgl/gps", response_class=HTMLResponse)
def mgl_gps_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "mgl_nmea.html", {"active": "mgl", "mgl_tab": "gps"}
    )


@router.get("/debug/mgl/autopilot", response_class=HTMLResponse)
def mgl_autopilot_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "mgl_autopilot.html", {"active": "mgl", "mgl_tab": "autopilot"}
    )


@router.get("/debug/mgl-can", include_in_schema=False)
def mgl_can_legacy():
    return RedirectResponse(url="/debug/mgl/can", status_code=302)


@router.get("/debug/mgl-airtalk", include_in_schema=False)
def mgl_airtalk_legacy():
    return RedirectResponse(url="/debug/mgl/airtalk", status_code=302)
