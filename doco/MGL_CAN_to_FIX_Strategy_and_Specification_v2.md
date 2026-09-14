# MGL CAN to FIX-Gateway Integration - Strategy and Implementation Specification

**Project:** Cozy Aircraft Data Collection System  
**Component:** MGL CAN acquisition and FIX-Gateway integration  
**Target platform:** Raspberry Pi / Stratux host  
**Status:** Implementation specification for Cursor — revised for existing FIX-Gateway `mgl`, `canfix` and `canfixand` architecture  
**Primary reference:** *MGL Avionics CAN Communications Protocol for MGL Avionics CAN bus devices, Release 10, 16 August 2018*

---

## 1. Purpose

Implement a reliable, passive interface between the aircraft's existing MGL CAN bus and FIX-Gateway.

The Raspberry Pi shall receive CAN traffic through the MCP2515 interface, decode supported MGL messages, and publish decoded engineering values into the existing FIX-Gateway database/current-state model.

A dedicated diagnostic web page shall be provided to prove and troubleshoot the complete path:

`MGL CAN bus -> MCP2515 -> Linux SocketCAN -> MGL decoder/FIX plugin -> FIX database -> diagnostic web page`

The historian remains a separate downstream consumer of FIX data. The CAN integration shall not write directly to the historian.

---

## 2. Design Principles

1. **Passive monitoring first.** The Pi is initially a CAN listener only. It must not deliberately transmit application CAN frames onto the aircraft bus.
2. **Use FIX-Gateway's existing CAN architecture.** Linux exposes the MCP2515 as SocketCAN `can0`; the new MGL-CAN plugin shall use `python-can`, following the established FIX-Gateway CAN-FIX plugin pattern. Do not create a second raw SocketCAN abstraction unless a demonstrated limitation requires it.
3. **One MGL CAN decoder.** MGL CAN interpretation belongs in a dedicated FIX-Gateway `mgl_can` plugin. The web UI and historian must not implement separate MGL CAN decoders.
4. **Reuse, do not conflate, existing plugins.** The existing FIX-Gateway `mgl` plugin is a useful reference for MGL-to-FIX naming/conversion conventions, while `canfix`/`canfixand` are references for CAN transport, plugin lifecycle and database interaction. MGL CAN is not CAN-FIX and requires its own protocol decoder.
5. **Preserve provenance while fitting FIX conventions.** During commissioning retain source-specific MGL values/diagnostics, but map validated measurements to standard FIX database keys where appropriate. Source-specific values must remain available where comparison between independent sources is useful.
6. **Separate raw, decoded, and historical layers.**
   - Raw CAN = commissioning/debug evidence.
   - FIX = current decoded aircraft state.
   - Historian = sampled time history.
7. **Fail visibly.** Unknown messages, stale values, malformed DLCs, decoder errors and bus/interface faults must be observable.
8. **Configuration over hard coding.** Interface name, enabled devices, FIX mappings, calibration and diagnostic options should be configurable.
9. **Do not disturb the existing MGL installation.** The Extreme remains the operational host/display. This project observes its bus.

---

## 3. Hardware / Linux Boundary

### 3.1 CAN interface

The MCP2515 module is connected to the Raspberry Pi by SPI and exposed by Linux as:

`can0`

Linux shall expose the interface through SocketCAN. The FIX-Gateway plugin shall access that interface through `python-can`, consistent with the existing CAN-FIX plugin architecture.

Initial expected MGL bus configuration:

- Standard CAN
- 11-bit identifiers
- 250 kbit/s
- external bus termination as required by the existing MGL installation

### 3.2 Listen-only commissioning

Where supported by the Linux CAN/MCP2515 stack, commissioning should use listen-only mode.

The software must never send MGL commands merely to discover or decode traffic.

---

## 4. MGL CAN Identifier Structure

The MGL protocol uses an 11-bit CAN identifier.

Conceptually:

`CAN_ID = (device_address << 4) | message_id`

where:

- upper 7 bits = MGL device address
- lower 4 bits = message/function ID

Decoder extraction:

```python
device_address = can_id >> 4
message_id = can_id & 0x0F
```

Relevant documented address ranges include:

| Device | MGL address |
|---|---:|
| Host / EFIS | 1-15 |
| RDAC | 32-35 |
| Compass | 36-39 |
| AHRS | 40-43 |
| Transponder | 44-45 |
| SP10 | 48-51 |
| ECB | 52-59 |
| TouchPad | 60-63 |
| EFIS Extender | 64-67 |
| External MGL AP | 68-69 |

