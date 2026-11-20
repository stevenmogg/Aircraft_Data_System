# Cozy Aircraft Data System — agent briefing

**Aircraft:** Cozy III, registration **VH-COZ**, historian id **COZ**  
**Date of this briefing:** 20 November 2026  
**Audience:** Research agents (Grokbot and others) who do not have this chat history  
**Source of truth:** This Mac git working tree. The Raspberry Pi is the runtime, not the archive.

Read this file first. Then open the cited document in `doco/`. Then look at the code. If a specification and the code disagree, say so. Prefer the code and the newest install note, and do not silently “correct” the aircraft to match an older paragraph.

This system is **advisory**. It logs and displays. It does not fly the aeroplane.

---

## 1. What this project is

A non-essential data system on a **Raspberry Pi 5** that already runs **Stratux**. It sits beside the installed **MGL XTreme** avionics on VH-COZ. It collects ADS-B, GPS, AHRS, and taps of the existing MGL buses, stores them as one current-state model, and records flights for later analysis.

The pilot’s primary instruments, autopilot, radios, and transponder stay the installed avionics. If this Pi stops, those continue.

The long-term shape is a small avionics data platform:

- one current-state model (**FIX-Gateway**, from MakerPlane)
- many producers (Stratux, MGL taps, future CAN nodes)
- many consumers (Historian, web UI, a future uploader)
- post-flight enrichment (AvPlan, MGL Enigma, FlySto) laid onto the flight that was already recorded

---

## 2. How the pieces fit

```text
Installed MGL XTreme  (operational avionics — do not disturb)
        |  passive taps only
        |  Airtalk (Nano USB)   NMEA (GPIO UART)   CAN (MCP2515 can0)
        v
Stratux on the same Pi  (ADS-B, USB GPS, AHRS, cockpit Wi-Fi)
        |
        v
FIX-Gateway  :3490     current aircraft state, canonical units
        |                         \
        v                          v
Historian (SQLite on SD)      cozy-web  :8080
10 Hz / 1 Hz samples          live display, flights, analysis
idle until the pilot starts   independent process
```

| Process | Unit | Role |
|---------|------|------|
| Stratux | `stratux.service` | ADS-B, GPS, AHRS, access point |
| FIX-Gateway | `fixgateway.service` | Current-state database. NetFIX on `0.0.0.0:3490` |
| Historian | `cozy-historian.service` | Samples FIX into SQLite. **Idle until Start** |
| Historian storage | `cozy-historian-data.service` | Bind-mounts the database onto the SD card |
| Web UI | `cozy-web.service` | FastAPI on port **8080**. Reads FIX and SQLite. Does not record the flight |

Deploy root on the Pi: `/cozy-data-system`.  
Python venv and `fixgw` binary: `/cozy-data-system/venv`.

---

## 3. Where you are allowed to look

| Path | What it is |
|------|------------|
| `doco/` | Specifications and install notes. Start here for intent. |
| `fix_gateway_plugins/` | Our FIX producers: Stratux HTTP, MGL CAN, Airtalk, NMEA, servo emulator |
| `config/fixgw/` | FIX database keys, units, and plugin connection YAML |
| `config/historian/` | Sample rates and aircraft seed (`COZ` / `VH-COZ`) |
| `historian/` | Recorder, schema, AvPlan GPX importer |
| `web/` | FastAPI UI |
| `navigation/` | AvPlan GPX → MGL Extreme `.ert` / `WAYPOINT.EWD` |
| `hardware/` | Nano Airtalk firmware, Pico UART bridge |
| `scripts/` | Image sync, Pi setup, persist-to-SD |
| `stratux-master/` | Local Stratux tree with our image customizations |
| `fix-gateway-master/` | Upstream MakerPlane FIX-Gateway, vendored for reference |

Do not treat `stratux-master/README.md` or `fix-gateway-master/README.md` as the project plan. They describe the upstream projects we build on.

Authoritative project documents:

