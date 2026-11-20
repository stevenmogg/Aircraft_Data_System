# MGL Airtalk Interface for Raspberry Pi Data Collector

**Project:** VH-COZ Aircraft Data Acquisition System\
**Status:** Receive-only tap live on the aircraft Airtalk bus. Heading
and SP-7 Euler10 attitude are decoded and published to FIX (`MGL_AT_*`).
FIX-Gateway plugin `cozy_mgl_airtalk` owns the Nano USB port; the web
page Watch/Observed/Interface follow that FIX feed.
**Target computer:** Raspberry Pi 5\
**Primary MGL sources:** SP-7 AHRS and SP-2 compass, connected to the
existing MGL Airtalk network\
**Last decode update:** 9 September 2026

------------------------------------------------------------------------

## 1. Purpose

This document defines the proposed interface between the existing MGL
Avionics Airtalk network and the Raspberry Pi 5 data collector.

The immediate objective is to **passively acquire Airtalk traffic
without altering the operation of the installed MGL system**. The first
implementation is deliberately receive-only. The Raspberry Pi will
observe the bus, timestamp and decode messages, and ultimately publish
selected values into FIX-Gateway.

The intended data path is:

``` text
MGL SP-7 AHRS ─────┐
                   │
MGL SP-2 Compass ──┼──── Existing Airtalk bus ──── MGL XTreme
                   │
                   └──── Passive receive-only tap
                                      │
                              10 kΩ / 18 kΩ divider
                              (5 V Airtalk → 3.3 V)
                                      │
                              Arduino Nano 33 BLE D4
                           Airtalk monitor/bridge
                                      │
                                      USB
                                      │
                               Raspberry Pi 5
                                      │
                              mgl_airtalk plugin
                                      │
                                  FIX-Gateway
                                      │
                                   Historian
```

The tap MCU is a **Nano 33 BLE** (nRF52840). Its GPIO is **3.3 V only and
not 5 V tolerant**. A 22 kΩ series resistor alone is not a level shifter:
Airtalk Space is still ~5 V at the pin. Use the 10 kΩ / 18 kΩ divider
below (≈ 3.21 V at D4) or a 3.3 V Schmitt buffer with a 5 V-tolerant
input. D3 stays high-Z in flight so the MCU cannot drive Airtalk.

The interface is initially intended for **data acquisition only**. No
Raspberry Pi transmit connection is to be made to Airtalk during the
protocol-discovery and initial operational phases.

------------------------------------------------------------------------

## 2. Design Principles

1.  Do not interfere with normal operation of the MGL XTreme, SP-7 or
    SP-2.
2.  Use a physically receive-only connection during initial development.
3.  Present a high impedance to the existing Airtalk bus.
4.  Protect the Raspberry Pi from the approximately 5 V Airtalk
    signalling level.
5.  Preserve the original MGL wiring and termination arrangements.
6.  Capture raw traffic before implementing assumptions about the SP-7
    protocol.
7.  Validate decoding against known indications on the MGL XTreme.
8.  Separate physical acquisition, protocol decoding and FIX-Gateway
    mapping in software.
9.  Preserve raw message information and provenance for troubleshooting
    and later analysis.

------------------------------------------------------------------------

## 3. Airtalk Electrical Interface

MGL describes Airtalk as a shared, single-wire asynchronous
communications link.

The SP-4 OEM communications documentation specifies:

-   19,200 baud
-   one start bit
-   eight data bits
-   one stop bit
-   no separate clock
-   single-wire data connection
-   `<1 V` represents Mark
-   `>3 V` represents Space
-   weak pull-up toward +5 V
-   polarity is different from conventional RS-232 signalling
-   multiple devices may share the bus

The SP-7 installation documentation confirms that older MGL
installations use the single-wire Airtalk bus and that it requires **no
termination resistor**.

### Reference documentation

