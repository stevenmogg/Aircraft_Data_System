# Cozy Aircraft Data System
## System Specification – Stage 1 (Revised)
**Distributed Avionics Data System with FIX-Gateway Core**

**See also:** [Development environment — Mac workstation and Raspberry Pi](development_environment.md) · [Stratux build and imaging workflow](stratux_build_and_imaging.md) · [Stratux local customizations](stratux_local_customizations.md)

---

# 1. Purpose and Scope

Design and implement a **non-essential, advisory-only distributed avionics data system** that:

- Uses a **standardised aircraft data model (FIX)**
- Provides a **unified aircraft Wi-Fi network**
- Runs **Stratux for ADS-B / GPS / AHRS**
- Logs flight data automatically
- Displays system status via cockpit touchscreen
- Uploads data to cloud
- Forms the foundation for a **distributed CAN-based sensor network**

---

# 2. Architectural Philosophy

The system follows a **distributed avionics model**:

- Data is **produced by independent modules**
- Data is **transported over a common bus (future CAN)**
- Data is **centralised logically, not physically**, via FIX-Gateway
- Displays and loggers are **consumers, not owners**

---

# 3. Safety Boundary

The system shall:

- Be **non-essential**
- Have **no control authority**
- Operate **in parallel** with existing avionics
- Not interfere with:
  - engine instrumentation
  - autopilot
  - radios
  - transponder

Failure results in:

- Loss of logging and display only

---

# 4. System Overview

                  (Future CAN Bus Backbone)
                          |
     -------------------------------------------------
     |              |              |                |
 Sensor Nodes   Engine Node   Control Node   Vibration Node
     |
     v
               FIX-Gateway (central data model)
                         |
          -----------------------------------------
          |               |           |            |
      Stratux         Logger     Dashboard    Uploader
   (ADS-B/GPS/AHRS)                  |
                                     v
                          Touchscreen / iPad

---

# 5. Core Components

## 5.1 Raspberry Pi 5 (Central Node)

Runs:

- FIX-Gateway (**core data system**)
- Stratux (**ADS-B / GPS / AHRS provider**)
- Wi-Fi Access Point
- Logging service (Historian via FIX)
- Cloud uploader (future)
- Web dashboard (FastAPI on `:8080`)

### Role:

- Data **gateway**
- Data **aggregator**
- Data **distributor**
- Not a real-time acquisition device

For how the codebase is edited on the Mac, deployed over SSH, and when to use a remote editor session on the Pi, see [development_environment.md](development_environment.md).

---

## 5.2 FIX-Gateway (Core System)

FIX-Gateway is the **central data backbone**:

- Maintains aircraft-wide data dictionary
- Stores:
  - values
  - units
  - validity
  - limits
  - status flags
- Enables:
  - multiple producers
  - multiple consumers
  - clean system expansion

All system components interact through FIX.

---

## 5.3 Stratux Integration

Stratux runs on the Pi and provides:

- ADS-B traffic
- GPS position
- AHRS attitude (if installed)

A **Stratux → FIX adapter** (`cozy_stratux_http`) polls Stratux `/getSituation` and maps:

- AHRS: pitch, roll, heading, slip → FIX
- Baro: pressure altitude, vertical speed → FIX (`PALT` / `VS`, feet / fpm)
- GPS (when fix valid): lat, lon, gs, track, GPS altitude → FIX (`ALT` is Stratux MSL **feet**)

MGL Extreme NMEA and RDAC are separate FIX plugins. See [gps_matek_sam_m8q.md](gps_matek_sam_m8q.md) and [fix_gateway_install.md](fix_gateway_install.md).

---

<a id="cockpit-network"></a>

## 5.4 Cockpit Network

### Wi-Fi

- Pi acts as **Access Point**
- Provides:
  - Stratux feed to AvPlan
  - FIX/dashboard access

### Connected devices:

- iPad (AvPlan)
- iPhone (internet gateway)
- Pi touchscreen

### Constraint

Stratux traffic feed must remain stable at all times.

---

## 5.5 Touchscreen / browser dashboard (FastAPI)

### Role

- System display only
- No critical logic
- Served by `cozy-web.service` on port **8080** ([cozy_web_install.md](cozy_web_install.md))

### Displays