| Question | Document |
|----------|----------|
| Whole-system intent, phases, design rules | `doco/cozy_aircraft_data_system_stage1.md` |
| How we develop (Mac repo, SSH to the Pi) | `doco/development_environment.md` |
| Stratux image and network defaults | `doco/stratux_build_and_imaging.md`, `doco/stratux_local_customizations.md` |
| FIX install and unit rules | `doco/fix_gateway_install.md` |
| Historian | `doco/Phase 4 Loggingfrom FIX - Specification.md`, `doco/historian_install.md` |
| Web UI | `doco/Phase 5 Aircraft Web UI - Specification.md`, `doco/cozy_web_install.md` |
| MGL CAN | `doco/MGL_CAN_to_FIX_Strategy_and_Specification_v2.md`, `doco/mgl_can_install.md` |
| MGL Airtalk | `doco/MGL_Airtalk_to_Pi_Data_Collector_Interface_v2.md` |
| MGL NMEA / GPS wiring notes | `doco/gps_matek_sam_m8q.md` |
| Servo emulator and its test plan | `doco/mgl_servo.md`, `doco/Pi_MGL_Servo_Emulator_Specification_and_Test_Plan.md` |
| Stick encoders on the Nano | `doco/Cozy_Pitch_Roll_Encoder_Nano_Interface.md`, `doco/Nano_Encoder_Implementation_Plan.md` |
| Flight-plan share and MGL card | `doco/flight_plan_file_share.md`, `doco/mgl_card_install.md` |
| FlySto (specified, not built) | `doco/FlySto_Flight_Analysis_Importer_Specification.md` |

`doco/cozy_aircraft_data_system_stage1.md` is the roadmap, and parts of its “not done” list are behind the code. As of this briefing, AvPlan GPX merge exists in `historian/importers/avplan_gpx.py` and on the Flights page. Enigma `.rec` import and cloud upload do not.

---

## 4. What is already built

### Phase 1 — Pi, Stratux, cockpit network

Done and flying as the baseline image.

- Stratux image builds from `stratux-master/`, with Cozy files baked in by `scripts/sync_cozy_into_stratux_image.sh`.
- Management Ethernet `eth0` static **192.168.50.2**. SSH alias `stratux`.
- Cockpit access point `ap0` at **192.168.10.1**. AvPlan uses this.
- Onboard `wlan0` can join a phone hotspot (Stratux WiFiMode 2) and NAT clients. Optional USB `wlan1` is a second uplink.
- Home LAN reservation **10.0.0.41**, SSH alias `stratux-wifi`.
- HDMI console **480×320**. Pi 5 fan curve is in the device tree, not Stratux’s GPIO fan controller.
- SMB share `cozy-data` serves `/cozy-data-system/data/flight-plans/`.
- MGL SD card: plans copied out to the card; `ENIGMA.REC` and XTFLIGHT CSV copied into `/cozy-data-system/data/mgl-inbox/`.
- AvPlan GPX flight plans convert to MGL Extreme route files (`navigation/avplan_to_mgl.py`).

### Phase 2 — FIX-Gateway

Done. MakerPlane FIX-Gateway is the only current-state store. `DEMO` is off. Clients use NetFIX port 3490.

### Phase 3 — Stratux into FIX

Done via `fix_gateway_plugins/cozy_stratux_http`. It polls Stratux `http://127.0.0.1/getSituation`.

- AHRS always: pitch, roll, heading, lateral accel, pressure altitude, vertical speed.
- GPS when Stratux fix quality is at least 1: lat, lon, groundspeed, track, GPS altitude.
- Live GPS is the **USB u-blox** (`ttyACM1`). GPIO `/dev/serial0` is **not** that GPS. It is MGL Extreme NMEA.

The stock MakerPlane GDL90 Stratux path is not what we use. It only emits valid AHRS when GPS is valid.

### MGL ingest — live on the aircraft Pi