The first implementation should focus on the installed Cozy equipment:

- MGL Extreme / host traffic
- RDAC XF
- SP-7 AHRS
- SP-2 3-axis compass, noting that the protocol document describes this family under the SP-6/Compass message definitions

Do not assume an observed address. Detect and report addresses actually present on the aircraft bus.

---

## 5. Expected High-Value Messages

### 5.1 SP-7 AHRS - Accelerometers

Device address range: 40-43  
Message ID: `1`  
DLC: 8  
Nominal rate: 20 Hz

| Bytes | Value |
|---|---|
| 0-1 | Accelerometer X, signed, 0.001 G |
| 2-3 | Accelerometer Y, signed, 0.001 G |
| 4-5 | Accelerometer Z, signed, 0.001 G |
| 6-7 | Total G, signed, 0.001 G |

Candidate FIX keys:

- `MGL.AHRS.ACCEL_X`
- `MGL.AHRS.ACCEL_Y`
- `MGL.AHRS.ACCEL_Z`
- `MGL.AHRS.TOTAL_G`

### 5.2 SP-7 AHRS - Gyro Rates

Device address range: 40-43  
Message ID: `2`  
DLC: 8  
Nominal rate: 20 Hz

| Bytes | Value |
|---|---|
| 0-1 | Turn rate |
| 2-3 | Bank rate |
| 4-5 | Pitch rate |
| 6-7 | Yaw rate |

Bank, pitch and yaw rate use the documented scale:

`360 deg/s = 16384 counts`

therefore:

`rate_deg_s = raw * 360 / 16384`

Candidate FIX keys:

- `MGL.AHRS.TURN_RATE`
- `MGL.AHRS.ROLL_RATE`
- `MGL.AHRS.PITCH_RATE`
- `MGL.AHRS.YAW_RATE`

### 5.3 SP-7 AHRS - Euler Attitude

Device address range: 40-43  
Message ID: `3`  
DLC: 8  
Nominal rate: 20 Hz

| Bytes | Value |
|---|---|
| 0-1 | Euler roll/bank, signed, 0.01 deg |
| 2-3 | Euler pitch, signed, 0.01 deg |
| 4-5 | Euler yaw, signed, 0.01 deg |
| 6 | Slip |
| 7 | Status/mode bits |

Status byte includes:

- bit 0: accelerometer/gyro mode
- bit 1: gyro over-range
- bit 2: operating-temperature flag (document notes no longer used)
- bits 5-7: AHRS identification

Candidate FIX keys:

- `MGL.AHRS.ROLL`
- `MGL.AHRS.PITCH`
- `MGL.AHRS.YAW`
- `MGL.AHRS.SLIP`
- `MGL.AHRS.GYRO_MODE`
- `MGL.AHRS.OVERRANGE`

### 5.4 Compass - Heading / Magnetometer

Device address range: 36-39  
Message ID: `1`  
DLC: 8  
Nominal rate: 20 Hz

Expected contents:

- magnetic heading: 0.01 degree resolution
- packed 12-bit corrected magnetometer X/Y/Z
- slip/ball value

The raw magnetometer values are packed fields and must be implemented from the protocol definition and verified with test vectors before use.

Candidate FIX keys:

- `MGL.COMPASS.HEADING`
- `MGL.COMPASS.MAG_X`
- `MGL.COMPASS.MAG_Y`
- `MGL.COMPASS.MAG_Z`
- `MGL.COMPASS.SLIP`

### 5.5 RDAC XF

RDAC address range: 32-35.

RDAC messages are particularly important because they provide the engine/sensor acquisition path.

#### ID 1 - Fuel-flow pulse information

DLC 8; transmitted every 4 seconds.

Contains pulse count and pulse-ratio information for fuel-flow channels 1 and 2.

Initially expose decoded raw protocol quantities. Do not invent fuel-flow engineering conversion without the required calibration.

#### IDs 2-4 - Thermocouples

DLC 8; transmitted every 500 ms.

- ID 2: TC1-TC4
- ID 3: TC5-TC8
- ID 4: TC9-TC12

Values are uncompensated K-type thermocouple measurements represented as degrees C. The RDAC temperature from ID 7 is used for cold-junction compensation.

Do not prematurely label TC channels as EGT/CHT until the aircraft's RDAC channel configuration is known.

Publish initially as:

- `MGL.RDAC1.TC1` ... `MGL.RDAC1.TC12`

A later aircraft configuration mapping can define which channels are EGT1-4, CHT1-4, etc.

