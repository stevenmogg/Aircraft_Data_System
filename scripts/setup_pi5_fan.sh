#!/bin/bash
# Configure Raspberry Pi 5 onboard FAN header thermal regulation.
#
# Usage:
#   sudo ./scripts/setup_pi5_fan.sh           # install curve + disable Stratux GPIO fancontrol
#   sudo ./scripts/setup_pi5_fan.sh --test    # spin fan through cooling levels (no reboot)
#   sudo ./scripts/setup_pi5_fan.sh --status  # show temp / fan state
#
set -euo pipefail

CONFIG="${BOOT_CONFIG:-/boot/firmware/config.txt}"
MARKER_BEGIN="# --- cozy pi5 fan cooling (begin) ---"
MARKER_END="# --- cozy pi5 fan cooling (end) ---"

MODE="install"
case "${1:-}" in
  --test) MODE=test; shift || true ;;
  --status) MODE=status; shift || true ;;
  --install|"") MODE=install ;;
  *) echo "usage: $0 [--install|--test|--status]"; exit 1 ;;
esac

log() { echo "pi5-fan: $*"; }

find_cooling_device() {
  local d typ
  for d in /sys/class/thermal/cooling_device*; do
    [ -e "$d/type" ] || continue
    typ=$(cat "$d/type" 2>/dev/null || true)
    case "$typ" in
      *fan*|*pwm*|*Fan*|*PWM*) echo "$d"; return 0 ;;
    esac
  done
  if [ -e /sys/class/thermal/cooling_device0/cur_state ]; then
    echo /sys/class/thermal/cooling_device0
    return 0
  fi
  return 1
}

show_status() {
  echo "=== CPU temperature ==="
  if command -v vcgencmd >/dev/null 2>&1; then
    vcgencmd measure_temp || true
  fi
  for t in /sys/class/thermal/thermal_zone*; do
    [ -e "$t/temp" ] || continue
    typ=$(cat "$t/type" 2>/dev/null || echo "?")
    millideg=$(cat "$t/temp" 2>/dev/null || echo 0)
    awk -v m="$millideg" -v n="$typ" 'BEGIN{printf "  %s: %.1f C\n", n, m/1000.0}'
  done

  echo "=== cooling devices ==="
  local any=0
  for d in /sys/class/thermal/cooling_device*; do
    [ -e "$d/type" ] || continue
    any=1
    echo "  $(basename "$d") type=$(cat "$d/type") cur=$(cat "$d/cur_state") max=$(cat "$d/max_state")"
  done
  [ "$any" -eq 1 ] || echo "  (none — reboot after install, or fan not detected)"

  echo "=== hwmon fan/pwm ==="
  for h in /sys/class/hwmon/hwmon*; do
    [ -e "$h/name" ] || continue
    name=$(cat "$h/name")
    case "$name" in
      *fan*|*pwm*|cpu_thermal|rp1*)
        echo "  $h ($name)"
        for f in "$h"/fan*_input "$h"/pwm1 "$h"/pwm1_enable; do
          [ -e "$f" ] && echo "    $(basename "$f")=$(cat "$f" 2>/dev/null)"
        done
        ;;
    esac
  done

  echo "=== config.txt fan lines ==="
  if [ -f "$CONFIG" ]; then
    grep -E "fan_temp|cozy pi5 fan" "$CONFIG" 2>/dev/null || echo "  (none installed yet)"
  fi

  echo "=== Stratux GPIO fancontrol ==="
  if systemctl list-unit-files 2>/dev/null | grep -q '^stratux_fancontrol.service'; then
    echo "  active=$(systemctl is-active stratux_fancontrol.service 2>/dev/null || true)"
    echo "  enabled=$(systemctl is-enabled stratux_fancontrol.service 2>/dev/null || true)"
    echo "  (should be disabled — it drives BCM18, not the Pi 5 FAN header)"
  else
    echo "  unit not present (ok)"
  fi
}

test_fan() {
  local dev max i
  dev=$(find_cooling_device) || {
    log "ERROR: no cooling_device found"
    log "Run --install, reboot, then --test again"
    exit 1
  }
  max=$(cat "$dev/max_state")
  log "using $dev (type=$(cat "$dev/type"), max=$max)"
  log "ramping fan 0 → $max"
  for i in $(seq 0 "$max"); do
    echo "$i" >"$dev/cur_state"
    log "  cur_state=$i  $(vcgencmd measure_temp 2>/dev/null || echo temp=?)"
    sleep 2
  done
  echo 0 >"$dev/cur_state"
  log "set cur_state=0 — thermal governor resumes automatic control"
}

strip_block() {
  local tmp
  tmp=$(mktemp)
  awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
    $0==b {skip=1; next}
    $0==e {skip=0; next}
    !skip {print}
  ' "$CONFIG" >"$tmp"
  cp "$tmp" "$CONFIG"
  rm -f "$tmp"
}

install_curve() {
  [ -f "$CONFIG" ] || { log "ERROR: $CONFIG not found"; exit 1; }
  [ "$(id -u)" -eq 0 ] || { log "ERROR: run as root"; exit 1; }

  if grep -q "$MARKER_BEGIN" "$CONFIG" 2>/dev/null; then
    strip_block
    log "removed previous cozy fan block"
  fi

  {
    echo ""
    echo "$MARKER_BEGIN"
    echo "# Cozy Pi 5 onboard FAN header — firmware thermal trips (not Stratux fancontrol)"
    echo "# Temps in millidegrees C; speed 0-255. Enclosed avionics curve (earlier than stock)."
    echo "dtparam=fan_temp0=40000"
    echo "dtparam=fan_temp0_hyst=5000"
    echo "dtparam=fan_temp0_speed=100"
    echo "dtparam=fan_temp1=50000"
    echo "dtparam=fan_temp1_hyst=5000"
    echo "dtparam=fan_temp1_speed=150"
    echo "dtparam=fan_temp2=60000"
    echo "dtparam=fan_temp2_hyst=5000"
    echo "dtparam=fan_temp2_speed=200"
    echo "dtparam=fan_temp3=67500"
    echo "dtparam=fan_temp3_hyst=5000"
    echo "dtparam=fan_temp3_speed=255"
    echo "$MARKER_END"
  } >>"$CONFIG"
  log "wrote fan curve to $CONFIG"

  if systemctl list-unit-files 2>/dev/null | grep -q '^stratux_fancontrol.service'; then
    systemctl disable --now stratux_fancontrol.service 2>/dev/null || true
    log "disabled stratux_fancontrol.service (BCM GPIO18 PWM — not Pi 5 FAN header)"
  fi

  log "REBOOT required for dtparam curve to take effect"
  log "After reboot: $0 --test && $0 --status"
}

case "$MODE" in
  status) show_status ;;
  test) test_fan ;;
  install) install_curve; show_status ;;
esac
