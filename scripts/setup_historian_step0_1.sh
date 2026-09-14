#!/bin/bash
# Install Historian Step 0–1 onto a Stratux Pi (code, config, durable data mount).
#
# Always installs into /overlay/robase when overlay is active.
#
# Usage (from repo on Mac, or after copying tree to Pi):
#   sudo ./scripts/setup_historian_step0_1.sh
#
# Or with explicit source tree:
#   sudo ./scripts/setup_historian_step0_1.sh /path/to/repo

set -euo pipefail

SRC_ROOT="${1:-}"
if [ -z "${SRC_ROOT}" ]; then
  SRC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

COZY=/cozy-data-system
SERVICE_DATA=/etc/systemd/system/cozy-historian-data.service

overlay_active() {
  [ -d /overlay/robase/overlay ]
}

ROOT=""
if overlay_active; then
  overlayctl unlock
  ROOT=/overlay/robase
fi

echo "=== Installing Historian into ${ROOT}${COZY} ==="
mkdir -p "${ROOT}${COZY}/historian" \
         "${ROOT}${COZY}/config/historian" \
         "${ROOT}${COZY}/scripts" \
         "${ROOT}${COZY}/data/historian/aircraft" \
         "${ROOT}/etc/systemd/system"

# Package
rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
  "${SRC_ROOT}/historian/" "${ROOT}${COZY}/historian/"

# Config
install -m 644 "${SRC_ROOT}/config/historian/historian.yaml" "${ROOT}${COZY}/config/historian/"
install -m 644 "${SRC_ROOT}/config/historian/aircraft.yaml" "${ROOT}${COZY}/config/historian/"

# Mount script
install -m 755 "${SRC_ROOT}/scripts/mount_historian_data.sh" "${ROOT}${COZY}/scripts/mount_historian_data.sh"

# Also keep a copy under /cozy-data-system that matches (when overlay merges)
if [ -n "${ROOT}" ]; then
  mkdir -p "${COZY}/scripts" "${COZY}/config/historian" "${COZY}/historian" 2>/dev/null || true
fi

# Wrapper CLI in venv
VENV_BIN="${ROOT}${COZY}/venv/bin"
if [ ! -x "${VENV_BIN}/python" ]; then
  echo "ERROR: FIX/cozy venv not found at ${VENV_BIN}/python" >&2
  exit 1
fi

cat >"${VENV_BIN}/historian" <<'EOF'
#!/bin/bash
export PYTHONPATH="/cozy-data-system${PYTHONPATH:+:$PYTHONPATH}"
exec /cozy-data-system/venv/bin/python -m historian "$@"
EOF
chmod 755 "${VENV_BIN}/historian"

# Systemd: durable data mount at boot
cat >"${ROOT}${SERVICE_DATA}" <<'EOF'
[Unit]
Description=Cozy Historian durable data bind-mount (robase)
DefaultDependencies=no
After=local-fs.target
Before=fixgateway.service multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/cozy-data-system/scripts/mount_historian_data.sh
ExecStop=/bin/umount /cozy-data-system/data/historian

[Install]
WantedBy=multi-user.target
EOF

install -m 644 "${SRC_ROOT}/config/systemd/cozy-historian-data.service" "${ROOT}${SERVICE_DATA}"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-historian-data.service" "${SERVICE_DATA}"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-historian.service" \
  "${ROOT}/etc/systemd/system/cozy-historian.service"
install -m 644 "${SRC_ROOT}/config/systemd/cozy-historian.service" \
  /etc/systemd/system/cozy-historian.service

if overlay_active; then
  mkdir -p "${ROOT}/etc/systemd/system/multi-user.target.wants"
  ln -sfn /etc/systemd/system/cozy-historian-data.service \
    "${ROOT}/etc/systemd/system/multi-user.target.wants/cozy-historian-data.service"
  ln -sfn /etc/systemd/system/cozy-historian.service \
    "${ROOT}/etc/systemd/system/multi-user.target.wants/cozy-historian.service"
fi

chown -R pi:pi "${ROOT}${COZY}/historian" \
               "${ROOT}${COZY}/config/historian" \
               "${ROOT}${COZY}/data/historian" \
               "${ROOT}${COZY}/scripts" 2>/dev/null || true

systemctl daemon-reload
systemctl enable cozy-historian-data.service
systemctl enable cozy-historian.service
systemctl start cozy-historian-data.service
systemctl start cozy-historian.service

if overlay_active; then
  overlayctl lock || true
fi

echo "=== Initialising database ==="
sudo -u pi env PYTHONPATH=/cozy-data-system \
  "${COZY}/venv/bin/python" -m historian init-db

echo "=== Status ==="
sudo -u pi env PYTHONPATH=/cozy-data-system \
  "${COZY}/venv/bin/python" -m historian status

echo "=== Done (Step 0–1) ==="