#### ID 5 - Analog channels

DLC 8; transmitted every 500 ms.

Raw 12-bit ADC values:

- OILT
- OILP
- AUX1
- AUX2

Publish both raw values and, once calibration is implemented, engineering values.

#### ID 6 - Analog channels

DLC 8; transmitted every 500 ms.

Raw 12-bit ADC values:

- FUELP
- COOLANT
- FUELLEVEL1
- FUELLEVEL2

Again, raw values are authoritative until the relevant conversion/calibration is known.

#### ID 7 - RDAC temperature and supply voltage

DLC 4; transmitted every 500 ms.

Contains:

- RDAC temperature
- RDAC supply-voltage raw value

Implement the voltage conversion specified by the MGL protocol and retain the raw value for diagnostics.

#### ID 8 - RPM, MAP and Current

DLC 8; transmitted every 200 ms (5 Hz).

Expected fields:

- RPM1
- RPM2
- MAP raw ADC
- CURRENT raw ADC

RPM is based on one pulse per revolution in the protocol representation. The protocol also defines a special >=50000 representation for high/turbine RPM.

MAP and current are raw ADC readings; conversion to engineering values depends on equipment/calibration.

This is particularly relevant to the Cozy RDAC MAP work. The decoder shall therefore expose:

- `MGL.RDAC1.MAP_RAW`
- `MGL.RDAC1.RPM1`
- `MGL.RDAC1.RPM2`
- `MGL.RDAC1.CURRENT_RAW`

Do not hard-code the experimentally derived MAP calibration into the low-level CAN decoder. Put engineering conversion in a configurable calibration layer.

---

## 6. Byte Decoding

The MGL document describes multibyte quantities as little-endian where explicitly specified and examples in the protocol are consistent with this convention. Implement helper functions centrally rather than duplicating byte manipulation.

Suggested helpers:

```python
u16_le(data, offset)
s16_le(data, offset)
u32_le(data, offset)
s32_le(data, offset)
```

Packed fields, such as the compass magnetometer data, should have dedicated decoder functions and unit tests.

Every decoder must validate DLC before accessing bytes.

A bad/mismatched frame must increment a diagnostic counter and must not overwrite the last valid FIX value.

---

## 7. Software Architecture

### 7.1 Reuse FIX-Gateway's existing CAN pattern

The existing FIX-Gateway CAN-FIX documentation specifies `python-can` as the CAN-bus interface and supports configuration such as `interface: socketcan` and `channel: vcan0`. The new MGL-CAN implementation shall follow that pattern, substituting the aircraft interface `can0`.

Do **not** route MGL frames through the CAN-FIX protocol decoder. CAN-FIX and MGL CAN are different application protocols that happen to share CAN as transport.

```text
MGL CAN bus
    │
    ▼
MCP2515 + Linux driver
    │
    ▼
SocketCAN can0
    │
    ▼
python-can
    │
    ▼
FIX-Gateway
└── mgl_can plugin
      ├── python-can receiver/listener
      ├── CAN identifier parser
      ├── device/message dispatcher
      ├── MGL payload decoders
      ├── engineering conversion/calibration
      ├── FIX publisher
      └── diagnostics
             │
             ├── FIX current-state database
             │
             └── diagnostic state
                    │
                    ▼
FastAPI application
└── /debug/mgl-can
      ├── interface status
      ├── observed CAN IDs
      ├── rates
      ├── raw payload
      ├── decoded values
      └── FIX values / age
```

### 7.2 Existing FIX-Gateway code to inspect before implementation

Cursor shall inspect the checked-out current repository before coding:

- `src/fixgw/plugins/mgl` — reference for existing MGL serial integration and FIX database publication conventions. Do not merge CAN decoding into the serial plugin merely because both sources are MGL.
- `src/fixgw/plugins/canfix` — primary reference for `python-can`, SocketCAN configuration, plugin lifecycle and CAN/database integration.
- `src/fixgw/plugins/canfixand` — inspect for additional established listener, mapping, callback, database and testing patterns that can be reused.
- `doc/plugins/canfix.rst` — configuration reference; it explicitly documents `python-can` as the CAN interface and the `interface` / `channel` configuration model.

Prefer established FIX-Gateway APIs and patterns over parallel custom infrastructure.

The existing FastAPI application remains independent of the CAN implementation. It consumes FIX state and, where necessary, a narrow diagnostics API exposed by the MGL plugin/service.

---

## 8. FIX-Gateway Plugin