Four of our plugins, all writing **source-specific** FIX keys so they can be compared with Stratux:

| Plugin | Bus | FIX prefix | Behaviour |
|--------|-----|------------|-----------|
| `cozy_mgl_airtalk` | Arduino Nano 33 BLE USB, passive Airtalk tap | `MGL_AT_*` | FIX-Gateway owns the Nano serial port. Does not overwrite Stratux `PITCH` / `ROLL` / `HEAD`. Roll sign on this aircraft is **positive left**. |
| `cozy_mgl_nmea` | Extreme NMEA 0183 on `/dev/serial0` at 19200 | `MGL_NMEA_*` | Does not overwrite Stratux `LAT` / `LONG`. Altitude stored in **feet**. `GPSD` stays off. |
| `cozy_mgl_can` | MCP2515 SocketCAN `can0` at 250 kbit/s | `MGL_RDAC_*` | **Receive only.** RDAC CHT/EGT stored as compensated **°F**. |
| `cozy_mgl_servo` | Same `can0`, virtual bank and pitch servos | `MGL_SRV_*` | Logs XTreme steering commands. **Does not transmit** unless `allow_tx` and `tx_armed` are both true. Aircraft default is TX off. |

The stock FIX-Gateway `MGL` plugin stays **off**. It can transmit on the bus. Our CAN plugin is the listener. The servo plugin is a separate, interlocked transmitter for ground experiments only.

Web debug pages: `/debug/mgl/can`, `/debug/mgl/airtalk`, `/debug/mgl/gps`, plus an autopilot/servo page. CAN debug still shows wire °C. Live and Historian show the FIX units.

### Phase 4 — Historian

Capture core is done.

- SQLite at `/cozy-data-system/data/historian/cozy_historian.sqlite`, WAL, on the SD card via bind mount. The Stratux root overlay is a **250 MB tmpfs** and must not hold the flight database or the venv.
- 10 Hz fast state and 1 Hz slow state, sampled from FIX. Events and pilot MARK.
- Daemon starts on boot and waits. A flight begins only on Start (web button or `historian start-flight`).
- Control socket: `/cozy-data-system/data/historian/historian.sock`.
- Signal list is `config/historian/historian.yaml`, copied from the FIX database. Historian does not convert units.
- AvPlan GPX can be merged onto an existing flight’s 10 Hz frames, or used to create a flight. Original source time is kept. Sync window is 500 ms.

Still open: import of MGL `ENIGMA.REC` / XTFLIGHT CSV into Historian tables. The files already land in the inbox.

### Phase 5 — Web UI

MVP is done. FastAPI, Uvicorn, Jinja2, HTMX, a little vanilla JavaScript, WebSocket JSON. No Streamlit on the aircraft.

| Page | What it does |
|------|----------------|
| `/live` | Instruments from FIX over `/ws/live` at about 10 Hz. Start, stop, MARK. |
| `/flights` | Catalogue, manifest, External Data (MGL card), AvPlan GPX merge |
| `/status` | GPS, FIX, Historian, temperature, host, MGL |
| `/configuration` | Wi-Fi, aircraft, historian signal list |
| `/analysis` | One flight, simple plot, CSV export |

URLs: `http://192.168.50.2:8080/live` on the bench Ethernet, `http://192.168.10.1:8080/live` on the cockpit AP.

The web process can die without stopping the Historian. The Historian never calls the web process.

---

## 5. What we are planning

In the order the project itself has set, not a new priority invented here.

