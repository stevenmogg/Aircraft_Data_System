#!/bin/bash
# Copy Cozy runtime source into the Stratux pi-gen stage so a new SD image
# boots with /cozy-data-system already populated (venv still installed later).
#
# Usage (from the Mac repo):
#   ./scripts/sync_cozy_into_stratux_image.sh
#   ./scripts/sync_cozy_into_stratux_image.sh /path/to/Cozy_repo /path/to/stage2/10-stratux
#
# image_build/build.sh calls this automatically when the Cozy repo is the parent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COZY_ROOT="${1:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
STAGE="${2:-${COZY_ROOT}/stratux-master/image_build/stage2/10-stratux}"
DEST="${STAGE}/files/cozy-payload"

if [ ! -d "${COZY_ROOT}/web" ] || [ ! -d "${COZY_ROOT}/config" ]; then
  echo "ERROR: ${COZY_ROOT} does not look like the Cozy repo (need web/ and config/)" >&2
  exit 1
fi
if [ ! -d "${STAGE}/files" ]; then
  echo "ERROR: Stratux stage not found: ${STAGE}" >&2
  exit 1
fi

echo "=== Staging Cozy payload -> ${DEST} ==="
mkdir -p "${DEST}"

RSYNC=(rsync -a
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.pytest_cache'
  --exclude 'venv'
  --exclude '*.sqlite'
  --exclude '*.sqlite-journal'
  --exclude '.DS_Store')

"${RSYNC[@]}" "${COZY_ROOT}/web/" "${DEST}/web/"
"${RSYNC[@]}" "${COZY_ROOT}/historian/" "${DEST}/historian/"
"${RSYNC[@]}" "${COZY_ROOT}/fix_gateway_plugins/" "${DEST}/fix_gateway_plugins/"
"${RSYNC[@]}" "${COZY_ROOT}/config/" "${DEST}/config/"
"${RSYNC[@]}" "${COZY_ROOT}/scripts/" "${DEST}/scripts/"
if [ -d "${COZY_ROOT}/navigation" ]; then
  "${RSYNC[@]}" "${COZY_ROOT}/navigation/" "${DEST}/navigation/"
fi
if [ -d "${COZY_ROOT}/hardware" ]; then
  "${RSYNC[@]}" "${COZY_ROOT}/hardware/" "${DEST}/hardware/"
fi

mkdir -p "${DEST}/data/flight-plans" "${DEST}/data/historian" "${DEST}/data/mgl-inbox"
touch "${DEST}/data/flight-plans/.gitkeep"

cat > "${DEST}/README.txt" <<'EOF'
Cozy Aircraft Data System — baked into the Stratux image
========================================================

This tree is copied to /cozy-data-system at image-build time.

After first flash, create the Python venv (offline wheels) and enable services:

  sudo /cozy-data-system/scripts/setup_fix_gateway.sh /tmp/fixgw-wheels
  sudo /cozy-data-system/scripts/setup_cozy_web.sh /cozy-data-system
  sudo /cozy-data-system/scripts/setup_historian_step0_1.sh

FIX stores aircraft units at ingest (feet, °F). See doco/fix_gateway_install.md.
EOF

chmod +x "${DEST}/scripts/"*.sh "${DEST}/scripts/"*.py 2>/dev/null || true
echo "staged $(du -sh "${DEST}" | awk '{print $1}')"