-   [MGL SP-7 AHRS Installation/Firmware
    Documentation](https://www.mglavionics.co.za/Docs/SP-7.pdf)
-   [MGL SP-6 / SP-7 Installation
    Manual](https://ww.mglavionics.co.za/Docs/SP6-SP7.pdf)
-   [MGL SP-4 AHRS OEM Communications
    Documentation](https://www.mglavionics.co.za/Docs/SP-4.pdf)
-   [MGL Legacy AHRS and Compass Documentation
    Page](https://mglavionics.co.za/legacy4.html)
-   [MGL Legacy Accessories -- Airtalk to PC
    Interfaces](https://mglavionics.co.za/legacy3.html)

The SP-4 OEM document is particularly useful because it documents the
Airtalk physical layer, framing and AHRS messages. It is a strong
reference for protocol investigation, but **SP-4 message compatibility
must not be assumed to prove the SP-7 Airtalk payload format**. Live
VH-COZ captures (September 2026) show that broadcast type `$37`
**does** follow the SP-4 Euler10 layout, with the sign conventions and
unused fields recorded in [section 14](#14-validated-live-decode).

### Observed signalling on VH-COZ

The Nano 33 BLE hardware UART at 19,200 8N1 with **invert off**
(idle-high / standard TTL UART) produces valid `0x82`…`0x83` frames.
Do not use the inverted software sampler for the live bus.

The tap is **not** the Pi UART. Path:

``` text
Airtalk ── 10 kΩ / 18 kΩ ── Nano 33 BLE D4 (RX only)
                              USB 115200
                              /dev/serial/by-id/usb-Arduino_Nano_33_BLE_*
                              cozy-web Airtalk monitor
```

Firmware: `hardware/nano_airtalk_monitor/`. Host parser:
`web/app/services/airtalk_frames.py`. Live engineering display:
`http://<pi>:8080/debug/mgl/airtalk`.

------------------------------------------------------------------------

## 4. Airtalk Packet Framing

The historical MGL OEM documentation defines Airtalk messages in the
following form:

``` text
STX
Destination
Length
Message Type
Data[1]
Data[2]
...
Data[n]
Checksum
ETX
```

Known framing constants are:

``` text
STX = 0x82
ETX = 0x83
```

The checksum is an XOR checksum using an initial value of `0xA5`.

The SP-2 documentation identifies the magnetometer destination as
`0xE4`. Historical AHRS documentation identifies the IMU/AHRS
destination as `0xE6`.

These values provide useful signatures when analysing a raw capture.

### Protocol validation strategy

Before relying on any SP-7 decoder:

1.  Capture raw Airtalk bytes at 19,200 baud. **Done** (Nano tap).
2.  Locate valid `0x82 ... 0x83` frames. **Done**.
3.  Verify frame length and checksum behaviour. **Done**.
4.  Identify known heading broadcasts. **Done** (FF/32, not dest E4).
5.  Classify remaining traffic by destination, type, length and rate.
    **In progress** (FF/37 Euler10; E6/01 unknown).
6.  Correlate candidate SP-7 messages with controlled pitch, roll and
    yaw movement. **Done** for FF/37.
7.  Compare decoded values against the MGL XTreme. **Done** for heading,
    bank, pitch, yaw behaviour, slip, G and turn-rate bar.
8.  Only then promote the decoder to operational FIX use. **Not started**.

------------------------------------------------------------------------

## 5. MGL SP-7 DB9 Pinout

The MGL SP-7 documentation gives the following connector assignment:

    DB9 Pin Function
  --------- --------------------------------
          1 Ground / battery negative
          2 Ground / battery negative
          3 RS-232 Receive
          4 RS-232 Transmit
      **5** **Airtalk**
          6 Vin / battery positive / +12 V
          7 Vin / battery positive / +12 V
          8 CAN Low
          9 CAN High

For Airtalk acquisition the relevant connections are therefore:

``` text
SP-7 pin 5  = Airtalk
SP-7 pin 1/2 = Ground
```

**Reference:** [MGL SP-7
documentation](https://www.mglavionics.co.za/Docs/SP-7.pdf)

------------------------------------------------------------------------

## 6. Historical SP-4 DB9 Pinout

The SP-4 OEM documentation provides the following connector assignment:

    DB9 Pin Function
  --------- -----------------------------
          1 Ground / battery negative
          2 Ground / battery negative
          3 Ground / battery negative
          4 No connection
      **5** **Airtalk**
          6 Vin / battery positive
          7 Vin / battery positive
          8 USBP -- historical/reserved
          9 USBM -- historical/reserved

This confirms that **pin 5 was also the Airtalk connection on the
earlier SP-4 AHRS**.

**Reference:** [MGL SP-4 OEM
documentation](https://www.mglavionics.co.za/Docs/SP-4.pdf)

------------------------------------------------------------------------

## 7. SP-2 Connection

The SP-2 is the legacy three-axis magnetometer/electronic compass used
with the earlier MGL AHRS family and is installed in the VH-COZ system.

MGL documentation describes the SP-2 and SP-4 as sharing the Airtalk
link. Historical installations also used RCA-style Airtalk
connections/harnessing.

For the aircraft installation, the preferred Pi acquisition point is the
**existing common Airtalk signal**, rather than disturbing the SP-2
connector.

Where direct DB9 access is contemplated, the actual VH-COZ SP-2
connector should be verified electrically before connection. Pin 5 is
strongly indicated by the historical MGL family wiring, but the project
will treat the actual installed unit/harness as the final authority.

### Bench verification

With the system powered and an oscilloscope connected:

``` text
Candidate Airtalk pin ───── Scope CH1
MGL ground ──────────────── Scope ground
```

A valid Airtalk point should show single-wire serial activity with a
high level of approximately 5 V and traffic consistent with 19,200 baud.

------------------------------------------------------------------------

## 8. Preferred Physical Tap Point

The Pi should tap the **common Airtalk network**, not be inserted in
series with it.

``` text
                  Existing aircraft system

SP-7 Airtalk ──────────────┐
                           │
SP-2 Airtalk ──────────────┼──────── XTreme Airtalk
                           │
                           │
                           └────── Pi passive receiver
```

The existing MGL network remains electrically complete if the Pi is
removed or powered down.

This is an important fail-safe property.

------------------------------------------------------------------------

## 9. Bench-Test Raspberry Pi Interface

For initial protocol capture, a simple resistor divider can be used.

### Proposed divider

``` text
MGL AIRTALK
     │
    10 kΩ
     │
     +────────────── Pi UART RX
     │
    18 kΩ
     │
MGL GND ──────────── Pi GND
```

For a 5.0 V Airtalk high:

``` text
V = 5.0 × 18 / (10 + 18)
    ≈ 3.21 V
```

This is suitable for an initial controlled bench experiment. The same
divider feeds **Nano 33 BLE D4** (RX only). Do not wire Airtalk into the
Pi UART while the Nano tap is fitted.

### Pi header connections

  Pi Signal         GPIO   Physical Header Pin Connection
  ----------- ---------- --------------------- -------------------------------
  Ground             ---                     6 MGL ground
  UART RX       GPIO15\*                  10\* Divider output
  UART TX       GPIO14\*                   8\* **NOT CONNECTED**
  3.3 V              ---                     1 Not required for divider test

\*The final UART device/pin assignment must be confirmed in the
Raspberry Pi 5 operating-system configuration before wiring. Do not
assume that the desired UART is enabled on GPIO14/15 merely because
those pins support UART functions.

### Critical rule

**There is no electrical connection from Pi TX to Airtalk.**

The receive-only restriction is intentional. MGL Airtalk supports
commands as well as broadcasts, including configuration/calibration
functions on historical sensor products. Removing the transmit path
prevents a software fault, Linux console configuration or programming
error from transmitting onto the operational MGL network.

------------------------------------------------------------------------

## 10. Permanent Interface

The resistor divider is intended primarily for bench testing and
protocol discovery.

For the permanent aircraft installation, use a dedicated receive buffer
such as a 3.3 V Schmitt-trigger device with a 5 V-tolerant input.

Conceptually:

``` text
MGL Airtalk
     │
 series protection resistor
     │
     ▼
5 V tolerant Schmitt input
3.3 V powered buffer
     │
     ▼
series protection resistor
     │
     ▼
Pi UART RX
```

Desirable permanent-interface features:

-   high input impedance
-   5 V-tolerant input
-   Schmitt-trigger input hysteresis
-   3.3 V output
-   input/output series protection
-   local decoupling
-   optional ESD/transient protection
-   no Airtalk pull-up added by the Pi interface
-   no TX circuitry fitted initially
-   short connection between receiver PCB and Pi GPIO
-   shielded/sensible routing for the Airtalk tap

A candidate component is the **SN74LVC1G17** or equivalent 3.3 V Schmitt
buffer with an input rated for the Airtalk high level.

Final aircraft hardware should be reviewed separately for power
transients, grounding, EMC and installation reliability.

------------------------------------------------------------------------

## 11. Grounding

The simple divider/buffer design uses a common reference:

``` text
MGL Ground ───────── Pi Ground
```

For bench testing this is straightforward.

For the final aircraft installation, grounding should be reviewed in the
context of the complete Pi installation, including:

-   Pi power supply
-   MGL CAN interface
-   USB-connected equipment
-   GPS/Stratux receivers
-   airframe/avionics ground topology
-   potential ground loops

Galvanic isolation may be considered later if testing shows it is
desirable, but it is not required for initial protocol capture.

------------------------------------------------------------------------

## 12. Initial UART Configuration

Airtalk on the wire:

``` text
Baud:       19200
Data bits:  8
Parity:     None
Stop bits:  1
Flow ctrl:  None
Direction:  Receive only
Polarity:   idle-high at Nano D4 (invert off)
```

The Nano forwards bytes over USB at 115200. Early capture was
raw-only; framed decode is now in the web monitor (section 14).

------------------------------------------------------------------------

## 13. Protocol Discovery Tool

Phase 1 capture remains:

``` text
hardware/nano_airtalk_monitor/host/mgl_airtalk_capture.py
```

Live framed display (same parser instance as the web monitor):

``` text
GET  /debug/mgl/airtalk
GET  /api/mgl-airtalk/snapshot
WS   /ws/mgl-airtalk
```

JSONL of OK frames is appended to `/tmp/cozy-airtalk-frames.jsonl` on
the Pi while cozy-web is running. Do not run the CLI capturer at the
same time: USB CDC is exclusive.

Example diagnostic output (verified):

``` text
DST=FF LEN=04 TYPE=32 DATA=5A 00 02 CHECK=OK     # mag heading 90°
DST=FF LEN=12 TYPE=37 DATA=05 … CHECK=OK          # Euler10 attitude
```

------------------------------------------------------------------------

## 14. Validated live decode

Checked on the aircraft Airtalk tap against the MGL XTreme (September
2026). All multi-byte fields are **little-endian**. Destinations `$E4`
(historical SP-2) were **not** seen; heading and attitude are both
broadcast to `$FF`. Destination `$E6` type `$01` appears at about 1 Hz
with payload `80 00 00 00` and is **not yet decoded**.

### 14.1 Magnetic heading — dest `$FF` type `$32`

| Item | Value |
| --- | --- |
| Rate | ≈ 5.8 Hz |
| Length field | `$04` (type + 3 data bytes) |
| Data | `hdg_lo, hdg_hi, status` |

-   Heading = `uint16` LE, **1 degree per count**, range observed 0…359.
-   Example: `5A 00 02` → heading **90°**, status `$02`.
-   i16 LE and u16 LE are the same because heading stays below 32768.
-   i16 BE is the swapped bytes (90 → 23040) and is **not** a heading.
-   Status byte has been `$02` in all captures so far; meaning unknown.
-   Matches the XTreme magnetic heading display.

This is the operational compass value for VH-COZ, whether it originates
in the SP-2 or is rebroadcast by the XTreme.

### 14.2 Attitude — dest `$FF` type `$37` subtype `$05` (Euler10)

Matches SP-4 OEM **Attitude message format six (Euler10)**, type `$37`,
subtype `$05`, length `$12`, about **9–10 Hz**. First data byte is the
subtype. Remaining payload (17 bytes after the type) is interpreted as:

  Offset  Type     Field           Scale / notes
  ------- -------- --------------- --------------------------------------
        0 byte     Subtype         `$05` Euler10
      1–2 int16    Bank / roll      divide by 10 → degrees
      3–4 int16    Pitch            divide by 10 → degrees
      5–6 int16    Yaw              divide by 10 → degrees
        7 sint8    Slip             −50…+50, matches ball
      8–9 fps      G                 LSB fraction, MSB signed integer
       10 byte     MISC            SP-4 mode bits (see below)
     11–12 uint16  Gyro heading     **always 0** on this installation
       13 byte     Reserved
       14 byte     Voltage          0.1 V steps; **observed 0**, unused
     15–16 int16   Turn rate         matches XTreme turn-rate bar (raw)

`fps` G: `value = signed_MSB + LSB/256`. At rest this is about **1.02 g**.

MISC (SP-4): bit 0 = gyro mode (1) vs accelerometer-erect mode (0);
bit 1 = gyro over-range; bit 2 = at operating temperature. Live idle
value `$04` = accelerometer mode, at temperature.

#### Sign conventions (XTreme, this aircraft)

These are **not** ARINC/aviation “right-wing-down positive” conventions.
Record them for FIX mapping; do not silently negate later.

  Quantity     Positive sense                         Verified
  ------------ -------------------------------------- ----------
  Pitch        Nose / sensor up                      Yes
  Roll (bank)  Left (left wing down / roll left)       Yes
  Yaw          Increases as the unit is turned, like  Yes
               a directional gyro. Initialises to
               **0** at power-up; not magnetic heading
  Slip         Ball sliding to the **right**         Yes
  G            Normal acceleration; ≈ 1 g at rest     Yes
  Turn rate    XTreme turn-rate bar, **right**        Yes
  Gyro heading Field present, always 0               Yes (unused)

Yaw is the AHRS yaw state, not FF/32 magnetic heading. After power-up it
starts at 0° and then tracks rotation.

Turn rate **correlates** with the EFIS turn-rate bar (positive right).
The raw int16 scale in deg/s is **not** yet calibrated.

### 14.3 Decoder implementation

Provisional decode lives in `web/app/services/airtalk_frames.py`
(`decode_fields`). Unit tests cover FF/32 = 90° and two FF/37 Euler10
frames (level and displaced). This is **not** yet a FIX-Gateway plugin.

------------------------------------------------------------------------

## 15. Remaining protocol work

Still open after the live check:

-   Meaning of FF/32 status byte (`$02`).
-   FF/37 gyro-heading field (always 0) and voltage field (always 0).
-   Turn-rate engineering units (deg/s vs raw).
-   Destination `$E6` type `$01` payload.
-   Whether dest `$E4` appears in flight or only FF/32 is used.
-   SP-7 OEM Airtalk document, if it exists, to confirm Euler10 vs a
    native SP-7 format that happens to match.
-   FIX keys, stale times (use ≈ 5.8 Hz heading and ≈ 9.3 Hz attitude),
    and sign handling for roll (positive left).

Do not treat decoded Pi values as flight-critical.

## 16. FIX-Gateway Integration

The final acquisition software should be implemented as a dedicated
FIX-Gateway plugin, provisionally:

``` text
mgl_airtalk
```

This is deliberately separate from the `mgl_can` plugin.

``` text
                 MGL data sources

       Airtalk                    CAN
          │                        │
          ▼                        ▼
  mgl_airtalk plugin         mgl_can plugin
          │                        │
          └──────────┬─────────────┘
                     ▼
                 FIX-Gateway
                     │
          canonical/current values
                     │
                     ▼
                  Historian
```

The objective is that downstream applications do not need to understand
Airtalk.

They consume named FIX values regardless of whether a value originated
from Airtalk, MGL CAN, Stratux, GPS or another source.

------------------------------------------------------------------------

## 17. Proposed `mgl_airtalk` Plugin Responsibilities

The plugin should eventually:

1.  Open the configured receive-only serial device.
2.  Maintain an Airtalk byte-stream parser.
3.  Detect STX/ETX framing.
4.  Validate message length.
5.  Validate checksum.
6.  Timestamp received frames.
7.  Identify source/device/message type.
8.  Decode supported SP-2 and SP-7 messages.
9.  Convert raw values to engineering units.
10. Publish selected values into FIX-Gateway.
11. Maintain quality/stale information using FIX-Gateway mechanisms.
12. Expose diagnostics without creating a second independent serial
    reader.
13. Maintain counters for good/bad/unknown frames.
14. Optionally retain unknown packet statistics for future protocol
    development.

------------------------------------------------------------------------

## 18. FIX Data Mapping -- Placeholder

The detailed FIX mapping will be completed after the protocol is
captured and the current FIX-Gateway database conventions are inspected.

Do **not** hard-code final key names from this document.

Provisional mapping (source-specific; `STRX_PITCH`/`STRX_ROLL`/`STRX_HEAD` stay Stratux):

  -------------------------------------------------------------------------
  Source     MGL         FIX meaning        FIX key            Units      Status
             Parameter
  ---------- ----------- ------------------ ------------------- ---------- ----------
  SP-7       Roll        Bank, **+ left**  `MGL_AT_ROLL`      deg        Live
                         (FF/37 /10)

  SP-7       Pitch       Pitch, **+ up**   `MGL_AT_PITCH`     deg        Live

  SP-7       Yaw         AHRS yaw, 0 at    `MGL_AT_YAW`       deg        Live
                         power-up                                 (not mag)

  SP-7       Turn rate   Matches XTreme     `MGL_AT_TURN`      raw        Live
                         bar, **+ right**                          (scale TBD)

  SP-7       Total G     Normal accel       `MGL_AT_G`         g          Live
                                                                   (~1 g rest)

  SP-7       Slip        Ball, **+ right** `MGL_AT_SLIP`      ---        Live

  SP-7       Status      MISC bits        `MGL_AT_MISC`      ---        Partial

  SP-7       Gyro hdg    SP-4 field         ---                 deg        Unused (0)

  Compass    Heading     Magnetic heading   `MGL_AT_HEAD`      deg        Live
                         (FF/32, 1 deg)

  Compass    Status      FF/32 byte 2      `MGL_AT_HEAD_STATUS` ---        Observed $02
  -------------------------------------------------------------------------

Plugin: `fix_gateway_plugins/cozy_mgl_airtalk` (`module: cozy_mgl_airtalk`).
Keys are defined in `config/fixgw/database/custom.yaml`. Live page shows
`MGL_AT_*` instruments above Stratux `STRX_PITCH`/`STRX_ROLL`/`STRX_HEAD`.

### FIX integration hooks

``` text
TODO: Inspect current FIX-Gateway database key definitions.

TODO: Determine which standard/canonical keys already exist.

TODO: Determine whether source-specific MGL keys are also required.

TODO: Define source priority/quorum where Stratux and MGL provide
      equivalent attitude parameters.

TODO: Define stale periods from measured rates (heading ≈ 5.8 Hz,
      attitude ≈ 9.3 Hz).

TODO: Define quality behaviour after checksum/frame errors.
```

Diagnostic page (engineering, not FIX): `/debug/mgl/airtalk`
(legacy redirect `/debug/mgl-airtalk`).

------------------------------------------------------------------------

## 19. Suggested Plugin Configuration -- Placeholder

A possible configuration shape is:

``` yaml
mgl_airtalk:
  load: yes
  module: plugins.mgl_airtalk

  # Nano 33 BLE USB CDC (not Pi GPIO UART)
  port: /dev/serial/by-id/usb-Arduino_Nano_33_BLE_FD3737723CBA566C-if00
  baud: 115200   # USB dump from the Nano; Airtalk on the wire is 19200

  # Safety: receiver implementation only.
  receive_only: true

  # Protocol debugging
  log_unknown_frames: true
  raw_capture: false

  # TODO
  sp2:
    enabled: true

  sp7:
    enabled: true
```

This is a **design placeholder**, not a final FIX-Gateway configuration
schema.

The plugin should follow the conventions of the existing FIX-Gateway
plugin framework once implementation begins.

------------------------------------------------------------------------

## 20. Diagnostics

A useful diagnostic view should expose:

``` text
UART device
UART state
bytes received
frames received
valid frames
checksum failures
framing failures
unknown destinations
unknown message types
last SP-2 frame time
last SP-7 frame time
SP-2 frame rate
SP-7 frame rate
last decoded values
raw frame sample
```

Engineering view is implemented at `/debug/mgl/airtalk` (Cozy web).
The FIX-Gateway plugin is the **sole** owner of the Nano USB port.
The web debug page does not open the serial device unless
`COZY_AIRTALK_WEB_SERIAL=1` (and `fixgateway` is stopped).

------------------------------------------------------------------------

## 21. Historian Interface

The historian remains downstream of FIX-Gateway.

``` text
Airtalk
   ↓
mgl_airtalk
   ↓
FIX-Gateway current-state database
   ↓
Historian sampler
   ↓
Flight database
```

This preserves the overall architecture: hardware-specific plugins
decode sources, FIX-Gateway provides the current aircraft state, and the
historian performs regular time-grid recording and provenance/quality
storage.

Raw Airtalk captures are primarily engineering/development artefacts and
need not become the normal historian format.

------------------------------------------------------------------------

## 22. Commissioning Sequence

### Stage A -- electrical bench test

-   [x] 10 kΩ / 18 kΩ divider into Nano 33 BLE D4 (3.3 V).
-   [x] D3 high-Z; no TX onto Airtalk.
-   [ ] Scope traces of Airtalk high/low (optional).
-   [ ] Permanent Schmitt-buffer receiver.

### Stage B -- raw UART capture

-   [x] 19,200 8N1 on the Nano; USB 115200 to the Pi.
-   [x] Stable reception, STX/ETX, XOR checksum.

### Stage C -- heading (FF/32)

-   [x] Identify broadcast type `$32`.
-   [x] uint16 LE, 1 deg; matches XTreme mag heading.
-   [ ] Status byte `$02` meaning.
-   [x] FIX key `MGL_AT_HEAD`.

### Stage D -- attitude (FF/37 Euler10)

-   [x] Type `$37` subtype `$05`, ≈ 10 Hz.
-   [x] Bank/pitch/yaw/slip/G/turn vs XTreme (see §14).
-   [ ] Turn-rate scale in deg/s.
-   [ ] `$E6` type `$01`.

### Stage E -- plugin prototype

-   [x] Common parser (web monitor).
-   [x] Heading + Euler10 decode (provisional).
-   [x] Tests from saved flight captures.
-   [x] Publish provisional FIX values (`MGL_AT_*`).

### Stage F -- aircraft-quality receiver

-   Replace bench divider with buffered/protected receiver.
-   Review grounding and EMC.
-   Secure wiring and connectors.
-   Verify no effect on existing MGL equipment.

### Stage G -- operational FIX integration

-   Finalize FIX key mapping (watch roll sign: + left).
-   Configure stale/tolerance behaviour.
-   Integrate diagnostics into the plugin (one USB owner).
-   Connect to historian.
-   Perform ground and flight validation.

------------------------------------------------------------------------

## 23. Safety and Failure Behaviour

The Pi data collector is **supplementary equipment**. Loss or corruption
of Pi data must not affect the installed MGL system.

The intended failure behaviour is:

``` text
Pi powered off       → MGL system continues normally
Pi software crashed  → MGL system continues normally
Pi UART disabled     → MGL system continues normally
Pi disconnected      → MGL system continues normally
```

This is one reason for using a passive parallel tap and omitting the TX
connection.

No decoded Pi value should be treated as flight-critical until its
source, scaling, update rate, validity behaviour and failure modes have
been verified.

------------------------------------------------------------------------

## 24. Open Items

-   [ ] Photograph/document the existing VH-COZ Airtalk harness.
-   [ ] Capture oscilloscope traces (optional; tap already works).
-   [ ] Recover/find SP-7 OEM communications documentation if possible.
-   [ ] FF/32 status byte; FF/37 gyro-heading and voltage fields.
-   [ ] Turn-rate scale (deg/s).
-   [ ] Decode dest `$E6` type `$01`.
-   [ ] Finalize permanent receiver circuit.
-   [x] `mgl_airtalk` FIX-Gateway plugin (one owner of the Nano USB port).
-   [x] FIX keys, including roll **positive left** (`MGL_AT_*`).
-   [ ] Historian integration and validation tests.

------------------------------------------------------------------------

## 25. Reference Links

### MGL Avionics

1.  [SP-7 AHRS
    documentation](https://www.mglavionics.co.za/Docs/SP-7.pdf)
2.  [SP-6 / SP-7 installation
    manual](https://ww.mglavionics.co.za/Docs/SP6-SP7.pdf)
3.  [SP-4 AHRS OEM communications
    documentation](https://www.mglavionics.co.za/Docs/SP-4.pdf)
4.  [MGL Legacy AHRS and Compass
    page](https://mglavionics.co.za/legacy4.html)
5.  [MGL Legacy Accessories -- Airtalk
    interfaces](https://mglavionics.co.za/legacy3.html)
6.  [MGL SP-7 product page](https://w.mglavionics.co.za/sp7.html)

### Raspberry Pi / software

7.  [Raspberry Pi
    Documentation](https://www.raspberrypi.com/documentation/)
8.  [FIX-Gateway GitHub
    repository](https://github.com/makerplane/FIX-Gateway)

------------------------------------------------------------------------

## 26. Document Status

Hardware tap, framing, magnetic heading (FF/32) and Euler10 attitude
(FF/37) are recorded from live VH-COZ traffic and XTreme comparison
(section 14).

Still open:

-   permanent protected receiver schematic
-   `mgl_airtalk` FIX-Gateway plugin
-   FIX key mapping and roll sign
-   stale/quality rules
-   historian validation
-   unused/always-zero FF/37 fields and `$E6` `$01`

This document is the commissioning and decode reference for the VH-COZ
Airtalk data source.