1. **Enigma / XTFLIGHT import.** Decode the inbox files and synchronise them onto the existing Historian frames. Then the web import controls that the Phase 5 spec still describes. Do not invent a second timeline.
2. **Finish Airtalk commissioning.** Several protocol fields are still open (status byte, gyro heading, voltage, turn-rate scale, dest `$E6` type `$01`). The permanent receiver circuit is not done. The tap that flies today is the Nano USB path.
3. **Pitch and roll stick encoders** on the **same** Nano 33 BLE that already receives Airtalk. Pitch Omron E6B2-CWZ6C 2000 P/R, roll HOK38H5-600N-G5-24 600 P/R, preliminary stick-to-encoder ratio 1.75. This must not move Airtalk RX off D4, must not use D3 (bench TX, high-Z in flight), and must stay 3.3 V. Plan: `doco/Nano_Encoder_Implementation_Plan.md`.
4. **Servo-emulator experiments**, still behind both TX interlocks, stationary, and not wired to a real S-TEC driver. The XTreme on this aircraft may be scoring “identify servo” on RS-232 as well as CAN. Read `doco/mgl_servo.md` before proposing a test.
5. **Phase 6 cloud upload.** An independent service that ships completed local flights when a link exists and retries when it does not. Not started. It waits until local capture and import are solid.
6. **FlySto importer.** Post-flight only. HAR files the pilot already downloaded in a browser. Maneuvers and phases as a reference classifier. No login automation, no credential storage, no in-flight use. Spec only: `doco/FlySto_Flight_Analysis_Importer_Specification.md`.
7. **Our own flight-phase classifier**, later, checked against FlySto rather than replaced by it.
8. **New sensors on CAN.** CAN is the standard for anything we add. The Pi remains a gateway, not the real-time sampler.
9. **Long-term and multi-flight analysis** lives in the future cloud environment. The Pi analysis page stays a single-flight look at what is on the aircraft.

Mentioned as future and not scheduled: GNC-300 RS-232 GPS, ARINC investigation, more CAN nodes beyond RDAC and the servo emulator, an outdoor GPS cross-check of the USB Stratux receiver against the Extreme.

---

## 6. Rules we have established

These are constraints. A research note that needs to break one of them is incomplete until it says which rule, why, and what would have to be re-decided by the builder.

### 6.1 Safety boundary

1. The system is **non-essential and advisory**. It has **no control authority**.
2. It runs **in parallel** with the MGL XTreme and the rest of the panel. It must not interfere with engine instruments, the autopilot, radios, or the transponder.
3. A dead Pi, a crashed service, a bad decode, or a pulled connector leaves the MGL installation working. That is why the Airtalk tap is receive-only and why the flight TX line stays off.
4. **Passive first.** RDAC CAN ingest is receive-only. The software must not transmit on the aircraft CAN bus to discover or decode traffic.
5. The stock FIX-Gateway `MGL` plugin stays disabled because it can transmit.
6. The servo emulator is not an actuator driver. Transmit only when `allow_tx` and `tx_armed` are both true. There is no automatic arm. Restart returns to the safe config. Malformed commands get no reply. Initial tests are on the ground. Do not put this emulator on an identification session that also has a real MGL servo unless that sharing is the explicit test.
7. A decoded value is not flight-critical until its source, scale, update rate, validity, and failure mode have been checked on this aircraft.
8. Label the installation non-essential. Power is a dedicated 12 V to 5 V supply for a panel Pi and touchscreen.

### 6.2 Data rules