- LIVE instruments + recording controls
- FLIGHTS catalogue + External Data (MGL card status)
- CONFIGURATION (Wi‑Fi / aircraft / signals)
- ANALYSIS plot + CSV export
- GPS / ADS-B / FIX / Historian health via `/api/status`

---

## 5.6 Logging System (Historian)

Logging is implemented as a **FIX consumer** ([historian_install.md](historian_install.md)).

### Behaviour

- `cozy-historian.service` starts on boot but stays **idle until Start**
- records FIX data at 10 Hz (fast) / 1 Hz (slow) into durable SQLite
- MARK events via control socket / web UI
- does **not** auto-arm a flight on power-up

### Data Source

- all sampled values come from FIX

---

## 5.7 File Storage

### Historian

- SQLite: `/cozy-data-system/data/historian/cozy_historian.sqlite` (bind-mounted from robase)

### Flight plans / MGL exchange

- Plans: `/cozy-data-system/data/flight-plans/` (SMB + MGL card sync)
- MGL inbox: `/cozy-data-system/data/mgl-inbox/` (`ENIGMA_LATEST.REC`, `XTFLIGHT_LATEST.CSV`)

---

## 5.8 Cloud Upload

- runs as independent service
- monitors new log files
- uploads when internet available
- retries on failure

---

# 6. Data Flow Model

Data Source → FIX-Gateway → Consumers

---

# 7. CAN Bus Strategy (Future)

CAN bus is the **standard for all new sensors**.

---

# 8. Legacy Avionics Integration (Future)

Potential integrations:

- GNC-300 (RS-232 GPS data)
- autopilot source logging
- ARINC data investigation

---

# 9. Startup Behaviour

On aircraft power:

1. Pi boots
2. Stratux starts (ADS-B / AHRS / GPS when receiver connected)
3. FIX-Gateway starts (`fixgateway.service`)
4. Stratux HTTP adapter feeds FIX
5. Historian daemon is idle until Start
6. Wi-Fi / SMB available
7. Web UI on `:8080`

---

# 10. Failure Modes

| Failure | Effect |
|--------|--------|
| Pi failure | loss of entire system |
| FIX failure | no data distribution |
| Stratux failure | no GPS/traffic |
| Wi-Fi failure | no iPad connectivity |
| logging failure | no recorded data |
| cloud failure | data retained locally |

---

# 11. Installation

- Panel-mounted Pi + touchscreen
- dedicated 12V → 5V supply
- system labelled **non-essential**

Engineering workflow from a Mac (repo on workstation, deploy over SSH): [development_environment.md](development_environment.md).

---

<a id="development-roadmap"></a>

# 12. Development Roadmap

Workflow (local Mac repo, Pi deploy, optional Remote SSH): [development_environment.md](development_environment.md).

## Phase 1 — **done**
- Pi + Stratux stable
- Wi-Fi working (AP + client uplink)
- AvPlan connected
- **Flight plan file share:** SMB share `cozy-data` on `/cozy-data-system/data/flight-plans/` ([flight_plan_file_share.md](flight_plan_file_share.md))
- MGL SD-card exchange: plans out, Enigma/XTFLIGHT in ([mgl_card_install.md](mgl_card_install.md))

## Phase 2 — **done**
- FIX-Gateway installed ([fix_gateway_install.md](fix_gateway_install.md)) — `fixgateway.service`, NetFIX `:3490`

## Phase 3 — **done (AHRS + GPS path)**
- Stratux → FIX via `cozy_stratux_http` (AHRS always; GPS when Stratux has a fix)
- Live Stratux GPS is the USB u-blox (`ttyACM1`). GPIO `/dev/serial0` is MGL Extreme NMEA (`MGL_NMEA_*`), not Matek. Wiring notes: [gps_matek_sam_m8q.md](gps_matek_sam_m8q.md)

## Phase 4 — **done (capture core)**
- Historian from FIX ([historian_install.md](historian_install.md)) — durable SQLite, 10/1 Hz, idle-until-start, MARK
- Still pending: Enigma / AvPlan **importers** into Historian

## Phase 5 — **done (MVP web UI)**
- Aircraft web UI ([cozy_web_install.md](cozy_web_install.md)) — FastAPI `:8080`, LIVE WS, flights, config, analysis/CSV, External Data status
- Still pending: Enigma/AvPlan import UI (blocked on Phase 4 importers)

