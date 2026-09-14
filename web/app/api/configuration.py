"""GET /api/configuration — aircraft + Wi-Fi + system config (read-only)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from historian.database.repository import HistorianDB, load_yaml
from web.app.services import wifi as wifi_svc

router = APIRouter(prefix="/api", tags=["configuration"])

HISTORIAN_YAML = Path("/cozy-data-system/config/historian/historian.yaml")
AIRCRAFT_YAML = Path("/cozy-data-system/config/historian/aircraft.yaml")


def _aircraft_block() -> dict:
    if not AIRCRAFT_YAML.exists():
        return {"ok": False, "error": f"missing {AIRCRAFT_YAML}"}
    data = load_yaml(AIRCRAFT_YAML)
    return {"ok": True, "aircraft": data.get("aircraft"), "configuration": data.get("configuration")}


def _historian_signals() -> dict:
    if not HISTORIAN_YAML.exists():
        return {"ok": False}
    hist = (load_yaml(HISTORIAN_YAML).get("historian") or {})
    return {
        "ok": True,
        "fast_rate_hz": hist.get("fast_rate_hz"),
        "slow_rate_hz": hist.get("slow_rate_hz"),
        "fast_signals": hist.get("fast_signals") or {},
        "slow_signals": hist.get("slow_signals") or {},
        "fix": hist.get("fix") or {},
        "control_socket": hist.get("control_socket"),
        "database_path": hist.get("database_path"),
    }


def _db_config_items() -> list:
    try:
        db = HistorianDB.from_config_files(HISTORIAN_YAML, AIRCRAFT_YAML)
        acfg = (load_yaml(AIRCRAFT_YAML).get("configuration") or {})
        cid = acfg.get("configuration_id")
        if not cid:
            return []
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT category, item, value, units, notes
                FROM configuration_item
                WHERE configuration_id=?
                ORDER BY category, item
                """,
                (cid,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


@router.get("/configuration")
def get_configuration():
    return {
        "ok": True,
        "aircraft": _aircraft_block(),
        "configuration_items": _db_config_items(),
        "historian_signals": _historian_signals(),
        "wifi": wifi_svc.wifi_configuration(),
    }