1. **All live aircraft state goes through FIX.** Displays and the logger are consumers. They do not own the data and they do not talk to each other for live values.
2. **No second live-data service.** Historian and FastAPI each open their own FIX connection. Shared Python helpers are fine. A new daemon whose failure would take both down is not.
3. **The web UI is not on the recording path.** Historian keeps recording if FastAPI, the browser, Wi-Fi, or the touchscreen dies.
4. **One timeline per flight.** The 10 Hz and 1 Hz frames written in flight stay put. Later imports land on those frames. They do not shift them and they do not create a parallel analysis clock.
5. **Keep provenance.** Stratux, Airtalk, NMEA, RDAC, servo commands, and AvPlan stay in their own keys (`MGL_AT_*`, `MGL_NMEA_*`, `MGL_RDAC_*`, `MGL_SRV_*`, `avplan_*`). Do not overwrite a measured channel with an imported or derived one.
6. **Convert units once, at ingest into FIX.** The YAML `units` field is the contract. Historian stores that. The UI shows that. Live altitudes are feet. RDAC temperatures are compensated °F. CAN debug may still show the wire unit.
7. **One decoder per protocol.** CAN interpretation lives in the CAN plugin. The web page and the Historian do not grow their own CAN, Airtalk, or NMEA decoders.
8. **Logging does not need the network.** The database is local SQLite on the SD card.
9. **Recording is deliberate.** Services come up at boot. A flight does not. The pilot (or a test command) starts and stops it.
10. The Historian accepts sample jitter. A row means “best FIX state we had at this Historian time,” not “the sensor’s own timestamp.” Live FIX data does not need an acquisition timestamp for this system. Secondary imports **do** keep their original timestamp beside the sync error.
11. The Pi is a **gateway and aggregator**, not the real-time acquisition device. New sensors use CAN and publish into FIX.

### 6.3 Engineering rules

1. **The Mac repo is the source of truth.** Edit here. Deploy to the Pi over SSH (`rsync` / `scp`). User `pi`. Then run `sudo /cozy-data-system/scripts/persist_cozy_to_robase.sh` so the overlay tmpfs is not the only copy.
2. **Persistent behaviour lives in source** (image templates, YAML, systemd units, scripts). A one-off shell change on the Pi is not a fix.
3. Stratux customizations must be describable well enough to re-apply onto a newer upstream Stratux. See `doco/stratux_local_customizations.md`.
4. The Stratux writable overlay is about **250 MB**. FIX-Gateway, the venv, and flight data live on `/overlay/robase`, bind-mounted into `/cozy-data-system`.
5. Image build on Apple Silicon: the build script breaks if the path contains spaces, and a drifted `pi-gen` pin has already broken a build. Follow `doco/stratux_build_and_imaging.md`.
6. Large image artifacts stay out of git unless someone deliberately versions one.
7. Aircraft web stack is Python 3, FastAPI, Uvicorn, SQLite, Jinja2, HTMX, small vanilla JS, WebSockets. Plotly is acceptable for the onboard chart. Streamlit is deferred and is not part of the aircraft runtime.
8. Configuration beats hard-coding for bus names, FIX maps, calibration, and which devices are enabled.
9. Fail visibly. Unknown CAN ids, stale FIX values, bad lengths, and a down interface should be observable on the status or debug pages.
10. When two sources disagree, keep both. Comparison is the point of the extra taps.

### 6.4 How a research agent should work

1. Separate three kinds of claim and label each one:
   - **Measured on VH-COZ** (a capture, a journal, a sentence in a doc that says we saw it).
   - **From a published manual or protocol** (cite the document and the section).
   - **Inferred** (say what it rests on).
2. Do not invent FIX key names, pinouts, scale factors, or CAN ids. If the repo does not contain them, the answer is “not in the repo yet.”
3. Do not propose a design that transmits on Airtalk or CAN, arms the servo emulator, or writes into the MGL Extreme, unless the task is specifically the already-specified ground test and you repeat the interlocks.
4. Do not scrape, log into, or automate FlySto. The importer spec starts from a HAR file the owner already saved.
5. Prefer a short note that names the decision it supports and the rule in section 6 it has to respect. Point at the file and section you used.
6. Specs in `doco/` sometimes lag the code (the AvPlan importer is the current example). Check both before you tell the builder something is missing.
7. Vendor code under `stratux-master/` and `fix-gateway-master/` is reference. Change it only when a Stratux image customization or a FIX behaviour really requires it, and record that in `doco/stratux_local_customizations.md` or the relevant install note.

---

## 7. Useful facts that are easy to get wrong

