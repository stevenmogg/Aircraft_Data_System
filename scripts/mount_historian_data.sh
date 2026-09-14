#!/bin/bash
# Mount durable Historian data from Stratux robase onto /cozy-data-system/data/historian.
#
# Stratux root overlay is a 250MB tmpfs. Flight SQLite must live on the SD card
# (robase). This script remounts robase RW and bind-mounts the durable directory.
#
# Safe to run repeatedly. Intended as a boot oneshot (cozy-historian-data.service).

set -euo pipefail

DST=/cozy-data-system/data/historian
ROBASE=/overlay/robase
SRC="${ROBASE}${DST}"

overlay_active() {
  [ -d /overlay/robase/overlay ]
}

if overlay_active; then
  # Leave robase RW so SQLite writes through the bind mount persist on disk.
  mount -o remount,rw "${ROBASE}"
  mkdir -p "${SRC}"
  chown pi:pi "${SRC}" 2>/dev/null || true
  mkdir -p "${DST}"
  if ! mountpoint -q "${DST}"; then
    mount --bind "${SRC}" "${DST}"
  fi
  # Ensure nested flight tree exists on durable storage
  mkdir -p "${DST}/aircraft"
  chown -R pi:pi "${DST}"
  echo "historian data: bind ${SRC} -> ${DST} (robase RW)"
else
  mkdir -p "${DST}/aircraft"
  chown -R pi:pi "${DST}"
  echo "historian data: overlay inactive; using ${DST} directly"
fi

# Sanity: must not be on the tiny overlay upper alone when overlay is active
if overlay_active; then
  if ! mountpoint -q "${DST}"; then
    echo "ERROR: ${DST} is not a mountpoint after bind" >&2
    exit 1
  fi
fi
exit 0
