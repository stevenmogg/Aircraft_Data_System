#!/bin/bash
# MCP2515 SocketCAN bring-up for the Cozy MGL bus (Stage 0 / 1).
#
# Usage (on Pi as root, or via ssh):
#   sudo ./scripts/setup_can0.sh --status
#   sudo ./scripts/setup_can0.sh --probe-overlay
#   sudo ./scripts/setup_can0.sh --install     # writes config.txt (reboot required)
#   sudo ./scripts/setup_can0.sh --up          # ip link listen-only 250 kbit/s
#   sudo ./scripts/setup_can0.sh --up-tx       # same bitrate, listen-only off (T14 / Autopilot install)
#
# Do not --install until `dmesg` shows: MCP2515 successfully initialized.
#
set -euo pipefail

CONFIG="${BOOT_CONFIG:-/boot/firmware/config.txt}"
MARKER_BEGIN="# --- cozy mcp2515 can0 (begin) ---"
MARKER_END="# --- cozy mcp2515 can0 (end) ---"
OSC="${COZY_MCP_OSC:-8000000}"
INT_GPIO="${COZY_MCP_INT:-25}"
# Default SPI clock is too fast for this harness/level shift; 500 kHz probes cleanly.
SPI_MAX="${COZY_MCP_SPI_MAX:-500000}"
CHANNEL="${COZY_CAN_CHANNEL:-can0}"
BITRATE="${COZY_CAN_BITRATE:-250000}"

MODE="status"
case "${1:-}" in
  --status|"") MODE=status ;;
  --probe-overlay) MODE=probe ;;
  --install) MODE=install ;;
  --up) MODE=up ;;
  --up-tx) MODE=uptx ;;
  --help|-h) MODE=help ;;
  *) echo "usage: $0 [--status|--probe-overlay|--install|--up|--up-tx]"; exit 1 ;;
esac

log() { echo "can0: $*"; }

show_status() {
  echo "=== $CHANNEL ==="
  ip -details -s link show "$CHANNEL" 2>&1 || echo "  (missing)"
  echo
  echo "=== overlays ==="
  dtoverlay -l 2>/dev/null || true
  echo
  echo "=== dmesg mcp251x ==="
  dmesg | grep -iE "mcp251|can0" | tail -20 || true
  echo
  echo "=== config.txt mcp lines ==="
  if [ -f "$CONFIG" ]; then
    grep -nE "mcp2515|cozy mcp2515" "$CONFIG" || echo "  (none)"
  fi
}

probe_overlay() {
  if ip link show "$CHANNEL" >/dev/null 2>&1; then
    log "$CHANNEL already exists"
    show_status
    return 0
  fi
  log "loading mcp2515-can0 oscillator=$OSC interrupt=$INT_GPIO spimaxfrequency=$SPI_MAX"
  dtoverlay mcp2515-can0 "oscillator=$OSC" "interrupt=$INT_GPIO" "spimaxfrequency=$SPI_MAX" || true
  sleep 1
  dmesg | grep -iE "mcp251" | tail -10
  if ip link show "$CHANNEL" >/dev/null 2>&1; then
    log "PASS: $CHANNEL appeared"
    return 0
  fi
  log "FAIL: kernel did not create $CHANNEL (SPI probe timeout is wiring/power, not bitrate)"
  return 1
}

install_overlay() {
  [ -f "$CONFIG" ] || { echo "missing $CONFIG"; exit 1; }
  local block
  block=$(cat <<EOF
$MARKER_BEGIN
# MCP2515 on SPI0 CE0. Confirm INT GPIO and crystal before relying on this.
dtparam=spi=on
dtoverlay=mcp2515-can0,oscillator=${OSC},interrupt=${INT_GPIO},spimaxfrequency=${SPI_MAX}
$MARKER_END
EOF
)
  if grep -q "$MARKER_BEGIN" "$CONFIG"; then
    log "replacing existing cozy mcp2515 block in $CONFIG"
    awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" -v repl="$block" '
      $0==b {print repl; skip=1; next}
      skip && $0==e {skip=0; next}
      !skip {print}
    ' "$CONFIG" >"${CONFIG}.new"
    mv "${CONFIG}.new" "$CONFIG"
  else
    log "appending cozy mcp2515 block to $CONFIG"
    printf "\n%s\n" "$block" >>"$CONFIG"
  fi
  grep -A5 "$MARKER_BEGIN" "$CONFIG"
  log "reboot required for a durable overlay"
}

bring_up() {
  if ! ip link show "$CHANNEL" >/dev/null 2>&1; then
    log "FAIL: $CHANNEL missing — run --probe-overlay or --install + reboot first"
    return 1
  fi
  ip link set "$CHANNEL" down || true
  if ip link set "$CHANNEL" up type can bitrate "$BITRATE" listen-only on; then
    log "UP $CHANNEL bitrate=$BITRATE listen-only=on"
  else
    log "listen-only failed; bringing up without it"
    ip link set "$CHANNEL" up type can bitrate "$BITRATE"
  fi
  ip -details -s link show "$CHANNEL"
}

bring_up_tx() {
  if ! ip link show "$CHANNEL" >/dev/null 2>&1; then
    log "FAIL: $CHANNEL missing — run --probe-overlay or --install + reboot first"
    return 1
  fi
  ip link set "$CHANNEL" down || true
  ip link set "$CHANNEL" type can bitrate "$BITRATE" listen-only off
  ip link set "$CHANNEL" up
  log "UP $CHANNEL bitrate=$BITRATE listen-only=off"
  ip -details -s link show "$CHANNEL"
}

case "$MODE" in
  help)
    sed -n '2,12p' "$0"
    ;;
  status) show_status ;;
  probe) probe_overlay ;;
  install) install_overlay ;;
  up) bring_up ;;
  uptx) bring_up_tx ;;
esac