- **Two GPS stories.** Stratux position comes from a USB GNSS receiver. The GPIO UART is the MGL Extreme’s NMEA output. `doco/gps_matek_sam_m8q.md` is the Matek wiring note; the live aircraft path is the USB receiver plus Extreme NMEA on `serial0`. Say which source you mean.
- **Two attitude stories.** Stratux AHRS and MGL Airtalk both produce pitch, roll, and heading, in different FIX keys. Airtalk roll is positive left on this XTreme. Do not “merge” them into one key.
- **CAN id layout** used by our decoder: 11-bit, `device_address << 4 | message_id`, 250 kbit/s. Protocol reference is MGL Avionics CAN Communications Protocol Release 10 (16 August 2018), plus what we have actually seen on VH-COZ.
- **Servo identify** on this XTreme is described in the operating manual §4.16 and may not be CAN-only. Read the 2026-09-13 notes in the servo spec before assuming a CAN reply completes an identify.
- **Nano pins already taken:** D4 Airtalk RX, D3 bench-test TX. Encoder plan uses D2/D5 roll, D6/D7 pitch, D8 pitch index. 3.3 V logic, not 5 V tolerant.
- **Flight id shape** used by the CLI examples: `COZ-YYYYMMDD-NN`.
- **Seeded configuration:** `COZ_CFG_001`, “Baseline Stage 1”.

---

## 8. Open questions worth research

These are gaps a follow-on agent can actually work. Stay inside section 6.

1. **Airtalk fields still undecoded** on the live tap: FF/32 status byte; FF/37 gyro-heading and voltage; turn-rate scale; dest `$E6` type `$01`. What does MGL documentation or a captured frame support, and what is still unknown?
2. **Enigma `.rec` and XTFLIGHT CSV.** What is in the inbox copies, how should they align to the 10 Hz grid, and which columns would duplicate a FIX channel we already store (those stay as a separate source)?
3. **XTreme servo identify path.** Which messages are CAN, which are RS-232 / COM Extender, and what would a ground test prove without arming TX?
4. **RDAC compensation.** Confirm the °F formula we store matches the Extreme’s displayed CHT/EGT closely enough for analysis, using a captured flight rather than the wire °C page.
5. **Historian load.** About 130 keys at 10 Hz over NetFIX can overrun a 100 ms tick. Which keys deserve 10 Hz, and which are already specified as 1 Hz, so a later trim does not drop something the Phase 4 spec put on the fast timeline?
6. **Encoder electrical check** against the Nano plan: 3.3 V pull-ups, quadrature direction versus stick sense, and a calibration method that survives power loss (the Nano counters are volatile).
7. **FlySto HAR shape.** Using only the published spec and any sanitized fixture that appears in the repo later: which responses carry phases and maneuvers, and how would their times attach to an existing `COZ-*` flight without a second timeline?
8. **Cloud upload boundaries.** What must remain on the aircraft if the uplink never appears, and which files are the upload unit (SQLite flight, exports, inbox originals)?

A good research reply names the files it read, separates measurement from inference, and ends with what the builder would have to decide. It does not include a patch, a bus transmit sequence, or a change to flight-control behaviour.

---

## 9. One-paragraph handoff

VH-COZ is a Cozy III with an MGL XTreme. A Raspberry Pi 5 running a customized Stratux image collects ADS-B, USB GPS, and AHRS, and passively taps Airtalk (Nano USB), Extreme NMEA (GPIO UART), and MGL CAN (MCP2515 `can0`, RDAC only). All of that is published into MakerPlane FIX-Gateway in canonical units, with the MGL values kept in their own keys. A separate Historian samples FIX at 10 Hz and 1 Hz into SQLite on the SD card, only after the pilot starts a flight. A separate FastAPI UI on port 8080 shows live state, flights, and a simple plot. AvPlan plans already cross to the MGL card, and AvPlan GPX tracks can merge onto a recorded flight. Still ahead: Enigma import, finishing the Airtalk decode, stick encoders on the existing Nano, carefully interlocked servo-command logging, then cloud upload and a FlySto phase reference. Nothing in this system is allowed to become part of the flight controls.
