#!/bin/bash
# Sync MGL Extreme SD card <-> Cozy Pi
#
# Usage:
#   mgl_card_sync.sh              # auto-find MGL partition, mount, sync, unmount
#   mgl_card_sync.sh /dev/sda1    # use given partition
#   mgl_card_sync.sh --mounted    # card already at mount_point; do not unmount
#   mgl_card_sync.sh --release [/dev/sdX1]  # unmount after yank / remove event
#   mgl_card_sync.sh --if-card    # sync only if an MGL card is present (else exit 0)
#   mgl_card_sync.sh --dry-run
#
# On insert: convert every GPX in flight-plans/ to Extreme .ert using the card's
# Navidata.ewd, merge user waypoints into WAYPOINT.EWD, delete previous .ert
# files so the card only has routes for the current GPX set. Then copy
# ENIGMA.REC / XTFLIGHT.CSV into the Pi inbox.
#
set -euo pipefail

CONFIG="${MGL_CARD_CONFIG:-/cozy-data-system/config/mgl_card/mgl_card.yaml}"
LOCK_FILE="${MGL_CARD_LOCK:-/run/cozy-mgl-card.lock}"
DRY_RUN=0
KEEP_MOUNTED=0
RELEASE_ONLY=0
IF_CARD=0
DEVICE_ARG=""

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) mgl-card: $*"; }
die() { log "ERROR: $*"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --mounted) KEEP_MOUNTED=1; shift ;;
    --release) RELEASE_ONLY=1; shift ;;
    --if-card) IF_CARD=1; shift ;;
    --config) CONFIG="$2"; shift 2 ;;
    -*) die "unknown option $1" ;;
    *) DEVICE_ARG="$1"; shift ;;
  esac
done

[ -f "$CONFIG" ] || die "config not found: $CONFIG"

