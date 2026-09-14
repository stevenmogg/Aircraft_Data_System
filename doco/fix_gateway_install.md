# FIX-Gateway install (Phase 2)

MakerPlane **FIX-Gateway** is the central avionics data backbone on the Stratux Pi.

## Runtime layout

| Item | Path / value |
|------|----------------|
| Install root | `/cozy-data-system/venv/` |
| Config | `/cozy-data-system/config/fixgw/` |
| Preferences (Cozy) | `/cozy-data-system/config/fixgw/preferences.yaml.custom` |
| Systemd unit | `fixgateway.service` (enabled) |
| NetFIX listen | `0.0.0.0:3490` |
| Binary | `/cozy-data-system/venv/bin/fixgw` |
| Client | `/cozy-data-system/venv/bin/fixgwc` |

## Status commands

```bash
ssh stratux 'systemctl status fixgateway --no-pager'
ssh stratux 'ss -tlnp | grep 3490'
ssh stratux 'sudo journalctl -u fixgateway -n 50 --no-pager'
```

## Cozy defaults

In `preferences.yaml.custom`:

- `NETFIX: true` — network clients can connect on port 3490
- `DEMO: false` — no simulated flight data
- `STRATUX: true` — Stratux → FIX via HTTP `/getSituation` (`connections/stratux_http.yaml`)
- Publishes AHRS always; publishes GPS (`LAT`/`LONG`/`GS`/`TRACK`/…) when Stratux has a fix
- `MGL_AIRTALK: true` — Nano USB Airtalk → `MGL_AT_*` (does not overwrite Stratux `PITCH`/`ROLL`/`HEAD`). FIX-Gateway owns the Nano USB port; `/debug/mgl/airtalk` Watch/Observed/Interface follow FIX.
- `MGL_CAN: true` — SocketCAN `can0` RDAC → `MGL_RDAC_*` (receive-only). Stock `MGL` plugin stays **off** (it can transmit).
- `MGL_NMEA: true` — MGL Extreme NMEA 0183 on GPIO UART `/dev/serial0` @ 19200 → `MGL_NMEA_*` (does not overwrite Stratux `LAT`/`LONG`). Stratux GPS is USB. Keep `GPSD: false`.
- `MGL_SERVO: true` — virtual MGL bank/pitch servos on `can0` → `MGL_SRV_*`. Listen-only until `allow_tx` and `tx_armed` in `connections/mgl_servo.yaml`. Stock `MGL` plugin stays **off**. See [mgl_servo.md](mgl_servo.md).
- Database keys: `config/fixgw/database.yaml` and `config/fixgw/database/`

## Units (store at ingest)

FIX YAML `units` is the source of truth. Convert on the way **into** the database, not on every UI extract.

| Source | FIX keys | Stored as |
|--------|----------|-----------|
| Stratux `/getSituation` | `PALT`, `ALT`, `GPS_ELLIPSOID_ALT` | feet (Stratux already reports GPS MSL in feet) |
| Extreme GGA | `MGL_NMEA_ALT`, `MGL_NMEA_GEOID` | feet (metres on the wire, converted in `mgl_nmea.parse_line`) |
| RDAC thermocouples | `MGL_RDAC_TCn` | compensated °F = (wire °C + `MGL_RDAC_TEMP` °C) then °F |
| RDAC cold junction | `MGL_RDAC_TEMP` | °F |

CAN debug (`/debug/mgl/can`) still shows wire °C. Live and Historian use FIX.

### Stratux → FIX (AHRS + GPS)

Stock MakerPlane GDL90 Stratux plugin only gets real pitch/roll when Stratux has a valid GPS fix (Stratux `isAHRSValid`). Without GPS, GDL90 sends invalid sentinels.

Cozy uses `fix_gateway_plugins/cozy_stratux_http`, which polls `http://127.0.0.1/getSituation` and writes:

- AHRS: `PITCH`, `ROLL`, `HEAD`, `ALAT`, baro `PALT` / `VS`
- GPS (when fix quality ≥ 1): `LAT`, `LONG`, `GS`, `TRACK`, `ALT` (GPS MSL), sats / accuracy keys

```bash
# AHRS
ssh stratux '/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read PITCH"'
ssh stratux '/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read ROLL"'

# GPS (when Stratux USB GPS has a fix)
ssh stratux '/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read LAT"'
ssh stratux '/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read LONG"'
ssh stratux '/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read GS"'
```

Compare with Stratux:

```bash
ssh stratux 'curl -s http://127.0.0.1/getSituation | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[\"AHRSPitch\"],d[\"AHRSRoll\"],d.get(\"GPSLatitude\"),d.get(\"GPSFixQuality\"))"'
```

## Offline install (no Pi internet)

Stratux’s 250MB overlay cannot hold FIX-Gateway. Install into the persistent root (`/overlay/robase`) via:

1. Build/download aarch64 wheels on the Mac (see `scripts/setup_fix_gateway.sh`)
2. Copy wheels to the Pi
3. Create venv under `/cozy-data-system/venv` on **robase**
4. Enable `fixgateway.service`

If the overlay upper layer shadows `/cozy-data-system`, copy onto robase with `sudo /cozy-data-system/scripts/persist_cozy_to_robase.sh` (this image often already has robase mounted RW, so `overlayctl unlock` can report busy). Reboot after a first-time venv install on robase if the live view is empty.

## Related

- Stage 1 roadmap: [cozy_aircraft_data_system_stage1.md](cozy_aircraft_data_system_stage1.md) Phase 2
- Upstream: https://github.com/makerplane/FIX-Gateway