## MGL ingest — **live on the aircraft Pi**
- Airtalk Nano USB → FIX `MGL_AT_*` (`cozy_mgl_airtalk`). Web `/debug/mgl/airtalk` Watch/Observed/Interface follow that FIX feed.
- Extreme NMEA on `/dev/serial0` @ 19200 → `MGL_NMEA_*` (altitudes stored in **feet**)
- MCP2515 `can0` @ 250 kbit/s → RDAC `MGL_RDAC_*` (CHT/EGT stored as compensated **°F**)
- Servo emulator `MGL_SERVO` (TX armed separately): [mgl_servo.md](mgl_servo.md)
- CAN notes: [mgl_can_install.md](mgl_can_install.md)

## Phase 6 — **not started**
- cloud upload

---

<a id="software-structure"></a>

# 13. Software Structure

On the Raspberry Pi, mirror this tree at your chosen deploy path (see [development_environment.md](development_environment.md)).

/cozy-data-system
    /fix_gateway_plugins   # cozy_stratux_http, cozy_mgl_can/airtalk/nmea/servo
    /historian
    /web
    /scripts               # setup_*, persist_cozy_to_robase, sync_cozy_into_stratux_image
    /navigation            # AvPlan → MGL ERT
    /hardware              # Nano Airtalk firmware, etc.
    /data
        /flight-plans
        /historian
        /mgl-inbox
    /config
        /fixgw
        /historian
        /mgl_card
        /mgl_can
        /systemd
        /udev

---

# 14. Key Design Rules

1. All data flows through FIX
2. Pi is not a real-time acquisition device
3. Logging must not depend on network
4. System must auto-start
5. All future expansion via CAN
6. FIX stores canonical aircraft units at ingest (feet, °F, knots). YAML `units` is the contract; Live/Historian display what FIX holds.

---

# 15. Strategic Outcome

- scalable avionics data platform
- distributed sensor network
- supports future engine monitoring and flight testing

---

# Next Step

1. Rebuild a Stratux image when you want a fresh SD card (`scripts/sync_cozy_into_stratux_image.sh` is invoked from `image_build/build.sh`).
2. Implement Historian Enigma / AvPlan importers; then wire Phase 5 import UI.
3. Phase 6 cloud upload when local capture/import is solid.

**Documentation:** [Development environment — Mac workstation and Raspberry Pi](development_environment.md).

---

## Stage 1 implementation status

Implemented on the live Pi / repo baseline:

- Stratux build and image workflow validated and documented
- Stable wired management network (`eth0` static `192.168.50.2`)
- Stratux AP (`ap0` on `192.168.10.1`) + AP+Client uplink (WiFiMode 2)
- HDMI 480×320 console
- SMB flight-plan share (`cozy-data`)
- FIX-Gateway (`fixgateway.service`, NetFIX `:3490`)
- Stratux → FIX HTTP adapter (AHRS + GPS keys)
- Matek GPS Stratux config (`GpsManualConfig` / `ublox8` / `/dev/serial0`)
- Pi 5 FAN header thermal curve (`dtparam=fan_temp*`; Stratux GPIO fancontrol not used)
- Historian (durable SQLite, idle-until-start, MARK)
- Web UI (`cozy-web.service` `:8080`, twisty pages, External Data)
- MGL card sync (udev insert/remove, plans watch, `_LATEST` inbox)
- MGL Airtalk → FIX `MGL_AT_*`; Extreme NMEA → `MGL_NMEA_*` (alt ft); RDAC → `MGL_RDAC_*` (°F compensated)
- MCP2515 `can0` at 250 kbit/s (SPI max 500 kHz overlay in `config.txt`)
- Cozy source baked into the Stratux image via `scripts/sync_cozy_into_stratux_image.sh`

Not done yet:

- GPS outdoor cross-check vs Extreme (USB Stratux GPS is live on the bench)
- Enigma / AvPlan Historian importers + web import UI
- Cloud upload (Phase 6)
- CAN sensor nodes beyond RDAC ingest / servo emulator

Reference: [stratux_build_and_imaging.md](stratux_build_and_imaging.md) · [fix_gateway_install.md](fix_gateway_install.md) · [gps_matek_sam_m8q.md](gps_matek_sam_m8q.md) · [historian_install.md](historian_install.md) · [cozy_web_install.md](cozy_web_install.md) · [mgl_card_install.md](mgl_card_install.md)
