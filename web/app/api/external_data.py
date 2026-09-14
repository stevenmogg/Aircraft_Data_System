"""REST: external data exchange (MGL card inbox / sync status)."""

from __future__ import annotations

from fastapi import APIRouter

from web.app.services import external_data as ext_svc

router = APIRouter(prefix="/api", tags=["external-data"])


@router.get("/external-data")
def get_external_data():
    try:
        return ext_svc.external_data_status()
    except Exception as e:
        return {
            "ok": False,
            "collection_state": "idle_last_failed",
            "installed": False,
            "card_mounted": False,
            "last_sync": {"ok": False, "error": str(e)},
            "flight_plans_on_pi": [],
            "flight_plans_count": 0,
            "error": str(e),
        }
