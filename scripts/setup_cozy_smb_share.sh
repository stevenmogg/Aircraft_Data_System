#!/bin/bash
# Install Cozy data SMB share on a running Stratux Pi (Phase 1 flight plans).
# Safe to re-run.
#
# Stratux uses a 250MB overlay for runtime writes; Samba is too large for apt there.
# When overlay is active, this script installs into /overlay/robase via chroot
# (requires offline .deb bundle — see doco/flight_plan_file_share.md).

set -euo pipefail

COZY_ROOT=/cozy-data-system
SMB_SNIPPET=/etc/samba/smb.conf.d/cozy-data.conf
DEB_DIR="${1:-/tmp/samba-debs}"

echo "=== Cozy flight-plan SMB setup ==="

install_samba_debs() {
  local root="$1"
  echo "Installing Samba packages into ${root}..."
  for m in dev proc sys; do
    mount --bind "/${m}" "${root}/${m}"
  done
  chroot "${root}" dpkg -i /tmp/samba-debs/*.deb
  for m in sys proc dev; do
    umount "${root}/${m}"
  done
}

write_smb_config() {
  local root="$1"
  mkdir -p "${root}/etc/samba/smb.conf.d"
  cat >"${root}${SMB_SNIPPET}" <<'EOF'
[cozy-data]
   comment = Cozy data (flight plans and project files)
   path = /cozy-data-system/data
   browseable = yes
   read only = no
   writable = yes
   guest ok = no
   valid users = pi
   create mask = 0664
   directory mask = 0775
   force user = pi
   force group = pi
   vfs objects = fruit streams_xattr
   fruit:metadata = stream
   fruit:model = RackMac
   fruit:posix_rename = yes
   fruit:veto_appledouble = no
   fruit:nfs_aces = no
EOF
  cat >"${root}/etc/samba/smb.conf.d/apple-vfs.conf" <<'EOF'
   server min protocol = SMB2
   vfs objects = fruit streams_xattr
   fruit:metadata = stream
   fruit:model = RackMac
   fruit:posix_rename = yes
   fruit:veto_appledouble = no
   fruit:nfs_aces = no
EOF
  if [ -f "${root}/etc/samba/smb.conf" ]; then
    sed -i '/^include = \/etc\/samba\/smb.conf.d/d' "${root}/etc/samba/smb.conf"
    if ! grep -q 'apple-vfs.conf' "${root}/etc/samba/smb.conf"; then
      sed -i '/^\[global\]/a\
   include = /etc/samba/smb.conf.d/apple-vfs.conf\
   include = /etc/samba/smb.conf.d/cozy-data.conf' "${root}/etc/samba/smb.conf"
    fi
  fi
}

setup_cozy_dirs() {
  local root="$1"
  mkdir -p "${root}${COZY_ROOT}/data/flight-plans" \
           "${root}${COZY_ROOT}/config" \
           "${root}${COZY_ROOT}/fix_gateway_plugins"
  chown -R pi:pi "${root}${COZY_ROOT}"
  chmod 775 "${root}${COZY_ROOT}/data"
  chmod 2775 "${root}${COZY_ROOT}/data/flight-plans"
}

ensure_runtime_config() {
  # Overlay upper layer may hold empty stubs; prefer robase copies.
  mkdir -p /etc/samba/smb.conf.d
  if [ -f /overlay/robase/etc/samba/smb.conf ]; then
    cp /overlay/robase/etc/samba/smb.conf /etc/samba/smb.conf
  fi
  if [ -f /overlay/robase/etc/samba/smb.conf.d/cozy-data.conf ]; then
    cp /overlay/robase/etc/samba/smb.conf.d/cozy-data.conf "${SMB_SNIPPET}"
  elif [ ! -s "${SMB_SNIPPET}" ] 2>/dev/null; then
    write_smb_config ""
  fi
  if [ -f /overlay/robase/lib/systemd/system/smbd.service ] && [ ! -f /lib/systemd/system/smbd.service ]; then
    cp /overlay/robase/lib/systemd/system/smbd.service /lib/systemd/system/
  fi
}

start_smbd() {
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files smbd.service >/dev/null 2>&1; then
    systemctl enable smbd
    systemctl restart smbd
  elif [ -x /usr/sbin/smbd ] && ! pgrep -x smbd >/dev/null 2>&1; then
    /usr/sbin/smbd
  fi
}

overlay_is_active() {
  [ -d /overlay/robase/overlay ]
}

if dpkg -s samba >/dev/null 2>&1 || [ -x /usr/sbin/smbd ]; then
  echo "Samba already installed."
else
  if overlay_is_active; then
    if [ ! -d "${DEB_DIR}" ] || [ -z "$(ls -A "${DEB_DIR}"/*.deb 2>/dev/null)" ]; then
      echo "ERROR: Samba not installed and ${DEB_DIR} missing offline .deb bundle."
      echo "Copy samba-debs.tgz to the Pi, extract to ${DEB_DIR}, then re-run."
      exit 1
    fi
    overlayctl unlock
    cp -a "${DEB_DIR}" /overlay/robase/tmp/samba-debs
    install_samba_debs /overlay/robase
    setup_cozy_dirs /overlay/robase
    write_smb_config /overlay/robase
    chroot /overlay/robase bash -c "(echo raspberry; echo raspberry) | smbpasswd -a pi -s"
    chroot /overlay/robase systemctl enable smbd
    rm -rf /overlay/robase/tmp/samba-debs
    overlayctl lock || true
  else
    echo "Installing samba via apt..."
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq samba
    setup_cozy_dirs ""
    write_smb_config ""
    (echo raspberry; echo raspberry) | smbpasswd -a pi -s
    systemctl enable smbd
  fi
fi

setup_cozy_dirs ""
ensure_runtime_config
start_smbd

echo
echo "Share ready: smb://$(hostname -I | awk '{print $1}')/cozy-data"
echo "Flight plans folder: ${COZY_ROOT}/data/flight-plans/"
echo "From cockpit Wi-Fi use: smb://192.168.10.1/cozy-data  (user pi)"
testparm -s 2>/dev/null | grep -A12 '\[cozy-data\]' || true
