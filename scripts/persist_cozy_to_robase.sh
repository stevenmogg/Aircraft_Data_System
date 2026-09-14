#!/bin/bash
# Copy /cozy-data-system (minus venv and historian DB) onto Stratux robase
# so overlay tmpfs edits survive reboot. Safe when overlayctl unlock is busy:
# this image already has /overlay/robase mounted read-write.
#
# Usage (on the Pi as root):
#   sudo ./scripts/persist_cozy_to_robase.sh
#   sudo ./scripts/persist_cozy_to_robase.sh /cozy-data-system /overlay/robase/cozy-data-system
set -euo pipefail

SRC="${1:-/cozy-data-system}"
DST="${2:-/overlay/robase/cozy-data-system}"

if [ ! -d "${SRC}/web" ]; then
  echo "ERROR: ${SRC} is not a Cozy tree" >&2
  exit 1
fi
if [ ! -d /overlay/robase ]; then
  echo "ERROR: /overlay/robase missing" >&2
  exit 1
fi

mkdir -p "${DST}"
rsync -a --delete \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude 'data/historian/*.sqlite' \
  --exclude 'data/historian/*.sqlite-journal' \
  --exclude 'data/mgl-inbox/*' \
  "${SRC}/" "${DST}/"

# Keep an existing venv on robase; do not delete it with --delete above (excluded).
if [ -d "${SRC}/venv" ] && [ ! -d "${DST}/venv" ]; then
  echo "NOTE: venv exists on live tree only; copy separately if you need it on robase"
fi

chown -R pi:pi "${DST}" 2>/dev/null || true
echo "persisted ${SRC} -> ${DST}"
df -h /overlay/robase | tail -1
