# FIX-Gateway database (Cozy copy)

`../database.yaml` is the include index. On the Pi the same files live at
`/cozy-data-system/config/fixgw/`.

FIX key names cannot contain `.` — a dotted name is treated as auxiliary
data on another key. Source-specific Cozy keys use underscores
(`MGL_AT_PITCH`, `MGL_RDAC_RPM1`).

Stock MakerPlane files (`generic.yaml`, `ahrs.yaml`, `engine.yaml`,
`com_radio.yaml`, `trims.yaml`, `mavlink.yaml`, `control.yaml`,
`misc.yaml`, `tires.yaml`) are **not loaded**. Stratux GPS/AHRS keys that
we still write live in `stratux.yaml`.

## Files

| File | Written by | Notes |
|------|-----------|--------|
| `variables.yaml` | — | Suffix expansion (`n` for QVOTE) |
| `stratux.yaml` | `cozy_stratux_http` | `STRX_PITCH` `STRX_ROLL` `STRX_HEAD` `STRX_LAT` `STRX_LONG` `STRX_GS` `STRX_ALT` `STRX_PALT` `STRX_VS` `STRX_TRACK` `STRX_ALAT` |
| `system.yaml` | FIX-Gateway | Time, battery, quorum |
| `mgl_airtalk.yaml` | `cozy_mgl_airtalk` | `MGL_AT_*`. Canonical attitude stays Stratux. |
| `mgl_rdac.yaml` | `cozy_mgl_can` | Raw RDAC. TC stored as compensated °F. |
| `mgl_nmea.yaml` | `cozy_mgl_nmea` | Extreme NMEA. Altitude stored as feet. |
| `mgl_servo.yaml` | `cozy_mgl_servo` | Autopilot servo emulator |
| `custom.yaml` | — | One-off keys only |
| `last.yaml` | — | `ZZLOADER` (must stay last) |

Historian capture lists every remaining FIX key in
`config/historian/historian.yaml`, including description, units, and limits.
