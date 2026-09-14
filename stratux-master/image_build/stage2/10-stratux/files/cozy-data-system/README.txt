Cozy Aircraft Data System — on-aircraft data directory
======================================================

/cozy-data-system/
    web/                  FastAPI UI (:8080)
    historian/            FIX capture → SQLite
    fix_gateway_plugins/  cozy_stratux_http, cozy_mgl_*
    config/               FIX, historian, systemd, udev
    scripts/              setup_*, persist_cozy_to_robase.sh
    navigation/           AvPlan → MGL plan conversion
    hardware/             Nano Airtalk firmware, etc.
    data/
        flight-plans/     AvPlan / MGL plan exchange (SMB)
        historian/        durable SQLite (bind-mounted from robase)
        mgl-inbox/        ENIGMA_LATEST / XTFLIGHT_LATEST

A rebuilt Stratux image copies this tree from files/cozy-payload (see
scripts/sync_cozy_into_stratux_image.sh). Python venv is installed after
flash with setup_fix_gateway.sh + setup_cozy_web.sh.

SMB (Wi‑Fi): smb://192.168.10.1/cozy-data  user pi
Web: http://192.168.10.1:8080/live
