# Flight plan file share (Phase 1)

AvPlan on iPad or iPhone can export flight plans into a folder on the Stratux Pi over Wi‑Fi using **SMB** (standard for iOS Files app).

## On the Pi

| Item | Value |
|------|--------|
| Share name | `cozy-data` |
| Path | `/cozy-data-system/data/` |
| Flight plans | `/cozy-data-system/data/flight-plans/` |
| Server (cockpit Wi‑Fi) | `192.168.10.1` |
| Server (management Ethernet) | `192.168.50.2` |
| Username | `pi` |
| Password | Same as SSH (default image: `raspberry`) |

Full URL: `smb://192.168.10.1/cozy-data`

When the Pi has internet via phone hotspot, devices on the Stratux AP (`192.168.10.x`) still reach the share at `192.168.10.1`.

### Live Pi without a rebuilt image

Stratux keeps runtime changes in a **250MB overlay**. Samba cannot be installed with `apt` on a running unit without internet and overlay space. Use `scripts/setup_cozy_smb_share.sh` with an offline `.deb` bundle, or flash a new image that includes Samba (see `stratux-master/image_build/stage2/10-stratux/01-run.sh`).

## iPad / iPhone — connect once

1. Join **Stratux** Wi‑Fi (cockpit AP).
2. Open **Files**.
3. **Browse** → **⋯** (top right) → **Connect to Server**.
4. Server: `smb://192.168.10.1` or `192.168.10.1`.
5. Choose **Registered User** (not Guest) → **Name** `pi`, **Password** (your Pi password).
6. Open share **cozy-data** → folder **flight-plans**.

If the share appears read-only, disconnect and reconnect as **Registered User** with password `raspberry` (or your Pi SSH password). Guest mode is not enabled on this share.

iOS needs Samba **fruit** VFS extensions (included in the image). After changing Samba config, reboot the Pi or run `sudo pkill smbd; sudo smbd`.

## AvPlan — send a flight plan

1. In AvPlan, open the flight plan → **Share** / **Export**.
2. Choose **Save to Files** (or share sheet → Files).
3. Navigate to **cozy-data** → **flight-plans** → save.

Supported formats depend on AvPlan export options (e.g. GPX, PDF, vendor formats).

## Verify from Mac (management Ethernet)

```bash
ssh stratux 'ls -la /cozy-data-system/data/flight-plans/'
```

Or mount SMB from Finder: **Go → Connect to Server** → `smb://192.168.50.2/cozy-data` (wired management IP).

## Related docs

- [cozy_aircraft_data_system_stage1.md](cozy_aircraft_data_system_stage1.md)
- [stratux_local_customizations.md](stratux_local_customizations.md)