yaml_get() {
  local key="$1"
  awk -v k="$key" '
    $0 ~ "^"k":" {
      sub("^[^:]+:[[:space:]]*", "");
      gsub(/["'\'']/, "");
      print;
      exit
    }
  ' "$CONFIG"
}

yaml_list() {
  local key="$1"
  awk -v k="$key" '
    $0 ~ "^"k":" { inlist=1; next }
    inlist && /^[^[:space:]#-]/{ exit }
    inlist && /^[[:space:]]*-[[:space:]]*/ {
      sub(/^[[:space:]]*-[[:space:]]*/, "");
      gsub(/["'\'']/, "");
      print
    }
  ' "$CONFIG"
}

MOUNT_POINT="$(yaml_get mount_point)"
PLANS_DIR="$(yaml_get flight_plans_dir)"
INBOX_ENIGMA="$(yaml_get inbox_enigma)"
INBOX_XT="$(yaml_get inbox_xtflight)"
STATUS_FILE="$(yaml_get status_file)"
EXPECTED_LABEL="$(yaml_get expected_label)"

mapfile -t PROTECTED < <(yaml_list protected_names)
mapfile -t PLAN_EXTS < <(yaml_list flight_plan_extensions)

mkdir -p "$PLANS_DIR" "$INBOX_ENIGMA" "$INBOX_XT" "$(dirname "$STATUS_FILE")"
mkdir -p "$MOUNT_POINT"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -n "${COZY_AVPLAN_TO_MGL:-}" ]; then
  CONVERTER="$COZY_AVPLAN_TO_MGL"
elif [ -f "$SCRIPT_DIR/../navigation/avplan_to_mgl.py" ]; then
  CONVERTER="$SCRIPT_DIR/../navigation/avplan_to_mgl.py"
else
  CONVERTER="/cozy-data-system/navigation/avplan_to_mgl.py"
fi

# Serialise insert/remove/sync so rapid card swaps cannot race.
exec 9>"$LOCK_FILE"
if ! flock -w 60 9; then
  die "could not acquire lock $LOCK_FILE (another sync stuck?)"
fi

is_protected() {
  local base="$1"
  local p upper
  upper=$(echo "$base" | tr '[:lower:]' '[:upper:]')
  for p in "${PROTECTED[@]}"; do
    if [ "$upper" = "$(echo "$p" | tr '[:lower:]' '[:upper:]')" ]; then
      return 0
    fi
  done
  case "$base" in
    .*|._*) return 0 ;;
  esac
  return 1
}

is_plan_ext() {
  local base="$1"
  local ext lower ext_l
  lower=$(echo "$base" | tr '[:upper:]' '[:lower:]')
  for ext in "${PLAN_EXTS[@]}"; do
    ext_l=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    case "$lower" in
      *"$ext_l") return 0 ;;
    esac
  done
  return 1
}

looks_like_mgl_root() {
  local root="$1"
  [ -f "$root/ENIGMA.REC" ] || [ -f "$root/enigma.rec" ] \
    || [ -f "$root/XTFLIGHT.CSV" ] || [ -f "$root/xtflight.csv" ]
}

device_exists() {
  local dev="$1"
  [ -n "$dev" ] && [ -b "$dev" ]
}

mount_source() {
  findmnt -n -o SOURCE --target "$MOUNT_POINT" 2>/dev/null || true
}

# True if the mountpoint is usable (source still present and readable).
mount_is_healthy() {
  local src
  mountpoint -q "$MOUNT_POINT" 2>/dev/null || return 1
  src=$(mount_source)
  device_exists "$src" || return 1
  # Stale VFAT after yank often fails directory reads.
  ls "$MOUNT_POINT" >/dev/null 2>&1 || return 1
  return 0
}

force_clear_mount() {
  local why="${1:-stale or foreign mount}"
  local src
  src=$(mount_source)
  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    return 0
  fi
  log "clearing mount ($why); was $src"
  sync 2>/dev/null || true
  umount "$MOUNT_POINT" 2>/dev/null || true
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    umount -l "$MOUNT_POINT" 2>/dev/null || true
  fi
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    umount -f "$MOUNT_POINT" 2>/dev/null || true
  fi
  # Last resort: lazy again after short wait
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    sleep 0.5
    umount -l "$MOUNT_POINT" 2>/dev/null || true
  fi
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    die "unable to clear $MOUNT_POINT (still mounted from $(mount_source))"
  fi
  log "mount cleared"
}

wait_for_device() {
  local dev="$1"
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if device_exists "$dev"; then
      # Give udev/kernel a moment to finish partition probe
      [ -n "$(lsblk -no FSTYPE "$dev" 2>/dev/null | tr -d ' ')" ] && return 0
      # fstype may lag; still accept if node exists after a few tries
      [ "$i" -ge 4 ] && return 0
    fi
    sleep 0.25
  done
  return 1
}

safe_umount() {
  sync 2>/dev/null || true
  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    return 0
  fi
  if umount "$MOUNT_POINT" 2>/dev/null; then
    log "unmounted $MOUNT_POINT — safe to remove card"
    return 0
  fi
  log "clean umount failed; trying lazy umount"
  umount -l "$MOUNT_POINT" 2>/dev/null || true
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    die "umount failed — wait a moment before removing card"
  fi
  log "lazy-unmounted $MOUNT_POINT"
}

write_status_error() {
  local msg="$1"
  local ts
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  cat >"$STATUS_FILE" <<EOF
{
  "ok": false,
  "timestamp_utc": "$ts",
  "device": "${DEVICE_ARG:-}",
  "mount_point": "$MOUNT_POINT",
  "error": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$msg"),
  "import_enigma": "pending"
}
EOF
}

# --- release path (card yanked / remove udev) ---
if [ "$RELEASE_ONLY" -eq 1 ]; then
  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    log "release: nothing mounted at $MOUNT_POINT"
    exit 0
  fi
  src=$(mount_source)
  if [ -n "$DEVICE_ARG" ]; then
    # Only clear if this remove event matches the mounted device, or mount is dead.
    if [ "$src" = "$DEVICE_ARG" ] || ! device_exists "$src"; then
      force_clear_mount "release for $DEVICE_ARG (was $src)"
    else
      log "release: ignoring $DEVICE_ARG (mounted is $src)"
    fi
  else
    force_clear_mount "release"
  fi
  exit 0
fi

find_mgl_partition() {
  local part label fstype tmp
  for part in /dev/sd[a-z][0-9]* /dev/mmcblk[0-9]p[0-9]*; do
    [ -b "$part" ] || continue
    label=$(lsblk -no LABEL "$part" 2>/dev/null | head -1 | tr -d ' ')
    fstype=$(lsblk -no FSTYPE "$part" 2>/dev/null | head -1 | tr -d ' ')
    if [ -n "$EXPECTED_LABEL" ] && [ "$label" = "$EXPECTED_LABEL" ]; then
      echo "$part"
      return 0
    fi
    if [ "$fstype" = "vfat" ] || [ "$fstype" = "exfat" ]; then
      tmp=$(mktemp -d)
      if mount -o ro,uid=1000,gid=1000 "$part" "$tmp" 2>/dev/null; then
        if looks_like_mgl_root "$tmp"; then
          umount "$tmp" 2>/dev/null || true
          rmdir "$tmp" 2>/dev/null || true
          echo "$part"
          return 0
        fi
        umount "$tmp" 2>/dev/null || true
      fi
      rmdir "$tmp" 2>/dev/null || true
    fi
  done
  return 1
}

DEVICE=""
WE_MOUNTED=0

# Always drop a dead mount first (yank without release / previous card gone).
if mountpoint -q "$MOUNT_POINT" 2>/dev/null && ! mount_is_healthy; then
  force_clear_mount "stale mount before sync"
fi

if [ "$KEEP_MOUNTED" -eq 1 ]; then
  mount_is_healthy || die "$MOUNT_POINT is not a healthy mount (--mounted)"
  DEVICE=$(mount_source)
else
  if [ -n "$DEVICE_ARG" ]; then
    DEVICE="$DEVICE_ARG"
    wait_for_device "$DEVICE" || die "device never appeared: $DEVICE"
  else
    if ! DEVICE="$(find_mgl_partition)"; then
      if [ "$IF_CARD" -eq 1 ]; then
        log "no MGL card present — skip (flight-plans changed, nothing to write)"
        exit 0
      fi
      die "no MGL SD card found"
    fi
  fi
  device_exists "$DEVICE" || die "not a block device: $DEVICE"

  # Drop a healthy mount of a *different* card so the new insert can proceed.
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    src=$(mount_source)
    if [ "$src" = "$DEVICE" ] && mount_is_healthy; then
      log "already mounted $DEVICE at $MOUNT_POINT"
    else
      force_clear_mount "need $DEVICE; had ${src:-none}"
    fi
  fi

  if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    if [ "$DRY_RUN" -eq 0 ]; then
      local_try=0
      until mount -o uid=1000,gid=1000,umask=0022,flush "$DEVICE" "$MOUNT_POINT" 2>/dev/null; do
        local_try=$((local_try + 1))
        [ "$local_try" -ge 5 ] && {
          write_status_error "mount failed for $DEVICE"
          die "mount failed for $DEVICE"
        }
        log "mount retry $local_try for $DEVICE"
        sleep 0.4
      done
      WE_MOUNTED=1
    fi
  fi
  log "using $DEVICE at $MOUNT_POINT"
fi

# --- identify MGL card (skip quietly for random USB sticks) ---
if ! looks_like_mgl_root "$MOUNT_POINT"; then
  label_now=$(lsblk -no LABEL "$(mount_source)" 2>/dev/null | head -1 | tr -d ' ')
  if [ -n "$EXPECTED_LABEL" ] && [ "$label_now" = "$EXPECTED_LABEL" ]; then
    log "label=$EXPECTED_LABEL but no ENIGMA/XTFLIGHT yet — continuing (plans-only)"
  else
    log "skip: not an MGL card (no ENIGMA/XTFLIGHT, label='$label_now')"
    if [ "$WE_MOUNTED" -eq 1 ] && [ "$KEEP_MOUNTED" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
      safe_umount || force_clear_mount "non-MGL"
    fi
    exit 0
  fi
fi

# Bail early if the filesystem went bad mid-flight (yank during settle).
if ! ls "$MOUNT_POINT" >/dev/null 2>&1; then
  write_status_error "card became unreadable (removed during settle?)"
  force_clear_mount "unreadable"
  exit 1
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
COPIED_PLANS=0
DELETED_PLANS=0
ENIGMA_DEST=""
XT_DEST=""
ROUTES_FILE="$(dirname "$STATUS_FILE")/last_routes.json"
ROUTES_OK=1

# --- 1) AvPlan GPX on Pi → Extreme .ert on card (uses card Navidata + WAYPOINT.EWD) ---
log "converting AvPlan GPX in $PLANS_DIR using card navidata/waypoints"
if [ ! -f "$CONVERTER" ]; then
  log "ERROR: converter missing: $CONVERTER"
  ROUTES_OK=0
  printf '%s\n' '{"ok":false,"error":"converter missing","routes":[],"routes_removed":[]}' >"$ROUTES_FILE"
else
  conv_cmd=(python3 "$CONVERTER" --card-sync --gpx "$PLANS_DIR" --card-root "$MOUNT_POINT" --json-out "$ROUTES_FILE")
  if [ "$DRY_RUN" -eq 1 ]; then
    conv_cmd+=(--dry-run)
    log "DRY-RUN route conversion"
  fi
  if "${conv_cmd[@]}"; then
    log "route conversion ok"
  else
    log "route conversion reported an error (see $ROUTES_FILE)"
    ROUTES_OK=0
  fi
fi
if [ -f "$ROUTES_FILE" ]; then
  COPIED_PLANS=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(int(d.get("gpx_count") or 0))' "$ROUTES_FILE" 2>/dev/null || echo 0)
fi

# Remove leftover AvPlan-style files from the card (Extreme uses .ert, not GPX).
for f in "$MOUNT_POINT"/*; do
  [ -f "$f" ] || continue
  base=$(basename "$f")
  is_protected "$base" && continue
  is_plan_ext "$base" || continue
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN delete AvPlan file on card: $base"
  else
    rm -f "$f"
    log "deleted AvPlan file on card: $base"
  fi
  DELETED_PLANS=$((DELETED_PLANS + 1))
done

# --- 2) ENIGMA.REC -> inbox (single ENIGMA_LATEST.REC; importer renames to _PROCESSED) ---
ENIGMA_SRC=""
for cand in ENIGMA.REC Enigma.rec enigma.rec; do
  if [ -f "$MOUNT_POINT/$cand" ]; then
    ENIGMA_SRC="$MOUNT_POINT/$cand"
    break
  fi
done
if [ -n "$ENIGMA_SRC" ]; then
  ENIGMA_DEST="$INBOX_ENIGMA/ENIGMA_LATEST.REC"
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN copy $ENIGMA_SRC -> $ENIGMA_DEST"
  else
    # Drop any legacy timestamped / hash copies; keep only _LATEST (+ optional _PROCESSED).
    find "$INBOX_ENIGMA" -maxdepth 1 -type f ! -name 'ENIGMA_LATEST.REC' ! -name 'ENIGMA_PROCESSED.REC' -delete 2>/dev/null || true
    cp -f "$ENIGMA_SRC" "$ENIGMA_DEST"
    log "copied ENIGMA.REC -> $ENIGMA_DEST ($(stat -c%s "$ENIGMA_DEST") bytes)"
  fi
else
  log "no ENIGMA.REC on card"
fi

# --- 3) XTFLIGHT.CSV -> inbox (single XTFLIGHT_LATEST.CSV) ---
XT_SRC=""
for cand in XTFLIGHT.CSV Xtflight.csv xtflight.csv; do
  if [ -f "$MOUNT_POINT/$cand" ]; then
    XT_SRC="$MOUNT_POINT/$cand"
    break
  fi
done
if [ -n "$XT_SRC" ]; then
  XT_DEST="$INBOX_XT/XTFLIGHT_LATEST.CSV"
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN copy $XT_SRC -> $XT_DEST"
  else
    find "$INBOX_XT" -maxdepth 1 -type f ! -name 'XTFLIGHT_LATEST.CSV' ! -name 'XTFLIGHT_PROCESSED.CSV' -delete 2>/dev/null || true
    cp -f "$XT_SRC" "$XT_DEST"
    log "copied XTFLIGHT.CSV -> $XT_DEST"
  fi
else
  log "no XTFLIGHT.CSV on card"
fi

if [ "$DRY_RUN" -eq 0 ]; then
  DEVICE_VAL="${DEVICE:-$(mount_source)}"
  export TS DEVICE_VAL MOUNT_POINT STATUS_FILE ROUTES_FILE ENIGMA_DEST XT_DEST COPIED_PLANS DELETED_PLANS ROUTES_OK
  python3 - <<'PY'
import json, os
from pathlib import Path

routes = {}
rf = Path(os.environ["ROUTES_FILE"])
if rf.is_file():
    try:
        routes = json.loads(rf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        routes = {"ok": False, "error": "invalid routes JSON"}

def _or_none(v):
    return v if v else None

ok = os.environ.get("ROUTES_OK", "1") == "1"
status = {
    "ok": ok,
    "timestamp_utc": os.environ["TS"],
    "device": os.environ.get("DEVICE_VAL") or "",
    "mount_point": os.environ["MOUNT_POINT"],
    "plans_copied": int(os.environ.get("COPIED_PLANS") or 0),
    "plans_deleted": int(os.environ.get("DELETED_PLANS") or 0),
    "routes": routes,
    "enigma": _or_none(os.environ.get("ENIGMA_DEST")),
    "xtflight": _or_none(os.environ.get("XT_DEST")),
    "import_enigma": "pending",
}
path = Path(os.environ["STATUS_FILE"])
path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
PY
  chown -R pi:pi /cozy-data-system/data/mgl-inbox 2>/dev/null || true
fi

# Always leave unmounted after auto sync so the next yank/insert is clean.
if [ "$KEEP_MOUNTED" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    safe_umount || force_clear_mount "post-sync"
  fi
else
  log "left mounted at $MOUNT_POINT"
fi

log "done routes=$COPIED_PLANS avplan_deleted=$DELETED_PLANS routes_ok=$ROUTES_OK"
exit 0
