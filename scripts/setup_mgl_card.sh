#!/bin/bash
# Install MGL card sync (udev + script + dirs) onto Stratux Pi.
set -euo pipefail
SRC_ROOT="${1:-}"
if [ -z "$SRC_ROOT" ]; then
  SRC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi
COZY=/cozy-data-system

overlay_active() { [ -d /overlay/robase/overlay ]; }
ROOT=""
if overlay_active; then
  overlayctl unlock
  ROOT=/overlay/robase
fi

echo "=== Installing MGL card sync into ${ROOT:-/}$COZY ==="
mkdir -p "${ROOT}${COZY}/scripts" \
         "${ROOT}${COZY}/config/mgl_card" \
         "${ROOT}${COZY}/data/mgl-inbox/enigma" \
         "${ROOT}${COZY}/data/mgl-inbox/xtflight" \
         "${ROOT}${COZY}/data/flight-plans" \
         "${ROOT}/etc/udev/rules.d" \
         "${ROOT}/etc/systemd/system" \
         /media/cozy-mgl

install -m 755 "${SRC_ROOT}/scripts/mgl_card_sync.sh" "${ROOT}${COZY}/scripts/mgl_card_sync.sh"
install -m 644 "${SRC_ROOT}/config/mgl_card/mgl_card.yaml" "${ROOT}${COZY}/config/mgl_card/mgl_card.yaml"
mkdir -p "${ROOT}${COZY}/navigation"
install -m 644 "${SRC_ROOT}/navigation/avplan_to_mgl.py" "${ROOT}${COZY}/navigation/avplan_to_mgl.py"
install -m 644 "${SRC_ROOT}/navigation/__init__.py" "${ROOT}${COZY}/navigation/__init__.py"
install -m 644 "${SRC_ROOT}/config/udev/99-cozy-mgl-card.rules" "${ROOT}/etc/udev/rules.d/99-cozy-mgl-card.rules"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-card@.service" "${ROOT}/etc/systemd/system/cozy-mgl-card@.service"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-card-release@.service" "${ROOT}/etc/systemd/system/cozy-mgl-card-release@.service"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-plans.service" "${ROOT}/etc/systemd/system/cozy-mgl-plans.service"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-plans.path" "${ROOT}/etc/systemd/system/cozy-mgl-plans.path"

# Live copies
install -m 755 "${SRC_ROOT}/scripts/mgl_card_sync.sh" "${COZY}/scripts/mgl_card_sync.sh"
install -m 644 "${SRC_ROOT}/config/mgl_card/mgl_card.yaml" "${COZY}/config/mgl_card/mgl_card.yaml"
mkdir -p "${COZY}/navigation"
install -m 644 "${SRC_ROOT}/navigation/avplan_to_mgl.py" "${COZY}/navigation/avplan_to_mgl.py"
install -m 644 "${SRC_ROOT}/navigation/__init__.py" "${COZY}/navigation/__init__.py"
install -m 644 "${SRC_ROOT}/config/udev/99-cozy-mgl-card.rules" /etc/udev/rules.d/99-cozy-mgl-card.rules
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-card@.service" /etc/systemd/system/cozy-mgl-card@.service
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-card-release@.service" /etc/systemd/system/cozy-mgl-card-release@.service
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-plans.service" /etc/systemd/system/cozy-mgl-plans.service
install -m 644 "${SRC_ROOT}/config/systemd/cozy-mgl-plans.path" /etc/systemd/system/cozy-mgl-plans.path

chown -R pi:pi "${ROOT}${COZY}/data/mgl-inbox" "${ROOT}${COZY}/data/flight-plans" \
  "${COZY}/data/mgl-inbox" "${COZY}/data/flight-plans" 2>/dev/null || true

udevadm control --reload
udevadm trigger --subsystem-match=block || true
systemctl daemon-reload
systemctl enable --now cozy-mgl-plans.path

echo "=== Installed. Insert card to auto-sync; flight-plans folder also watched. ==="
