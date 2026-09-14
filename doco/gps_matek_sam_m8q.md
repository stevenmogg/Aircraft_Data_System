# Matek SAM-M8Q GPS on Raspberry Pi GPIO UART (Stratux)

GPS only (compass not used). **Live aircraft node:** Stratux GPS is the USB u-blox (`ttyACM1`). GPIO `/dev/serial0` is owned by FIX plugin `cozy_mgl_nmea` (MGL Extreme @ 19200). This page is the Matek wiring note if that module is used later.

FIX reads Stratux GPS via `cozy_stratux_http` (`GpsManualConfig` is **false** so Stratux does not open `serial0`).

**Status (live Pi):** USB GPS feeds Stratux `/getSituation`. Extreme NMEA alt is stored in FIX as feet (`MGL_NMEA_ALT`).

## Wiring

| Matek Pin | Cable Colour | Function | Raspberry Pi GPIO | Pi Physical Pin | Notes |
| --------- | ------------ | ------------------------- | ----------------- | ---------------------- | --------------------------------- |
| **5V** | **Red** | Power (4–6 V input) | 5 V | Pin **2** or **4** | Required |
| **G** | **Black** | Ground | GND | Pin **6** (or any GND) | Required |
| **RX** | **Yellow** | GPS UART Receive | **GPIO14 (TXD0)** | Pin **8** | Connect to Pi TX |
| **TX** | **Blue** | GPS UART Transmit | **GPIO15 (RXD0)** | Pin **10** | Connect to Pi RX |
| **DA** | **White** | I²C SDA (QMC5883 Compass) | **GPIO2 (SDA1)** | Pin **3** | Not connected (optional — see below) |
| **CL** | **Green** | I²C SCL (QMC5883 Compass) | **GPIO3 (SCL1)** | Pin **5** | Not connected (optional — see below) |

Cross UART: Matek TX → Pi RX, Matek RX → Pi TX. Power from Pi **5 V**, not 3.3 V.

**Compass (DA / CL):** Not wired in the Cozy installation. They **could** share the Stratux AHRS I²C bus (pins 3/5) if needed later — addresses do not clash:

| Device | I²C address (7-bit) | Notes |
|--------|---------------------|--------|
| ICM-20948 (Stratux AHRS IMU) | **0x68** (alt 0x69) | Already on the bus |
| BMP280 (Stratux baro) | **0x76** | Already on the bus |
| AK09916 (mag inside ICM-20948) | **0x0C** | Internal / bypass; not the Matek chip |
| QMC5883L (Matek compass) | **0x0D** | Matek DA/CL |

Stock Stratux does not use QMC5883 today (AHRS mag heading is unused pending calibration anyway), so leave DA/CL disconnected unless you add software for it.

## Stratux config

Live image uses USB GPS, so **do not** set `GpsManualConfig` true (that would steal `/dev/serial0` from Extreme NMEA):

```json
"GPS_Enabled": true,
"GpsManualConfig": false
```

Templates: `debian/stratux.conf.default` and `image_build/.../stratux.conf.default`. Fill Wi‑Fi client passwords on the Pi only (`CHANGE_ME` in git).

If Matek is later wired to the GPIO UART **instead of** Extreme NMEA, then:

```json
"GpsManualConfig": true,
"GpsManualDevice": "/dev/serial0",
"GpsManualChip": "ublox8",
"GpsManualTargetBaud": 115200
```

`/dev/serial0` → `ttyAMA0` on this image. Chip `ublox8` matches SAM-M8Q (u-blox M8).

```bash
sudo systemctl restart stratux
```

## FIX

`STRATUX: true` with `connections/stratux_http.yaml` polls `/getSituation` and publishes:

- `LAT`, `LONG`, `GS`, `TRACK`
- `ALT` (GPS MSL when fix; else baro), `PALT` (baro)
- `GPS_FIX_TYPE`, `GPS_SATS_TRACKED`, accuracies when present

Keep `GPSD: false`. Stratux USB GPS does not use this UART; Extreme NMEA does.

Historian samples `LAT` / `LONG` / `GS` / `TRACK` / `ALT` / `PALT` at 10 Hz when recording.

## Verify

```bash
# Stratux
curl -s http://127.0.0.1/getStatus | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('GPS_connected'),d.get('GPS_detected_type'),d.get('GPS_solution'))"
curl -s http://127.0.0.1/getSituation | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('GPSLatitude'),d.get('GPSLongitude'),d.get('GPSFixQuality'),d.get('GPSSatellitesTracked'))"

# FIX
sudo systemctl start fixgateway
/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read LAT"
/cozy-data-system/venv/bin/fixgwc --host 127.0.0.1 --port 3490 --execute "read LONG"
```

Cold start outdoors may take 30–90 s for first fix. Antenna needs sky view.

## Related

- [fix_gateway_install.md](fix_gateway_install.md)
- [stratux_local_customizations.md](stratux_local_customizations.md)
