# Pi MGL Servo Emulator Module
## Specification and Test Plan

**Project:** VH-COZ Raspberry Pi / FIX-Gateway avionics data system  
**Module:** MGL CAN Autopilot Servo Emulator  
**Status:** Stage 1 implemented (Plan B). T13 capture matches published identify/position on CAN. T14 bank identify: Pi replies on `0x101` but XTreme V1 reports **no data received**. TX locked off by default.

## 1. Purpose

The Pi MGL Servo Emulator shall integrate with the existing MGL CAN monitor and provide virtual MGL autopilot servos on the aircraft CAN bus. Its first purpose is **not to move an actuator**; it is to make the XTreme believe valid MGL bank and pitch servos are present so that the Pi can capture and log the XTreme's steering commands.

Initial virtual servos:

- Servo 1 — Bank / Roll
- Servo 2 — Pitch

The emulator shall support the XTreme's normal **Identify Servo** procedure, accept the identity assigned by the XTreme, receive position commands, and return valid servo status/current-position replies.

## 2. Design principles

1. Reuse the existing `python-can` / SocketCAN `can0` implementation.
2. Keep one production CAN receive/dispatch path; the emulator subscribes to that path.
3. Receive-only by default; active CAN transmission requires explicit configuration and runtime arming.
4. No aircraft-control actuation in this phase.
5. Log every relevant raw CAN frame before interpretation.
6. Preserve unknown bits/bytes for later analysis.
7. On timeout, crash, CAN error, or disarm, stop transmitting rather than inventing continued state.
8. Prove on `vcan0`, then physical bench CAN, then stationary-aircraft ground tests.

## 3. Protocol basis

MGL autopilot servo CAN uses standard 11-bit CAN at **250 kbit/s**.

```text
CAN_ID = (device_address << 4) | message_id
```

The MGL host/EFIS logical address is 1. Servo addresses are 16–31:

```text
device_address = (servo_number - 1) + 16
```

Thus:

| Servo | MGL function | Device address | Reply CAN ID for Msg 1 |
|---:|---|---:|---:|
| 1 | Bank / Roll | 16 | 0x101 |
| 2 | Pitch | 17 | 0x111 |
| 3 | Yaw | 18 | 0x121 |
| 4 | Throttle / Other | 19 | 0x131 |

Host-originated servo messages use host address 1:

```text
Set Servo Number: CAN ID 0x010
Set Position:     CAN ID 0x011
```

## 3.1 Protocol sources

