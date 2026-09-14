#!/bin/bash
# Install Cozy Web UI (FastAPI) into Stratux robase + enable cozy-web.service
#
# Usage:
#   sudo ./scripts/setup_cozy_web.sh /path/to/repo [/path/to/wheels]

set -euo pipefail

SRC_ROOT="${1:-}"
WHEELS="${2:-/tmp/cozy-web-wheels}"
if [ -z "${SRC_ROOT}" ]; then
  SRC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

COZY=/cozy-data-system
SERVICE=/etc/systemd/system/cozy-web.service

overlay_active() { [ -d /overlay/robase/overlay ]; }

ROOT=""
if overlay_active; then
  overlayctl unlock
  ROOT=/overlay/robase
fi

echo "=== Installing Cozy Web into ${ROOT}${COZY} ==="
mkdir -p "${ROOT}${COZY}/web" \
         "${ROOT}${COZY}/config/systemd" \
         "${ROOT}/etc/systemd/system"

rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
  "${SRC_ROOT}/web/" "${ROOT}${COZY}/web/"

if [ -d "${WHEELS}" ]; then
  "${ROOT}${COZY}/venv/bin/pip" install --no-index --find-links="${WHEELS}" \
    fastapi 'uvicorn[standard]' jinja2 python-multipart websockets pyserial
else
  echo "WARNING: no wheels dir ${WHEELS}; assuming deps already installed"
fi

install -m 644 "${SRC_ROOT}/config/systemd/cozy-web.service" "${ROOT}${SERVICE}"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-web.service" "${SERVICE}"

# Live tree mirror when overlay active
if [ -n "${ROOT}" ]; then
  mkdir -p "${COZY}/web"
  rsync -a --delete --exclude '__pycache__' "${ROOT}${COZY}/web/" "${COZY}/web/" || true
fi

chown -R pi:pi "${ROOT}${COZY}/web" 2>/dev/null || true

systemctl daemon-reload
systemctl enable cozy-web.service
if [ -n "${ROOT}" ]; then
  mkdir -p "${ROOT}/etc/systemd/system/multi-user.target.wants"
  ln -sfn "${SERVICE}" "${ROOT}/etc/systemd/system/multi-user.target.wants/cozy-web.service"
  overlayctl lock || true
fi
systemctl restart cozy-web.service
sleep 2
systemctl is-active cozy-web
curl -sS http://127.0.0.1:8080/api/health || true
echo
curl -sS http://127.0.0.1:8080/api/status | head -c 800 || true
echo
echo "=== Cozy Web Step 1 installed (port 8080) ==="
