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
- Onboard `wlan0` as hotspot client (AP+Client / WiFiMode 2) for phone internet
- Internet passthrough from AP clients via NAT on `wlan0`
- Optional USB dongle `wlan1` as backup uplink
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
Working Stage 1 profile:

- `ap0` serves Stratux AP clients at `192.168.10.1`
- Onboard `wlan0` joins phone hotspot (AP+Client) and provides uplink + NAT passthrough
- `eth0` reserved as deterministic management link (`192.168.50.2`)
- Optional `wlan1` USB dongle remains as backup client (higher metric)

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

## 3.2 AP+Client mode (onboard wlan0 uplink)

### File

- `stratux-master/image_build/stage2/10-stratux/files/interfaces`
- `stratux-master/debian/interfaces.template`
- `stratux-master/image_build/stage2/10-stratux/files/wpa_supplicant.conf`
- `stratux-master/debian/stratux.conf.default`
- `stratux-master/image_build/stage2/10-stratux/files/stratux.conf.default`

### Change

Bake Stratux **WiFiMode 2** (AP+Client):

- `ap0` AP at `192.168.10.1`
- `wlan0` client via `wpa-roam` / `/etc/wpa_supplicant/wpa_supplicant.conf`
- `WiFiInternetPassThroughEnabled: true` with idempotent iptables MASQUERADE/FORWARD on `wlan0`
- Default client network: phone hotspot SSID/PSK in wpa + `WiFiClientNetworks` in stratux.conf
- Install boot config to `/boot/firmware/stratux.conf` so first-boot rewrite and UI match

### Why

This is the proven Stage 1 path: Mac SSH on Ethernet, AvPlan/cockpit on Stratux AP, Pi internet via phone hotspot without a USB Wi-Fi dongle.

---

## 3.3 Optional secondary Wi-Fi uplink (`wlan1`)

### File

- `stratux-master/image_build/stage2/10-stratux/files/interfaces`
- `stratux-master/debian/interfaces.template`

### Change

Add `wlan1` interface stanza:

- DHCP client
- `wpa-conf /etc/wpa_supplicant/wpa_supplicant-wlan1.conf`
- `metric 100` (prefer onboard `wlan0` client when both are up)
- disable `wlan1` powersave on up

### Why

Allow USB Wi-Fi dongle as backup internet backhaul while preserving AP+Client as the primary path.

---

## 3.4 AP passthrough (forwarding + NAT)

### File

- `stratux-master/image_build/stage2/10-stratux/files/interfaces`
- `stratux-master/debian/interfaces.template`

### Change

In AP+Client `wlan0` hooks when passthrough is enabled:

- enable `net.ipv4.ip_forward`
- idempotent iptables NAT: `POSTROUTING -o wlan0 -j MASQUERADE`
- idempotent FORWARD rules: `wlan0 <-> ap0`

### Why

Permit clients on `192.168.10.0/24` to reach internet through the phone hotspot when available.

---

## 3.5 Ensure iptables is present in image

### File

- `stratux-master/image_build/stage2/10-stratux/01-run.sh`

### Change

Package install line includes `iptables` in stage build image setup.

### Why

NAT/forwarding hooks rely on iptables binaries.

---

## 3.6 Hotspot credential / wpa files

### File

- `stratux-master/image_build/stage2/10-stratux/files/wpa_supplicant.conf` (wlan0 client)
- `stratux-master/image_build/stage2/10-stratux/files/wpa_supplicant_wlan1.conf`
- `stratux-master/debian/wpa_supplicant_wlan1.conf.template`
- `stratux-master/debian/stratux.conf.default` / image `files/stratux.conf.default`
- `stratux-master/image_build/stage2/10-stratux/01-run.sh` (install paths)
- `stratux-master/Makefile` (copies `debian/stratux.conf.default` into package)

### Change

Primary hotspot block enabled with Stage 1 credentials; optional iPad fallback commented out.
`01-run.sh` installs wpa files, interfaces, and both `/opt/stratux/cfg/stratux.conf.default` and `/boot/firmware/stratux.conf`.

### Why

Deterministic out-of-box networking after flashing a newly built image.

---

## 3.7 Cockpit display resolution (480x320)

### File

- `stratux-master/image_build/stage2/10-stratux/01-run.sh`
- `stratux-master/image_build/stage2/10-stratux/files/config.txt`

### Change

On Bookworm / Pi 5, resolution is set via KMS kernel cmdline (not legacy `hdmi_*` alone):

- Prepend to `/boot/firmware/cmdline.txt` (single line):
  - `video=HDMI-A-1:480x320MR@60me video=HDMI-A-2:480x320MR@60me`
- Set `disable_fw_kms_setup=1` in `config.txt` so firmware does not inject a high-res EDID mode
- Also store legacy `hdmi_cvt=480 320 ...` hints for early firmware
- Large console font via `/etc/default/console-setup` (`TerminusBold` `16x32`)

See also [hdmi_480x320_boot_fix.md](hdmi_480x320_boot_fix.md) for editing the SD boot partition from a Mac.

### Why

Match the Stage 1 480×320 cockpit panel from first boot (console and HDMI output).

### Note

This targets HDMI panels. SPI/DPI TFTs need a different `dtoverlay` and are not covered here.

---

## 4. Re-apply procedure on a future Stratux release

When upgrading to a future upstream Stratux version:

1. Clone new upstream release/tag.
2. Re-apply customizations in this order:
   - `interfaces` and `interfaces.template` (eth0 static, AP+Client passthrough, optional wlan1)
   - `wpa_supplicant.conf` / `wpa_supplicant_wlan1` files
   - `stratux.conf.default` (WiFiMode 2, passthrough, client networks)
   - `01-run.sh` package/install additions (including boot `stratux.conf` and 480x320 `video=` cmdline)
   - `config.txt` (`disable_fw_kms_setup=1`)
   - `Makefile` default-config copy
3. Validate no upstream logic conflict in Wi-Fi mode sections.
4. Build image from no-space path.
5. Pin `pi-gen` to release-compatible commit if needed.
6. Boot test matrix:
   - AP reachable at `192.168.10.1`
   - `eth0` static at `192.168.50.2`
   - `wlan0` joins phone hotspot and gets DHCP
   - NAT passthrough works from AP clients
   - optional `wlan1` uplink if dongle present
   - HDMI console at 480×320

---

## 5. Suggested merge strategy

- Keep this document as canonical intent.
- Prefer small, isolated commits for each concern:
  - wired mgmt IP
  - AP+Client defaults
  - uplink / passthrough
  - credential template files
  - build package dependency
- During future rebase/merge:
  - resolve `interfaces.template` conflicts by preserving new upstream mode logic first, then reinsert local eth0/wlan1 blocks and passthrough idempotency
  - re-check `01-run.sh` package names against target Debian base

---

## 6. Security and operational notes

- Hotspot credentials are stored in repository templates for private Stage 1 convenience.
  - if repository exposure changes, move credentials to post-flash provisioning / placeholders
- WPA AP password policy remains a separate operational setting in Stratux UI/config.
- If uplink is unavailable, AP and local Stratux services continue operating.

---

## 7. Validation commands (post-flash)

```bash
ip -br a
ip route
iw dev wlan0 link
ping -c 2 8.8.8.8
curl -I https://example.com
```

From Mac management link (`192.168.50.1` ↔ `192.168.50.2`):

```bash
ssh stratux 'ip -br a; iw dev wlan0 link; ping -c 2 8.8.8.8'
```