| Source | What it defines |
|---|---|
| [MGL Autopilot servo interface protocols](https://mglavionics.eu/lignes/MGL/pdf/Servo_communications_protocol.pdf) | CAN 250 kbit/s identify (`0x010` DLC 4), set position (`0x011` DLC 4), position reply (`0x101`/`0x111` DLC 5). Success = host sees position replies after identify + ≥100 ms + a position command. |
| `doco/MGL CAN Protocol.pdf` | Shared 11-bit addressing (host 1, servos 16–31). Does **not** document autopilot servo payloads (those are SP-10 / RDAC / AHRS). |
| XTreme-EFIS Operating Manual **§4.16 Autopilot Setup** (pp. 113–117) | What this EFIS actually does in the Identify / limit / torque UI. Ground truth for T14 UX. |

## 3.2 XTreme V1 Autopilot Setup (operating manual §4.16)

This is the procedure the emulator must satisfy. Summary of the VH-COZ XTreme manual, not a substitute for it.

**Enable:** BANK SERVO / PITCH SERVO selected as installed.

**Identify Bank / Identify Pitch**

- Autopilot not engaged, no flight active.
- **Only one servo may be connected** (disconnect the other).
- Operator runs IDENTIFY BANK SERVO (or PITCH).
- EFIS shows a confirmation, then after **a few seconds** either success **or “no data has been received”**.
- Failure text tells the operator to check **power and signal wiring**. Bank-limit text says **serial communications**; pitch-limit text also says **correct COM Extender port**.

That serial/COM Extender wording is a first-class risk for this project: XTreme V1 may judge identify success on **RS232**, even when it also emits the CAN identify/position frames captured in T13/T14.

**Left/right and pitch up/down limits**

- Cannot use or test MGL servos until limits (and thus direction) are set.
- Operator moves the **stick** to the desired stop. The EFIS shows **current position 0..4095**.
- That number is the **servo encoder**, not a stick pot: moving the stick moves the servo arm through the linkage; the servo replies with current position.
- A virtual echo of target `0` will **not** make that field change. Limit setup needs a way to vary reported current position (debug setter, or a later sensor mapping).
- Settings are stored only after exiting all menus.

**Bank / pitch control (later calibration, T16+)**

| Setting | Role |
|---|---|
| Target rate of turn | ~2.0–3.0 °/s for large heading errors |
| Bank/pitch servo torque | Slip threshold; 100% = max; set so the pilot can override |
| Bank servo magnitude | Servo travel vs bank-angle error; start at 10, typical 10–30 |
| Heading control | Slow / Medium / Fast intercept |
| Pitch angle control magnitude | Start at 10; sensitive airframes ~5–8 |
| Pitch change to VSI reaction | Slow / Medium / Fast |
| Low/High ASI, target VSI | Airspeed has priority over climb/descent rate |

Torque in this UI is the **host command** (options bits 4–7 on CAN), not the torque byte we return.

**Servo test functions** move the arm to stored positions. The emulator must not be treated as a control actuator; those tests are for a real servo.

## 3.3 Live XTreme V1 (VH-COZ) vs published CAN — 2026-09-13

| Item | Published | Observed |
|---|---|---|
| Identify | `0x010` DLC 4 `AA 55 nn ~nn` | **DLC 8**, same 4 bytes + `00` pad. Bank → servo **1**. |
| Set position | `0x011` DLC 4 ~10 Hz | **DLC 8**, **~17 Hz**, **both** servo 1 and 2: `01 40 00 00` / `02 40 00 00` |
| Options | bit 0 engage (RS232 clear; CAN text has a typo) | Live byte **`0x40`** (bit 6 / torque nibble 4). Engage still unverified. |
| After identify | Wait ≥100 ms, then position, then expect DLC 5 `0x101` | XTreme **stops `0x011` for ~550 ms**, then resumes. Identify UI then reports **no data received**. |
| Reply `0x101` | DLC 5 status/pos/volt/torque | Pi sent this (T14a late DLC 5; T14b immediate DLC 8; T14c immediate DLC 5 at **+1.7 ms**). Bus TX errors **0**. XTreme still failed identify. |

So: the Pi **is** on the CAN bus, **does** accept servo 1, **does** transmit `0x101`. The XTreme identify dialog does **not** accept those frames. Next checks: Autopilot interface is CAN not RS232/COM Extender; whether identify success is scored on a different CAN ID/DLC; whether a second “connected” servo (pitch commanded as 2 with no reply) fails the “only one servo” rule.

## 4. Host → Servo messages

### 4.1 Message ID 0 — Set Servo Number

**CAN ID:** `0x010`  
**DLC:** 4

| Byte | Meaning |
|---:|---|
| 0 | `0xAA` |
| 1 | `0x55` |
| 2 | Requested servo number `0..16` |
| 3 | Byte 2 XOR `0xFF` |

Servo number 0 is the unidentified/virgin state.

MGL's recommended identification sequence is:

1. Host sends Message ID 0 with the desired servo number.
2. Wait at least 100 ms.
3. Host sends Position Message ID 1.
4. Servo returns Position Reply Message ID 1.

Only **one virtual virgin servo may be armed for identification at a time**.

### 4.2 Message ID 1 — Set Position

**CAN ID:** `0x011`  
**DLC:** 4

| Byte | Meaning |
|---:|---|
| 0 | Servo number `1..16` |
| 1 | Options byte |
| 2 | Target position LSB |
| 3 | Target position MSB |

```text
target_position = byte2 | (byte3 << 8)
```

Valid position range: `0..4095`.

The published protocol defines the options byte as containing:

- engage/disengage request
- torque-measurement reset
- torque setting in bits 4–7

The published CAN text appears to contain a wording/bit-number typo around the engage field. The RS232 form clearly uses bit 0 for engage. Therefore the implementation shall provisionally treat **bit 0 as engage**, preserve the complete raw options byte, and verify the mapping empirically against XTreme behaviour before relying on it.

## 5. Servo → Host reply

### 5.1 Message ID 1 — Position reply

**CAN ID:**

```text
((servo_number - 1 + 16) << 4) | 1
```

Examples:

```text
Bank / Servo 1  -> 0x101
Pitch / Servo 2 -> 0x111
```

**DLC:** 5

| Byte | Meaning |
|---:|---|
| 0 | Status |
| 1 | Current position LSB |
| 2 | Current position MSB |
| 3 | Servo supply voltage |
| 4 | Measured torque |

Published status bits:

```text
bit 0 = engaged
bit 1 = slipping
bit 2 = voltage alarm
```

Current position:

```text
current_position = byte1 | (byte2 << 8)
```

Voltage encoding:

```text
Vservo = 5.0 + 0.1 * voltage_byte
```

For a simulated 13.8 V servo:

```text
voltage_byte = 88
```

Measured torque shall initially be returned as zero unless a later dynamic model explicitly simulates it.

## 6. Virtual-servo state machine

Each virtual servo shall implement:

```text
DISABLED
   |
   | runtime arm
   v
VIRGIN
   |
   | identify_armed + valid Msg 0
   v
IDENTIFIED
   |
   | valid addressed Msg 1
   v
ACTIVE
   |
   | command timeout / disarm
   v
IDENTIFIED_IDLE
```

### DISABLED

- no servo replies
- monitor remains active
- default startup state unless explicitly enabled

### VIRGIN

- servo number 0
- no position replies
- accepts identification only if `identify_armed=true`

### IDENTIFIED

- assigned servo number retained in runtime state
- persistence to configuration requires explicit operator action
- valid addressed position commands produce replies

### ACTIVE

- valid position commands arriving within timeout
- reply to each valid addressed command

### IDENTIFIED_IDLE

- identity retained
- no unsolicited replies
- virtual engaged state cleared after timeout

## 7. Multi-servo identification

Recommended commissioning flow:

```text
Virtual servo A:
  role = ROLL
  number = 0
  identify_armed = true

XTreme -> Identify Bank Servo
Pi -> accept assignment, expected number 1
Pi -> disarm A identification

Virtual servo B:
  role = PITCH
  number = 0
  identify_armed = true

XTreme -> Identify Pitch Servo
Pi -> accept assignment, expected number 2
Pi -> disarm B identification
```

If the XTreme assigns a number inconsistent with the expected role, raise a warning and preserve the observed assignment rather than silently rewriting it.

## 8. Reply models

### 8.1 Echo mode

Initial compatibility mode:

```text
current_position = target_position
engaged = requested engage state
slipping = false
voltage_alarm = false
measured_torque = 0
```

This presents a perfect instantaneous servo and is intended to determine whether the XTreme accepts the emulator and continues generating steering commands.

### 8.2 Dynamic model

Later test mode with finite motion:

```text
error = shortest_circular_error(target, current)
current += clamp(error, -max_step_per_update, +max_step_per_update)
```

Configurable parameters:

- maximum position rate
- optional acceleration limit
- simulated torque
- simulated supply voltage
- optional slip threshold
- optional response lag

This mode can test whether the XTreme uses returned actual position as part of its autopilot logic.

## 9. Circular 12-bit position arithmetic

Use shortest-path circular arithmetic:

```text
error = ((target - current + 2048) % 4096) - 2048
```

Do not use raw subtraction across the 4095/0 boundary.

Historian should retain both raw 12-bit target/current values and, where useful, an unwrapped analysis series.

## 10. Command rate and timeout

MGL recommends servo position commands at approximately **10 Hz**, even if unchanged. A physical servo disengages if regular requests stop.

The emulator shall calculate:

- command interval
- rolling command frequency
- min/max interval
- last valid command timestamp
- missed/timeout count

Initial configurable timeout:

```text
300 ms
```

On timeout:

- clear virtual engaged state
- retain servo identity
- do not transmit unsolicited frames

## 11. Integration with current CAN monitor

**Plan B (implemented):** RDAC ingest and the servo emulator are **separate FIX plugins** on the same SocketCAN interface.

- `cozy_mgl_can` remains receive-only (`MGL_RDAC_*`).
- `cozy_mgl_servo` is the **sole CAN transmitter** for servo replies (`MGL_SRV_*`).
- Protocol decode/encode/state/rates live in one library (`web/app/services/mgl_servo/`) so the stacks cannot drift.
- Linux SocketCAN delivers every RX frame to every socket. Two sockets are expected; two protocol implementations are not.
- The web CAN page may listen for display only. It must never transmit.

```text
SocketCAN can0 / vcan0
     |
     +-- cozy_mgl_can (RX only) -----> MGL_RDAC_*
     |
     +-- cozy_mgl_servo (RX + interlocked TX)
              |
              +--> protocol library (identify / position / echo / rates)
              |
              +--> MGL_SRV_* FIX keys (commands vs replies named separately)
              |
              v
         TX only if allow_tx AND tx_armed AND valid command
```

The web CAN monitor is not a production TX path.

### 11.1 TX interlock

Every emulator transmission shall satisfy:

```text
allow_tx
AND tx_armed
AND emulator enabled
AND interface_ok
AND servo enabled
AND valid emulator state
AND valid received command
```

Default aircraft configuration:

```yaml
allow_tx: false
tx_armed: false
```

A TX exception disarms `tx_armed` immediately.

## 12. Software structure (Plan B)

```text
web/app/services/mgl_servo/
    protocol.py      decode/encode, circular error, voltage byte
    interlock.py     tx_allowed()
    emulator.py      VirtualServo, ServoEmulator, rates/timeouts, FIX mapping
    control.py       Autopilot page install-mode JSON

fix_gateway_plugins/cozy_mgl_servo/   FIX plugin (MGL_SERVO)
config/fixgw/connections/mgl_servo.yaml
config/fixgw/database/mgl_servo.yaml
web/tests/test_mgl_servo.py           T0–T5, T7, T8, T11, install wizard
```

Install commissioning UI: Cozy **MGL → AutoPilot** (`/debug/mgl/autopilot`). It writes `data/mgl_servo_control.json`; `cozy_mgl_servo` polls that file so identify/limits can be armed without restarting FIX. The limits slider sets reported current position (no servo encoder on the Pi).

`cozy_mgl_can` is unchanged except that host/servo IDs are labelled in `decode_map.yaml` for the debug CAN page.

## 13. Provisional configuration

See `config/fixgw/connections/mgl_servo.yaml`. Aircraft defaults:

```yaml
mgl_servo:
  load: MGL_SERVO
  module: cozy_mgl_servo
  channel: can0
  enabled: true          # listen and publish FIX
  allow_tx: false        # no replies
  tx_armed: false
  command_timeout_ms: 300
  engage_bit: 0
  servos:
    roll:
      enabled: true
      expected_number: 1
      servo_number: 0
      identify_armed: false
      mode: echo
    pitch:
      enabled: true
      expected_number: 2
      servo_number: 0
      identify_armed: false
      mode: echo
```

## 14. Data exposed to FIX / historian

Exact key names shall be aligned with the current FIX-Gateway database conventions. Required semantic values per servo:

```text
role
servo_number
device_address

target_position_raw
target_position_unwrapped
current_position_raw
current_position_unwrapped
position_error

options_raw
engage_requested
torque_setting_raw
torque_reset_requested

status_raw
engaged_reported
slipping_reported
voltage_alarm
simulated_voltage
measured_torque_raw

command_rate_hz
command_age_ms
command_count
reply_count
invalid_command_count
timeout_count

identified
identify_armed
emulator_enabled
tx_armed
```

The historian shall clearly distinguish **XTreme command values** from **emulator-generated reply values**.

## 15. Diagnostics

A `/debug/mgl-can/servos` style view/API should show:

```text
CAN interface and state
TX allowed / TX armed
bus errors / bus-off count

ROLL:
  servo number
  reply CAN ID
  identification state
  target position
  simulated current position
  raw options
  engage request
  torque setting
  command rate / age
  command and reply counts
  errors

PITCH:
  same fields
```

Raw-frame diagnostics shall show timestamp, RX/TX direction, CAN ID, DLC, payload and decoded meaning. TX frames must be visually distinct from received frames.

## 16. Logging requirements

For every relevant frame record:

- monotonic timestamp
- UTC/system timestamp where available
- RX/TX direction
- CAN ID
- DLC
- exact payload bytes
- decoded message type
- servo number
- servo role if known
- target/current position where applicable
- complete raw options/status bytes
- decoder version
- emulator mode

Unknown fields shall be retained.

## 17. Safety interlocks

### Software

- `allow_tx=false` by default
- separate runtime `tx_armed`
- no automatic transition from passive monitor to active emulator
- only one virgin servo may be identification-armed
- malformed identification or position commands produce no reply
- CAN TX exceptions disarm emulator TX
- timeout clears virtual engaged state
- restart returns to safe configured state

### Operational

Initial aircraft tests shall be stationary ground tests. The emulator shall not be connected to any S-TEC servo-driver interface. No real MGL autopilot servo should share the identification experiment unless its behaviour is deliberately part of the test, because the MGL protocol's normal identification procedure assumes one unidentified servo is connected at a time.

# TEST PLAN

## T0 — Configuration and no-TX sanity

Verify:

- emulator disabled by default
- `allow_tx=false`
- `tx_armed=false`
- no code path can transmit with either interlock false
- invalid servo numbers are rejected
- no more than one virtual servo can be `identify_armed`

**Pass:** default configuration is completely passive.

## T1 — Circular position unit tests

Test:

```text
100 -> 200
200 -> 100
4090 -> 10
10 -> 4090
0 -> 4095
4095 -> 0
0 -> 2048
2048 -> 0
```

**Pass:** no false large jump across 4095/0.

## T2 — Identification-message decoder

Inject:

```text
ID   0x010
DLC  4
DATA AA 55 01 FE
```

Expected: valid request for servo 1.

Negative cases:

```text
AA 55 01 FF
AB 55 01 FE
AA 54 01 FE
wrong DLC
extended CAN frame
```

**Pass:** only valid messages are accepted.

## T3 — Identification state machine

Start roll virtual servo as virgin and identification-armed. Inject valid assignment to servo 1.

Verify:

```text
roll.servo_number = 1
roll.identify_armed = false
roll.reply_id = 0x101
```

Repeat for pitch as servo 2 -> reply ID `0x111`.

## T4 — Position-command decoder

Inject host ID `0x011` containing:

- servo number 1
- known options pattern
- known 12-bit target position

Verify correct servo selection, little-endian decode, raw options preservation, timestamp and counters.

Commands for unrelated servo numbers must not trigger a reply from the wrong virtual servo.

## T5 — Reply encoder

For bank servo 1, configure:

```text
position = 0x0567
engaged = true
slipping = false
voltage alarm = false
voltage = 13.8 V
torque = 0
```

Verify:

```text
CAN ID = 0x101
DLC = 5
position bytes = 67 05
voltage byte = 88
```

Repeat pitch -> CAN ID `0x111`.

## T6 — `vcan0` integration

Run the existing MGL CAN monitor plus emulator on Linux `vcan0`, with an independent test harness acting as the XTreme.

Sequence:

1. send bank identification
2. wait >100 ms
3. send bank position command
4. verify emulator reply
5. repeat at 10 Hz
6. sweep position through the 4095/0 boundary
7. repeat for pitch

Verify the monitor and emulator use the same receive/dispatch architecture and historian distinguishes RX from TX.

## T7 — Frequency and timeout

Send position commands at 10 Hz, 5 Hz, 2 Hz and irregular intervals, then stop.

Verify:

- measured rate and age
- timeout event at configured threshold
- engaged state clears
- no unsolicited replies after host commands stop

## T8 — Echo-mode behaviour

Exercise:

- engage/disengage
- torque-setting nibble
- torque-reset bit
- repeated identical target
- rapid target changes
- wrap boundary

Verify `current_position == latest target_position` in echo mode.

## T9 — Dynamic model

Configure finite position rate. Apply step commands and verify current position moves toward target by shortest circular route, remains stable through wrap and reports the simulated lag correctly.

## T10 — Physical bench CAN

Hardware:

- Pi 5
- Pi-safe CAN interface
- CAN analyzer or second CAN node
- correct bench termination
- no aircraft connection

Verify 250 kbit/s, 11-bit IDs, correct physical frames, no error frames or bus-off. Repeat T2–T9.

## T11 — Physical TX-interlock test

On bench:

1. `allow_tx=false`, try to identify
2. `allow_tx=true`, `tx_armed=false`, try again
3. both true, identify
4. remove runtime arm while active

Expected: no TX in 1–2, correct TX in 3, immediate cessation in 4.

## T12 — Aircraft passive baseline

Aircraft stationary, emulator TX disabled.

Verify:

- 250 kbit/s
- expected RDAC traffic
- no unexplained existing traffic in servo address range 16–31
- no CAN errors
- baseline bus load

**Go/no-go:** stop if servo-address traffic is unexplained.

## T13 — Observe XTreme Identify Servo with TX disabled

Enter XTreme autopilot setup and operate **Identify Servo** while Pi remains passive.

Capture the exact ID/data/timing. Confirm whether XTreme V1 emits:

```text
0x010  AA 55 <servo> <servo XOR FF>
```

This test validates the published protocol against this exact XTreme before the Pi replies.

## T14 — Identify virtual bank servo

Conditions:

- aircraft stationary
- no physical MGL servo involved
- no S-TEC actuator connection to emulator
- roll virtual servo only
- TX explicitly armed

Use XTreme `IDENTIFY BANK SERVO` (manual §4.16). AP not engaged, no flight. Ideally no second MGL servo on the bus.

**T14 result (2026-09-13):** Pi accepted servo 1 and transmitted `0x101`. XTreme reported **no data received** for:

- T14a: DLC 5 replies starting 553 ms after identify (first reply coincident with resumed `0x011`)
- T14b: DLC 8 immediate reply at +1.6 ms
- T14c: DLC 5 immediate reply at +1.7 ms (`00 00 00 58 00`)

All three: zero CAN TX errors; ~550 ms `0x011` gap after `0x010`. Do not treat T14 as passed. Disarm `tx_armed` after each attempt.

Expected sequence (published):

```text
XTreme -> identification command
Pi -> accepts servo 1
XTreme -> position command
Pi -> 0x101 status/position reply
XTreme -> bank servo accepted
```

Record every raw frame and timestamp, then disarm TX.

## T15 — Identify virtual pitch servo

Repeat with pitch only.

Expected:

```text
servo number 2
reply ID 0x111
```

## T16 — Autopilot disengaged baseline

With both virtual servos identified, observe commands while AP is disengaged.

Determine:

- neutral/rest target behaviour
- exact engage-bit behaviour
- normal command rate
- torque-setting field when disengaged

This is the primary test to resolve the published engage-bit ambiguity.

## T17 — Bank-command stimulation

Under a safe stationary test condition, create known heading/navigation errors where possible and record:

```text
bank target position
position change rate
engage request
torque setting
command frequency
```

Determine neutral, left/right sense, command range, and whether the target is absolute or behaves as an offset around a learned neutral.

## T18 — Pitch-command stimulation

If safe ground stimulation is possible, perform equivalent pitch tests. Do not infer aircraft-control direction until independently verified.

## T19 — Reply-loss fault injection

Inhibit emulator replies while XTreme commands a virtual servo.

Observe:

- XTreme warning/fault indication
- whether commands continue
- timeout behaviour
- recovery when replies resume

## T20 — Simulated position lag

Use the dynamic model and progressively increase lag. Determine whether XTreme modifies commands based on reported actual position and identify any fault thresholds.

## T21 — Simulated slip

Return `status.slipping=true` during a ground test and record XTreme response.

## T22 — Simulated voltage alarm

Return `status.voltage_alarm=true` and record XTreme response.

## T23 — Servo disappearance timing

Stop all replies for 100 ms, 300 ms, 500 ms and 1 s. Characterise XTreme detection and recovery.

# 18. Phase-1 acceptance criteria

Phase 1 is accepted when:

1. Existing CAN monitoring remains reliable.
2. Emulator TX is disabled by default.
3. XTreme V1 identification traffic is captured and confirmed.
4. XTreme successfully identifies Pi as Servo 1 Bank and Servo 2 Pitch.
5. Pi correctly receives and records position commands.
6. Pi returns status/current-position replies accepted by XTreme.
7. Steering target position, engage state and raw torque-setting field are logged to FIX/historian.
8. Position wrap is handled correctly.
9. Loss of commands results in safe virtual disengagement.
10. Disabling the emulator leaves the CAN logger unaffected.
11. No S-TEC or aircraft-control actuator is driven by this module.

# 19. Questions the test programme must resolve

1. Does XTreme V1 use exactly the published identification sequence?
2. Does it assign Bank=1 and Pitch=2 as documented?
3. Does Identify success look at **CAN `0x101`** or at **RS232 / COM Extender** (manual §4.16 wording)?
4. What is the exact engage bit used by this XTreme?
5. What torque-setting values does XTreme command?
6. What target position is neutral for each axis?
7. What command range does XTreme use in practice?
8. Are target positions absolute coordinates or continuously re-centred around a captured neutral?
9. Does XTreme alter its control law based on returned current position?
10. What reply latency is tolerated?
11. What happens if returned position does not follow target?
12. What happens on slip, voltage alarm, stale reply or complete servo loss?
13. Can both virtual servos remain active indefinitely without disturbing unrelated MGL CAN traffic?
14. How will left/right (pitch up/down) **limit setup** get a changing 0..4095 without a physical servo arm?

# 20. Future interface

Once Phase 1 is proven, the captured MGL position command can feed a **separate** future module:

```text
XTreme MGL servo position command
          |
          +--> historian / system identification
          |
          +--> translator/controller
                    |
                    +--> S-TEC analogue guidance input
                    |
                    or
                    |
                    +--> independent S-TEC servo controller
```

The S-TEC control function is intentionally outside this specification.

