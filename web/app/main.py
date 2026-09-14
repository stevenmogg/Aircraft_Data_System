from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cozy Aircraft Web",
        description="Aircraft-local UI for FIX live data and Historian flights",
        version="0.1.0",
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from web.app.api import configuration as configuration_api
    from web.app.api import events as events_api
    from web.app.api import exports as exports_api
    from web.app.api import external_data as external_data_api
    from web.app.api import flights as flights_api
    from web.app.api import historian_ctrl as historian_api
    from web.app.api import mgl_airtalk as mgl_airtalk_api
    from web.app.api import mgl_can as mgl_can_api
    from web.app.api import mgl_nmea as mgl_nmea_api
    from web.app.api import mgl_servo as mgl_servo_api
    from web.app.api import pages as pages_api
    from web.app.api import status as status_api
    from web.app.websocket import live as live_ws
    from web.app.websocket import mgl_airtalk as mgl_airtalk_ws
    from web.app.websocket import mgl_can as mgl_can_ws
    from web.app.websocket import mgl_nmea as mgl_nmea_ws

    app.include_router(status_api.router)
    app.include_router(configuration_api.router)
    app.include_router(external_data_api.router)
    app.include_router(flights_api.router)
    app.include_router(historian_api.router)
    app.include_router(events_api.router)
    app.include_router(exports_api.router)
    app.include_router(mgl_can_api.router)
    app.include_router(mgl_airtalk_api.router)
    app.include_router(mgl_nmea_api.router)
    app.include_router(mgl_servo_api.router)
    app.include_router(pages_api.router)
    app.include_router(live_ws.router)
    app.include_router(mgl_can_ws.router)
    app.include_router(mgl_airtalk_ws.router)
    app.include_router(mgl_nmea_ws.router)

    @app.on_event("startup")
    def _start_monitors() -> None:
        import os

        from web.app.services.can_monitor import get_monitor as get_can

        get_can().start()
        from web.app.services.nmea_monitor import get_monitor as get_nmea

        get_nmea().start()
        # FIX-Gateway cozy_mgl_airtalk owns the Nano USB port. Opt in to the
        # web reader only for bench work (must stop fixgateway first).
        if os.environ.get("COZY_AIRTALK_WEB_SERIAL", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            from web.app.services.airtalk_monitor import get_monitor as get_airtalk

            get_airtalk().start()

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "cozy-web"}

    return app


app = create_app()
