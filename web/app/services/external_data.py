"""External data exchange status (MGL SD card, inbox)."""

from __future__ import annotations

import json
import os
from pathlib import Path

MGL_STATUS = Path("/cozy-data-system/data/mgl-inbox/last_sync.json")
INBOX_ENIGMA = Path("/cozy-data-system/data/mgl-inbox/enigma")
INBOX_XT = Path("/cozy-data-system/data/mgl-inbox/xtflight")
FLIGHT_PLANS = Path("/cozy-data-system/data/flight-plans")
MOUNT_POINT = Path("/media/cozy-mgl")
SYNC_SCRIPT = Path("/cozy-data-system/scripts/mgl_card_sync.sh")
UDEV_RULE = Path("/etc/udev/rules.d/99-cozy-mgl-card.rules")


def _list_files(directory: Path, limit: int = 8) -> list[dict]:
    if not directory.is_dir():
        return []
    files = []
    for p in sorted(directory.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name.endswith(".sha256"):
            continue
        try:
            st = p.stat()
            files.append(
                {
                    "name": p.name,
                    "bytes": st.st_size,
                    "mtime_utc": int(st.st_mtime),
                }
            )
        except OSError:
            continue
        if len(files) >= limit:
            break
    return files


def _is_mountpoint(path: Path) -> bool:
    try:
        return path.is_dir() and os.path.ismount(str(path))
    except OSError:
        return False


def external_data_status() -> dict:
    last_sync = None
    if MGL_STATUS.is_file():
        try:
            last_sync = json.loads(MGL_STATUS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            last_sync = {"ok": False, "error": str(e)}

    plans = []
    if FLIGHT_PLANS.is_dir():
        plans = sorted(
            p.name
            for p in FLIGHT_PLANS.iterdir()
            if p.is_file() and not p.name.startswith(".")
        )

    mounted = _is_mountpoint(MOUNT_POINT)
    card_files: list[str] = []
    if mounted:
        try:
            card_files = sorted(
                p.name
                for p in MOUNT_POINT.iterdir()
                if p.is_file() and not p.name.startswith(".") and not p.name.startswith("._")
            )
        except OSError:
            card_files = []

    enigma = _list_files(INBOX_ENIGMA)
    xtflight = _list_files(INBOX_XT)

    enigma_latest = INBOX_ENIGMA / "ENIGMA_LATEST.REC"
    enigma_processed = INBOX_ENIGMA / "ENIGMA_PROCESSED.REC"
    xt_latest = INBOX_XT / "XTFLIGHT_LATEST.CSV"
    xt_processed = INBOX_XT / "XTFLIGHT_PROCESSED.CSV"

    sync_ok = bool(last_sync and last_sync.get("ok"))
    installed = SYNC_SCRIPT.is_file() and UDEV_RULE.is_file()

    if mounted:
        collection_state = "card_mounted"
    elif sync_ok:
        collection_state = "idle_last_ok"
    elif last_sync is not None:
        collection_state = "idle_last_failed"
    elif installed:
        collection_state = "ready_no_sync_yet"
    else:
        collection_state = "not_installed"

    if enigma_latest.is_file():
        import_enigma = "pending"
    elif enigma_processed.is_file():
        import_enigma = "processed"
    else:
        import_enigma = (last_sync or {}).get("import_enigma", "none")

    return {
        "ok": True,
        "collection_state": collection_state,
        "installed": installed,
        "card_mounted": mounted,
        "mount_point": str(MOUNT_POINT),
        "last_sync": last_sync,
        "flight_plans_on_pi": plans,
        "flight_plans_count": len(plans),
        "card_root_files": card_files,
        "inbox": {
            "enigma": enigma,
            "xtflight": xtflight,
            "enigma_latest": enigma_latest.is_file(),
            "enigma_processed": enigma_processed.is_file(),
            "xtflight_latest": xt_latest.is_file(),
            "xtflight_processed": xt_processed.is_file(),
            "enigma_count": len(enigma),
            "xtflight_count": len(xtflight),
        },
        "import_enigma": import_enigma,
        "paths": {
            "flight_plans": str(FLIGHT_PLANS),
            "inbox_enigma": str(INBOX_ENIGMA),
            "inbox_xtflight": str(INBOX_XT),
            "status_file": str(MGL_STATUS),
        },
    }
