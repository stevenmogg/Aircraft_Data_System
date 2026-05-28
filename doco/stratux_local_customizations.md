# Stratux local customizations (Stage 1)

This document records all local configuration and build customizations made on top of standard Stratux for the Cozy Aircraft Data System Stage 1 baseline.

Purpose:

- Explain **what** changed and **why**
- Provide enough detail to **re-apply** changes onto a future Stratux version
- Support future merges with upstream Stratux releases

Related docs:

- [cozy_aircraft_data_system_stage1.md](cozy_aircraft_data_system_stage1.md)
- [development_environment.md](development_environment.md)
- [stratux_build_and_imaging.md](stratux_build_and_imaging.md)

---

## 1. Design intent of the customizations

Baseline upstream Stratux is focused on AP operation and typical Stratux workflows.
Our Stage 1 target needed a predictable development/ops profile:

- Stable wired management IP for SSH from Mac
- Stratux AP preserved for cockpit clients (`192.168.10.1`)
- Secondary Wi-Fi uplink on USB dongle (`wlan1`) for phone hotspot internet
- Optional AP client passthrough to internet via uplink (NAT + forwarding)
- Defaults embedded in source so rebuilds are repeatable

---

## 2. Story of the change

### 2.1 Build process stabilization

During image builds on Apple Silicon, we hit two practical issues:

- Build script fails if local path contains spaces (unquoted local `git clone` in `image_build/build.sh`)
- Latest `pi-gen` arm64 branch drifted to package states that broke Stratux stage scripts (`ifplugd` candidate issue)

Resolution:

- Build from no-space path (`/tmp/...`)
- Pin `pi-gen` to the commit used with Stratux `v2.0-pre4` (`b9e30f2e0e2557ae62bde141eb657f48a2c21dae`)

### 2.2 Network architecture decision

Direct iPhone USB tethering was unreliable in this appliance-like image context.
We selected dual interface behavior:

- `ap0` serves Stratux AP clients
- `wlan1` (USB Wi-Fi dongle) connects to iPhone hotspot
- `eth0` reserved as deterministic management link

### 2.3 Persistence principle

All desired runtime behavior was moved into source templates and image-stage files so a new image rebuild reproduces the environment without manual one-off shell tweaks.

---

## 3. File-by-file customization map

## 3.1 Wired management IP default

### File

- `stratux-master/image_build/stage2/10-stratux/files/interfaces`
- `stratux-master/debian/interfaces.template`

### Change

Set `eth0` static instead of DHCP:

- Address: `192.168.50.2`
- Netmask: `255.255.255.0`

### Why

Predictable SSH management from Mac (`en10` set to `192.168.50.1`) without requiring Internet Sharing.

---

## 3.2 Secondary Wi-Fi uplink (`wlan1`)

### File

- `stratux-master/image_build/stage2/10-stratux/files/interfaces`
- `stratux-master/debian/interfaces.template`

### Change

Add `wlan1` interface stanza:

- DHCP client
- `wpa-conf /etc/wpa_supplicant/wpa_supplicant-wlan1.conf`
- `metric 50`
- disable `wlan1` powersave on up

### Why

Allow USB Wi-Fi dongle internet backhaul while preserving onboard AP behavior.

---

## 3.3 AP passthrough to uplink (forwarding + NAT)

### File

- `stratux-master/image_build/stage2/10-stratux/files/interfaces`
- `stratux-master/debian/interfaces.template`

### Change

In `wlan1` up/down hooks:

- enable `net.ipv4.ip_forward`
- add/remove iptables NAT:
  - `POSTROUTING -o wlan1 -j MASQUERADE`
- add/remove FORWARD rules:
  - `wlan1 -> ap0` established/related
  - `ap0 -> wlan1` forward

Rules are written idempotently on up (`-C` check before `-A`) and removed on down.

### Why

Permit clients on `192.168.10.0/24` to reach internet through hotspot uplink when available.

---

## 3.4 Ensure iptables is present in image

### File

- `stratux-master/image_build/stage2/10-stratux/01-run.sh`

### Change

Package install line includes `iptables` in stage build image setup.

### Why

NAT/forwarding hooks rely on iptables binaries.

---

## 3.5 Add dedicated wlan1 wpa_supplicant config file

### File

- `stratux-master/image_build/stage2/10-stratux/files/wpa_supplicant_wlan1.conf` (new)
- `stratux-master/debian/wpa_supplicant_wlan1.conf.template` (new)
- `stratux-master/image_build/stage2/10-stratux/01-run.sh` (install path)
- `stratux-master/Makefile` (template copy into config dir)

### Change

New wlan1 hotspot client config file added and installed.

Current defaults:

- Primary hotspot enabled:
  - SSID `CHANGE_ME_HOTSPOT_SSID`
  - PSK `CHANGE_ME_HOTSPOT_PASSWORD`
  - priority 20
- Secondary fallback present but commented out:
  - SSID `CHANGE_ME_FALLBACK_SSID`
  - same PSK
  - priority 10

### Why

Keep hotspot uplink credentials/source-controlled for deterministic builds.

---

## 4. Re-apply procedure on a future Stratux release

When upgrading to a future upstream Stratux version:

1. Clone new upstream release/tag.
2. Re-apply customizations in this order:
   - `interfaces` and `interfaces.template`
   - new `wpa_supplicant_wlan1` files
   - `01-run.sh` package/install additions
   - `Makefile` template-copy addition
3. Validate no upstream logic conflict in Wi-Fi mode sections.
4. Build image from no-space path.
5. Pin `pi-gen` to release-compatible commit if needed.
6. Boot test matrix:
   - AP reachable at `192.168.10.1`
   - `eth0` static at `192.168.50.2`
   - `wlan1` uplink gets DHCP from hotspot
   - NAT passthrough works from AP clients

---

## 5. Suggested merge strategy

- Keep this document as canonical intent.
- Prefer small, isolated commits for each concern:
  - wired mgmt IP
  - uplink interface
  - NAT/forwarding
  - credential template files
  - build package dependency
- During future rebase/merge:
  - resolve `interfaces.template` conflicts by preserving new upstream mode logic first, then reinsert local `wlan1` block
  - re-check `01-run.sh` package names against target Debian base

---

## 6. Security and operational notes

- Hotspot credentials are currently stored in repository templates.
  - acceptable for this private project baseline
  - if repository exposure changes, move credentials to post-flash provisioning
- WPA AP password policy remains a separate operational setting in Stratux UI/config.
- If uplink is unavailable, AP and local Stratux services continue operating.

---

## 7. Validation commands (post-flash)

On Pi:

```bash
ip -br a
ip route
iw dev wlan1 link
curl -I https://github.com
```

Expect:

- `ap0` at `192.168.10.1/24`
- `eth0` at `192.168.50.2/24`
- `wlan1` connected to hotspot and default route via uplink gateway
- internet reachable
