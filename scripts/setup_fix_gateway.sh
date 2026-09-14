#!/bin/bash
# Offline install of MakerPlane FIX-Gateway onto a Stratux Pi.
#
# IMPORTANT: Stratux uses a 250MB overlay. Always install into /overlay/robase
# (unlock first). Do NOT create /cozy-data-system on the upper overlay layer
# or it can shadow the lower install until reboot.
#
# Usage (on Pi as root/sudo):
#   sudo ./setup_fix_gateway.sh /tmp/fixgw-wheels
#
# Prefs/unit can also be staged as:
#   /tmp/preferences.yaml.custom
#   /tmp/fixgateway.service

set -euo pipefail

COZY_ROOT=/cozy-data-system
VENV="${COZY_ROOT}/venv"
CFG="${COZY_ROOT}/config/fixgw"
WHEELS="${1:-/tmp/fixgw-wheels}"
PREF_SRC="${2:-/tmp/preferences.yaml.custom}"
SERVICE_UNIT=/etc/systemd/system/fixgateway.service

if [ ! -d "${WHEELS}" ]; then
  echo "ERROR: wheels directory not found: ${WHEELS}"
  exit 1
fi

overlay_is_active() {
  [ -d /overlay/robase/overlay ]
}

ROOT=""
if overlay_is_active; then
  overlayctl unlock
  ROOT=/overlay/robase
fi

echo "=== Installing FIX-Gateway into ${ROOT}${COZY_ROOT} ==="
mkdir -p "${ROOT}${COZY_ROOT}/config" \
         "${ROOT}${COZY_ROOT}/data/flight-plans" \
         "${ROOT}${COZY_ROOT}/fix_gateway_plugins"

if [ ! -x "${ROOT}${VENV}/bin/python" ]; then
  python3 -m venv "${ROOT}${VENV}"
fi

PIP="${ROOT}${VENV}/bin/pip"
"${PIP}" install --no-index --find-links="${WHEELS}" -U pip setuptools wheel || true
"${PIP}" install --no-index --find-links="${WHEELS}" \
  pyyaml lockfile daemon pyserial psutil "python-can==4.6.1" python-canfix \
  pynmea2 pymavlink numpy py-gpsd2 packaging typing_extensions future lxml
"${PIP}" install --no-index --find-links="${WHEELS}" --no-deps fixgw

"${ROOT}${VENV}/bin/python" - <<PY
import shutil
from pathlib import Path
import fixgw
cfg = Path("${ROOT}${CFG}")
pkg = Path(fixgw.__file__).resolve().parent / "config"
cfg.mkdir(parents=True, exist_ok=True)
for item in pkg.iterdir():
    dest = cfg / item.name
    if item.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(item, dest)
    else:
        shutil.copy2(item, dest)
print("seeded", cfg, "version", fixgw.__version__)
PY

# Overlay Cozy FIX keys/connections (do not let the stock seed wipe them).
THIS="$(cd "$(dirname "$0")" && pwd)"
OVERLAY_FIXGW="$(cd "${THIS}/.." && pwd)/config/fixgw"
if [ -d "${OVERLAY_FIXGW}" ]; then
  rsync -a --exclude 'default.yaml' "${OVERLAY_FIXGW}/" "${ROOT}${CFG}/"
  if [ -f "${THIS}/ensure_mgl_airtalk_include.py" ]; then
    python3 "${THIS}/ensure_mgl_airtalk_include.py" "${ROOT}${CFG}/default.yaml" || true
  fi
fi

if [ -f "${PREF_SRC}" ]; then
  install -m 644 "${PREF_SRC}" "${ROOT}${CFG}/preferences.yaml.custom"
fi
chown -R pi:pi "${ROOT}${COZY_ROOT}"

mkdir -p "${ROOT}/etc/systemd/system"
cat >"${ROOT}${SERVICE_UNIT}" <<'EOF'
[Unit]
Description=FIX-Gateway (Cozy Aircraft Data System)
After=network-online.target stratux.service
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/cozy-data-system
Environment=HOME=/home/pi
Environment=PYTHONPATH=/cozy-data-system/fix_gateway_plugins:/cozy-data-system
ExecStart=/cozy-data-system/venv/bin/fixgw --config-file=/cozy-data-system/config/fixgw/default.yaml
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Avoid empty upper-layer unit shadowing robase
rm -f /overlay/rwdata/data/etc/systemd/system/fixgateway.service 2>/dev/null || true
cp "${ROOT}${SERVICE_UNIT}" "${SERVICE_UNIT}"

if overlay_is_active; then
  mkdir -p "${ROOT}/etc/systemd/system/multi-user.target.wants"
  ln -sfn "${SERVICE_UNIT}" "${ROOT}/etc/systemd/system/multi-user.target.wants/fixgateway.service"
  overlayctl lock || true
  echo "NOTE: if /cozy-data-system/venv is missing in the live view, reboot once."
fi

systemctl daemon-reload
systemctl unmask fixgateway.service 2>/dev/null || true
systemctl enable fixgateway.service
systemctl restart fixgateway.service
sleep 2
systemctl --no-pager --full status fixgateway.service || true
ss -tlnp | grep 3490 || true
echo
echo "FIX-Gateway NetFIX port: 3490"
echo "Config: ${CFG}"
echo "Client: ${VENV}/bin/fixgwc"