Create an MGL CAN plugin/module following the conventions of the existing FIX-Gateway installation.

Suggested logical package structure:

```text
mgl_can/
    __init__.py
    plugin.py
    protocol.py
    decoders/
        ahrs.py
        compass.py
        rdac.py
        host.py
    calibration.py
    diagnostics.py
    config.py
```

There should normally be **no custom `socketcan.py` layer**. Use `python-can` in the same manner as FIX-Gateway's CAN-FIX implementation. Adapt this structure to the actual current FIX-Gateway plugin conventions rather than forcing this exact directory layout.

### Plugin startup

On startup:

1. load configuration;
2. create/open the `python-can` bus using the configured `interface` and `channel`;
3. initialise diagnostics;
4. register/obtain FIX keys using established FIX-Gateway database APIs;
5. start the receive/listener loop using the same lifecycle pattern as the existing CAN plugins;
6. report healthy/running state.

For the aircraft installation the expected configuration is `interface: socketcan`, `channel: can0`.

Failure to open CAN must not crash unrelated FIX-Gateway functionality. It should produce a clear degraded/fault state.

### Receive loop

For every frame:

1. record monotonic reception timestamp;
2. validate standard 11-bit frame;
3. extract `device_address`;
4. extract `message_id`;
5. update raw-frame diagnostics;
6. select decoder from `(device_address family, message_id)`;
7. validate DLC;
8. decode;
9. apply any explicitly configured engineering conversion;
10. update FIX values;
11. update message count/rate/last-seen statistics.

Unknown frames are retained in diagnostics but are not errors.

---

## 9. FIX Naming, Standard Keys and Provenance

The implementation should fit FIX-Gateway's existing database conventions rather than creating a completely parallel namespace.

For validated measurements that have an appropriate standard FIX key, the plugin should be capable of publishing to that standard key. At the same time, this project intentionally compares independent sources, so provenance must not be lost.

Use a configurable mapping model with two concepts:

1. **Canonical FIX key** — normal aircraft/current-state value consumed by generic clients.
2. **Source-specific MGL value** — retained where useful for commissioning, comparison, diagnostics and historian analysis.

Conceptually:

```text
MGL SP-7 roll
    ├── source-specific MGL roll
    └── ROLL        # if configured as canonical source

MGL RDAC RPM
    ├── source-specific MGL RPM
    └── RPM1        # if configured as canonical source
```

Exact source-specific key names must follow FIX-Gateway database naming rules; do not assume dotted names are valid without checking the current repository/database definition.

Where multiple live sources can populate the same canonical measurement, inspect FIX-Gateway's existing source-selection/quorum capabilities before inventing custom arbitration logic.

---

## 10. Timing and Data Age

FIX represents current state, not historical samples.

For each decoded signal retain, where FIX-Gateway supports it:

- value
- reception/update time
- age/stale state
- quality/status

The CAN receiver should use a monotonic clock internally for age and rate calculations.

Do not manufacture a measurement timestamp that the MGL message does not contain.

The historian will later sample FIX at its configured frame rates (for example 10 Hz). The original MGL message rate and reception age remain useful metadata when interpreting sampled data.

---

## 11. Diagnostics

Maintain at least:

```text
MGLCAN.STATUS
MGLCAN.RX_COUNT
MGLCAN.DECODE_COUNT
MGLCAN.UNKNOWN_COUNT
MGLCAN.DECODE_ERROR_COUNT
MGLCAN.LAST_RX_AGE
```

Also maintain per-CAN-ID diagnostics in memory:

- CAN ID
- device address
- message ID
- DLC
- latest raw payload in hex
- total count
- calculated message rate
- last reception monotonic timestamp
- known/unknown
- decoder name

Do not create hundreds of permanent FIX keys merely to represent arbitrary unknown CAN frames.

---

## 12. Diagnostic Web Page

Implement:

`/debug/mgl-can`

This is an engineering/commissioning page, not the production flight display.

### Section A - CAN interface

Show:

- interface: `can0`
- state UP/DOWN
- configured bitrate if available
- listen-only state if available
- RX frame count
- CAN errors where available
- last frame age
- plugin status

### Section B - observed messages

Live table:

| CAN ID | Device | Msg ID | DLC | Rate | Last age | Payload | Decoder |
|---|---|---:|---:|---:|---:|---|---|

This is essential for comparing the actual Extreme/RDAC/SP-7/SP-2 installation against the document.

Unknown IDs should remain visible and clearly marked `UNKNOWN`.

