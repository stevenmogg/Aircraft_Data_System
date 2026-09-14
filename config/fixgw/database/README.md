# FIX-Gateway database (Cozy copy)

This folder is the project copy of every FIX key FIX-Gateway will load.

`../database.yaml` is the include index. On the Pi the same files live at
`/cozy-data-system/config/fixgw/`.

FIX key names cannot contain `.` — a dotted name is treated as auxiliary
data on another key. Source-specific Cozy keys use underscores
(`MGL_AT_PITCH`, `MGL_RDAC_RPM1`).

## Stock files (MakerPlane)

These define the generic aircraft namespace. Keys exist whether or not a
plugin is writing them. They are readable over NetFIX (`:3490`) and
`fixgwc --execute "read KEY"`.

| File | Contents |
|------|----------|
| `variables.yaml` | Engine/cylinder counts used to expand `%e` / `%c` keys |
| `generic.yaml` | Analog / button / encoder placeholders |
| `ahrs.yaml` | `PITCH` `ROLL` `HEAD` `LAT` `GS` `ALT` … |
| `engine.yaml` | `TACH1` `OILT1` `EGT11` `CHT11` `MAP1` … (canonical engine) |
| `com_radio.yaml` | COM/NAV radios |
| `trims.yaml` | Trim positions |
| `mavlink.yaml` | Mavlink extras |
| `system.yaml` | Gateway / system |
| `control.yaml` | Control surfaces |
| `misc.yaml` | Misc |
| `tires.yaml` | Tire pressure |
| `last.yaml` | `ZZLOADER` (must stay last) |

## Cozy source files

| File | Written by | Notes |
|------|-----------|--------|
| `mgl_airtalk.yaml` | `cozy_mgl_airtalk` (Nano USB) | Live. Canonical `PITCH`/`ROLL`/`HEAD` stay Stratux. |
| `mgl_rdac.yaml` | `cozy_mgl_can` (SocketCAN `can0`) | Raw RDAC. Not mapped to `TACH1`/`EGT11` until calibrated. |
| `custom.yaml` | — | One-off keys only |

## Captured vs available

**Available via API / NetFIX:** every key in this folder (after FIX-Gateway
starts).

**Captured to the historian SQLite file:** only the maps in
`config/historian/historian.yaml` (`fast_signals` / `slow_signals`). Today
that is Stratux/FIX AHRS and GPS, not MGL Airtalk or RDAC.

RDAC values appear in FIX only when Linux has `can0` and the MGL CAN plugin
is receiving frames. MCP2515 probe failure means keys exist but stay stale.
