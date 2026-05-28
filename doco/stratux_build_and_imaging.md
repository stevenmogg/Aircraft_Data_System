# Stratux build and imaging workflow

This document records the working process used to build Stratux and create a bootable Raspberry Pi image from a Mac.

Use this together with:

- [development_environment.md](development_environment.md)
- [cozy_aircraft_data_system_stage1.md](cozy_aircraft_data_system_stage1.md)
- [stratux_local_customizations.md](stratux_local_customizations.md)

---

## 1. Scope

This process is for:

- Building a custom Stratux image from source
- Flashing that image to microSD for bench testing
- Running a standard 1090 MHz receiver setup (no FLARM hardware required)

---

## 2. Prerequisites

- Apple Silicon Mac with Docker Desktop installed as the **Apple Silicon (arm64)** build
- Docker Desktop engine running
- Enough free disk (image build can use many GB)
- `git`, `curl`, `unzip`, Raspberry Pi Imager

Quick checks:

```bash
docker info >/dev/null && echo "docker ok"
file /Applications/Docker.app/Contents/MacOS/com.docker.backend
```

The Docker backend must report `arm64`, not `x86_64`.

---

## 3. Source checkout

Use a path **without spaces**. The Stratux image build script calls `git clone` without quoting local paths.

```bash
git clone --branch v2.0-pre4 --recurse-submodules https://github.com/stratux/stratux.git /tmp/stratux-v2.0-pre4
```

---

## 4. Build notes that matter

### 4.1 pi-gen branch/commit

Using the latest `pi-gen` `arm64` branch can fail due to dependency drift (for example, `ifplugd` package candidate issues in newer Debian bases).

For reproducible builds with Stratux `v2.0-pre4`, use the pi-gen commit pinned by that release:

```bash
cd /tmp/stratux-v2.0-pre4/image_build/pi-gen
git checkout b9e30f2e0e2557ae62bde141eb657f48a2c21dae
```

### 4.2 Stale pi-gen container

If the build stops with:

`Container pigen_work already exists and you did not specify CONTINUE=1`

remove it and rerun:

```bash
docker rm -v pigen_work
```

---

## 5. Build the image

```bash
cd /tmp/stratux-v2.0-pre4/image_build
rm -rf pi-gen/work pi-gen/deploy pi-gen/stratux
./build.sh
```

Expected artifacts:

- `pi-gen/deploy/image_YYYY-MM-DD-stratux-lite.zip`
- `pi-gen/deploy/YYYY-MM-DD-stratux-lite.info`

Example successful output artifact:

- `image_2026-05-27-stratux-lite.zip`

---

## 6. Copy artifact into project workspace

Optional, but convenient for tracking:

```bash
cp /tmp/stratux-v2.0-pre4/image_build/pi-gen/deploy/image_2026-05-27-stratux-lite.zip "/Users/stevenmogg/Documents/Software_Projects/Cozy_Aircraft_Data System/stratux-v2.0-pre4-image.zip"
```

---

## 7. Flashing and first boot

1. Unzip the build artifact.
2. Open Raspberry Pi Imager.
3. Choose **Use custom** and select the generated `.img`.
4. Select target microSD and write.
5. Boot Pi and connect to Stratux Wi-Fi.
6. Open `http://192.168.10.1`.

---

## 8. Important imaging constraint (confirmed)

For this build flow, imaging has been reliable only when you **do not apply custom OS settings in Raspberry Pi Imager**.

In practice:

- Prefer plain flash with no imager-time customizations.
- If customization is needed, apply it after first boot through Stratux UI and/or SSH.

---

## 9. Post-boot baseline for 1090-only testing

For initial single-receiver 1090 testing:

- Enable 1090 / ES receiver
- Disable OGN/FLARM-related options (until hardware exists)
- Keep setup minimal and validate traffic reception first

---

## 10. Local network defaults in this codebase

This repository now bakes in these defaults for new images:

- `eth0` static management IP: `192.168.50.2/24`
- Stratux AP on `ap0`: `192.168.10.1/24`
- Optional secondary uplink on `wlan1` (USB Wi-Fi dongle):
  - DHCP client
  - hotspot credentials read from `/etc/wpa_supplicant/wpa_supplicant-wlan1.conf`
  - AP-to-uplink forwarding/NAT rules applied on `wlan1` up/down

Related templates/files:

- `image_build/stage2/10-stratux/files/interfaces`
- `debian/interfaces.template`
- `image_build/stage2/10-stratux/files/wpa_supplicant_wlan1.conf`
- `debian/wpa_supplicant_wlan1.conf.template`

Current hotspot configuration policy in this repo:

- Primary uplink hotspot block is enabled by default in templates
- Optional fallback hotspot block is present but commented out
- Credentials are placeholder values and must be updated after flash or in private local builds

---

## 11. Fallback option

If local builds are blocked, use the official release image:

- [Stratux releases](https://github.com/stratux/stratux/releases)

This allows bench testing while local build tooling is fixed.