### Section C - decoded FIX values

Live table:

| FIX key | Value | Units | Age | Status | Source |
|---|---:|---|---:|---|---|

### Updates

Use the already selected FastAPI/WebSocket/JSON architecture.

The server may send JSON snapshots/deltas over WebSocket to the page. HTMX and lightweight JavaScript may be used for rendering; no Streamlit dependency is required.

A suitable JSON diagnostic update might be:

```json
{
  "type": "mgl_can_update",
  "can": {
    "interface": "can0",
    "status": "UP",
    "rx_count": 38426
  },
  "messages": [
    {
      "can_id": "0x283",
      "device_address": 40,
      "message_id": 3,
      "dlc": 8,
      "rate_hz": 20.0,
      "age_ms": 18,
      "payload": "..."
    }
  ]
}
```

The exact CAN ID above is illustrative of the documented address/message composition; observed traffic is the commissioning authority.

---

## 13. Raw CAN Capture

Support raw capture during development/commissioning using standard SocketCAN tooling rather than inventing another recording format.

Example operational concept:

```bash
candump -L can0 > mgl_can.log
```

Raw logs are diagnostic evidence and are not part of the normal historian.

They should allow later replay into the decoder for regression testing.

---

## 14. Configuration

Provide configuration similar to:

```yaml
mgl_can:
  load: yes
  module: plugins.mgl_can

  # python-can configuration, following CAN-FIX convention
  interface: socketcan
  channel: can0

  passive: true

  devices:
    rdac: true
    ahrs: true
    compass: true
    host: true

  diagnostics:
    retain_unknown_ids: true
    calculate_rates: true

  calibration:
    rdac1:
      map:
        enabled: false
```

Do not put aircraft-specific sensor calibration constants inside protocol decoder source code.

---

## 15. Testing Strategy

Testing is deliberately staged so faults can be isolated.

### Stage 1 - Linux/MCP2515

Acceptance:

- `can0` exists.
- interface can be brought UP at 250 kbit/s.
- existing MGL traffic is visible.
- traffic stops when physically disconnected.
- no evidence the Pi is disturbing the MGL network.
- Extreme/SP-7/RDAC/compass continue normal operation.

Use standard SocketCAN tools before FIX-Gateway.

### Stage 1A - python-can transport test

Before writing MGL protocol logic, prove that `python-can` can open `socketcan/can0` and receive the same frames seen by `candump`.

Acceptance:

- no custom raw CAN socket code is required;
- arbitration IDs, DLC and payloads agree with `candump`;
- shutdown/restart releases and reopens the interface cleanly;
- passive/listen-only behaviour is maintained as configured.

### Stage 2 - CAN identifier discovery

Record all observed IDs and rates with the aircraft system powered.

Verify that observed identifiers decompose into plausible MGL address/message pairs.

Expected examples include:

- AHRS address 40-43 with message IDs 1, 2 and 3 near 20 Hz.
- compass address 36-39 message ID 1 near 20 Hz.
- RDAC address 32-35 with slower message IDs.

Do not fail merely because additional host or device traffic is present.

### Stage 3 - Decoder unit tests

Create deterministic byte-level tests for every implemented decoder.

Examples:

**Euler roll**

Raw signed value `1234` -> `12.34 deg`.

Raw signed value `-9000` -> `-90.00 deg`.

**Gyro rate**

Raw `16384` -> `360 deg/s`.

**Accelerometer**

Raw `1000` -> `1.000 G`.

**Heading**

Raw heading `12345` -> `123.45 deg`.

Test:

- positive values
- negative signed values
- zero
- minimum/maximum expected values
- malformed DLC
- packed compass fields
- status bits

### Stage 4 - recorded CAN replay

Capture a short `candump` log from the real aircraft.

Create a replay/injection test path that feeds recorded frames to the decoder without requiring the aircraft.

Acceptance:

- same log produces same decoded values;
- no decoder exceptions;
- message counts/rates are sensible;
- unknown messages remain observable.

### Stage 5 - FIX publication

For each known test frame:

`known CAN bytes -> expected decoded value -> expected FIX key`

Verify:

- correct key;
- correct units;
- correct sign;
- correct scaling;
- update occurs only on matching messages;
- malformed messages do not corrupt the last good value;
- stale/age behaviour works.

### Stage 6 - physical sensor tests

With aircraft stationary and engine not running where appropriate:

- rotate/tilt SP-7 and compare roll/pitch with Extreme;
- change heading and compare compass heading;
- compare RDAC temperature channels;
- compare MAP raw ADC while changing the test/input condition;
- verify RPM remains zero with engine stopped.

The goal is agreement with the Extreme and expected physical response, not merely plausible numbers.

### Stage 7 - web diagnostic page

Verify:

- CAN interface state changes correctly;
- RX counter increments;
- observed IDs populate automatically;
- nominal message rates are shown;
- raw payload changes live;
- decoded values match FIX;
- age increases when a source stops;
- unknown messages are visible;
- WebSocket reconnects cleanly after network interruption.

### Stage 8 - historian integration

Only after CAN/FIX validation.

Add selected `MGL.*` FIX keys to the existing historian configuration.

The historian samples them exactly like any other FIX value.

No CAN-specific code is permitted in the historian.

---

## 16. Acceptance Criteria

The implementation is acceptable when:

1. Pi receives the aircraft MGL CAN bus through `can0` without disrupting normal MGL operation.
2. Plugin automatically identifies documented device/message combinations.
3. SP-7 attitude, rate and acceleration data decode correctly.
4. compass heading data decode correctly.
5. relevant RDAC messages decode correctly.
6. raw ADC quantities remain distinguishable from calibrated engineering quantities.
7. decoded values appear in FIX with `MGL.*` provenance.
8. FIX values expose sensible freshness/staleness behaviour.
9. `/debug/mgl-can` shows bus status, observed frames, rates, payloads and decoded FIX state.
10. unknown frames remain observable.
11. recorded CAN traffic can be replayed for regression testing.
12. historian can consume selected FIX keys without knowing that they originated on CAN.

---

## 17. Implementation Order for Cursor

Implement in this order:

1. inspect current FIX-Gateway `mgl`, `canfix`, `canfixand` plugins and `canfix.rst`;
2. confirm/configure SocketCAN `can0`;
3. prove `python-can` reception on `socketcan/can0`;
4. create the new MGL-CAN plugin using established FIX-Gateway lifecycle/database patterns;
5. create the MGL identifier parser and raw-frame diagnostics;
6. implement SP-7 decoders;
7. implement compass decoder;
8. implement RDAC decoders;
9. implement configurable FIX publication/mapping;
10. add diagnostics/status;
11. implement FastAPI diagnostic endpoints and WebSocket JSON updates;
12. build `/debug/mgl-can`;
13. add unit tests and recorded-log replay tests;
14. validate against the live aircraft;
15. only then add selected validated FIX values to historian configuration.

---

## 18. Repository / Implementation References

Cursor should treat the checked-out FIX-Gateway source as the authority for current plugin APIs and naming conventions.

Review before implementation:

- `src/fixgw/plugins/mgl`
- `src/fixgw/plugins/canfix`
- `src/fixgw/plugins/canfixand`
- `doc/plugins/canfix.rst`

The CAN-FIX documentation states that `python-canfix` installs `python-can`, and that `python-can` is used as the CAN-bus interface. Its example configuration uses `interface: socketcan` and `channel: vcan0`. For this aircraft project the intended physical channel is `can0`.

The goal is **not** to reuse CAN-FIX protocol semantics. It is to reuse the proven FIX-Gateway CAN transport/plugin pattern while substituting the MGL protocol decoder described here.

---

## 19. Explicit Non-Goals for Initial Version

Do not initially:

- transmit MGL commands;
- impersonate an MGL host;
- alter SP-7/compass addresses;
- perform compass calibration;
- change RDAC calibration;
- replace the Extreme as CAN host;
- write CAN data directly to historian tables;
- make the FastAPI UI decode CAN;
- map every MGL signal to generic FIX keys;
- assume every documented MGL message will be present in this aircraft;
- permanently store all raw CAN traffic during every flight.

These can be considered later after passive acquisition is proven.

---

## 20. Important Implementation Notes

The attached protocol contains a few table/range typographical inconsistencies (for example some 8-byte fields are printed as ending at byte 8). Cursor should implement valid CAN payload boundaries and use the documented field intent, but questionable cases must be captured in tests and verified against real traffic rather than silently guessed.

Likewise, raw RDAC analog channels are not engineering measurements until the appropriate aircraft calibration is applied. The protocol decoder should preserve the raw measurement so later calibration changes do not require changing the CAN parser.

The initial system should therefore make it easy to answer three separate questions:

1. **What was actually received on the wire?**
2. **What does the MGL protocol say that frame means?**
3. **What current engineering value has FIX published?**

Maintaining those three layers is central to making the Cozy data system diagnosable and extensible.
