# Pitch and Roll Control Encoder Interface
## Cozy III Flight Data System

**Status:** Specification (firmware not yet implemented). A/B interface **confirmed:** NPN/open-collector with **4.7 kΩ pull-up to Nano 3.3 V**. Encoder supply current is **negligible** on Pi USB 5 V.  
**MCU:** Arduino Nano 33 BLE (nRF52840, 3.3 V I/O) already used as the receive-only MGL Airtalk tap.  
**Firmware:** `hardware/nano_airtalk_monitor/` (`v5`: Airtalk + encoders + Matek ASPD-4525 I²C).  
**Diagrams:** [diagrams/nano_airtalk_encoder.drawio](diagrams/nano_airtalk_encoder.drawio) — system, Nano wiring, electrical, USB/FIX.  
**Build order:** [Nano_Encoder_Implementation_Plan.md](Nano_Encoder_Implementation_Plan.md).  
**Airtalk tap:** [MGL_Airtalk_to_Pi_Data_Collector_Interface_v2.md](MGL_Airtalk_to_Pi_Data_Collector_Interface_v2.md).

---

## 1. Purpose

Two incremental rotary encoders measure **pitch and roll control movement**. They connect to the **existing Nano 33 BLE** that already receives the MGL Airtalk bus and forwards data to the Raspberry Pi over USB.

| Axis | Encoder | PPR |
|---|---|---:|
| **Pitch** (stick) | Omron **E6B2-CWZ6C** 2000 P/R | **2000** |
| **Roll** (aileron / stick roll) | **HOK38H5-600N-G5-24** | **600** |

```text
MGL Airtalk (SP-7 / SP-2 / XTreme) ── 10 kΩ/18 kΩ ── D4 RX only
Roll  HOK    A/B     ── 4.7 kΩ to 3.3 V ── D2 / D5 ──┤
Pitch Omron  A/B/Z   ── 4.7 kΩ to 3.3 V ── D6 / D7 / D8 ┤ Nano 33 BLE ── USB ── Pi 5
                                                         │
                                                         └── FIX-Gateway (cozy_mgl_airtalk)
                                                                   │
                                                            MGL_AT_* + CTRL_*
                                                                   │
                                                              Historian / Web
```

The Nano counts every quadrature edge. The Pi publishes and stores values through FIX-Gateway and the Historian.

Safety boundary: **advisory / logging only**. The Nano shall not drive Airtalk, shall not command servos, and shall not replace Stratux `STRX_*` or SP-7 as an attitude source.

---

## 2. Encoder Identification

### 2.1 Pitch — Omron E6B2-CWZ6C 2000 P/R

[Omron E6B2-CWZ6C 2000P/R 2M](https://automation.omron.com/en/us/products/family/E6B2-C/e6b2-cwz6c%202000p/r%202m)

| Parameter | Specification |
|---|---|
| Type | Incremental optical rotary encoder |
| Resolution | **2000 PPR** |
| Outputs | A, B and **Z (index)** |
| Output circuit | NPN open collector |
| Supply | 5–24 V DC — **use 5 V** on this Nano |
| Supply current | Datasheet ≤80 mA; **measured / practical current negligible** on Pi USB 5 V |
| Maximum output voltage | 30 V DC |
| Maximum sink current | 35 mA |
| Output LOW | ≤0.4 V at 35 mA |
| Maximum response frequency | 100 kHz |
| Maximum shaft speed | 6000 rpm |
| Body / shaft | 40 mm / 6 mm |
| A/B phase | nominally 90° |
| Protection | IP50 |

Omron E6B2-C datasheet cable colours (**confirmed**):

| Colour | Function |
|---|---|
| BROWN | +VCC |
| BLUE | 0V / GND |
| BLACK | Channel A |
| WHITE | Channel B |
| ORANGE | Channel Z (index) |

```text
BROWN   → VCC
BLUE    → 0V / GND
BLACK   → Channel A
WHITE   → Channel B
ORANGE  → Channel Z
```

### 2.2 Roll — HOK38H5-600N-G5-24

| Parameter | Specification |
|---|---|
| Type | Incremental rotary encoder |
| Resolution | **600 PPR** |
| Outputs | A and B (no Z) |
| Output circuit | NPN / open-collector (**confirmed**, 4.7 kΩ to 3.3 V) |
| Supply | 5–24 V DC — **use 5 V** on this Nano |
| Supply current | **Negligible** on Pi USB 5 V |
| Body / shaft | ~38 mm class / ~6 mm (measure before mechanical design) |

Lead colours:

| Colour | Function |
|---|---|
| RED | VCC |
| BLACK | 0V / GND |
| WHITE | Channel A |
| GREEN | Channel B |

```text
RED     → VCC
BLACK   → 0V / GND
WHITE   → Channel A
GREEN   → Channel B
```

The two encoders do **not** share the same lead colours. Do not swap WHITE/BLACK between the Omron and the HOK.

---

## 3. Resolution

**Required decoding: x4** on both axes (every valid A/B transition).

| Axis | PPR | x4 counts / encoder rev | Encoder shaft ° / count |
|---|---:|---:|---:|
| Pitch (Omron) | **2000** | **8000** | 0.045° |
| Roll (HOK) | **600** | **2400** | 0.15° |

### 3.1 Preliminary mechanical ratio

**Stick-to-encoder ratio = 1.75** (preliminary, both axes until ground-calibrated).

Convention used in this spec:

```text
θ_encoder = 1.75 × θ_stick
```

The encoder shaft turns **1.75×** the stick angle. Invert this if the linkage is measured the other way around.

| Axis | x4 counts / stick revolution | Stick ° / count |
|---|---:|---:|
| Pitch | 8000 × 1.75 = **14000** | 360 / 14000 ≈ **0.0257°** |
| Roll | 2400 × 1.75 = **4200** | 360 / 4200 ≈ **0.0857°** |

Firmware and Historian log **raw encoder counts**. Conversion to stick degrees uses this ratio on the Pi:

```text
θ_stick_deg = count × (360 / (PPR × 4 × 1.75))
            = count × (360 / (PPR × 7))
```

| Axis | Stick degrees per raw count |
|---|---|
| Pitch | 360 / (2000 × 7) = **0.025714°** |
| Roll | 360 / (600 × 7) = **0.085714°** |

Replace 1.75 with the measured ratio after a full stick travel vs encoder-count ground test.

---

## 4. Incremental Position and Zero

Both encoders are incremental. After power-up the Nano knows movement and direction, not physical control position, except:

- **Pitch** has a **Z index** once per encoder revolution. That is a *shaft* index, not stick neutral, unless the mechanics put Z at a known stick angle. First implementation: count Z edges (`CTRL_PITCH_Z`); do **not** auto-zero the stick from Z.
- **Roll** has no Z. Neutral is USB `zero` at a known stick/aileron position.

| Option | First implementation |
|---|---|
| Neutral + USB `zero` before flight | **Yes** (both axes) |
| Pitch Z as shaft index / diagnostic | Wire and count; not stick zero |
| Absolute encoders | Out of scope |

`CTRL_ZERO_VALID` is false from boot until a successful `zero` command. Raw counts are always recorded.

---

## 5. Nano Connections

The aircraft tap is a **Nano 33 BLE**. D3 is already the Airtalk bench-test TX (high-Z in flight). D4 is Airtalk RX.

| Function | Pin | Encoder lead |
|---|---|---|
| Airtalk RX | D4 | — (as-built) |
| Bench test TX | D3 | — (INPUT in flight; not an encoder) |
| Roll A | D2 | HOK WHITE |
| Roll B | D5 | HOK GREEN |
| Pitch A | D6 | Omron BLACK |
| Pitch B | D7 | Omron WHITE |
| Pitch Z | D8 | Omron ORANGE |
| Encoder VCC | Nano **5V** | HOK RED, Omron BROWN |
| Encoder 0V | Nano **GND** | HOK BLACK, Omron BLUE (common with MGL GND) |
| NPN pull-ups | Nano **3.3V** via **4.7 kΩ** | Every A, B, and pitch Z |
| USB CDC | Native USB | FIX plugin is sole owner |

See draw.io page **2 Nano wiring** (WD-ENC-001).

### 5.1 Cable connectors

Encoder flying leads terminate in **flat single-row** plugs. The Nano harness has matching sockets. Pin numbers below are the **Cozy harness standard** (mark both plug and socket). Mating-face sketches: pin 1 at the key / chamfer (left).

**J1 — 4-pin — ROLL (HOK38H5-600N-G5-24)**

| J1 pin | Function | HOK colour | Nano |
|---|---|---|---|
| 1 | +5 V | RED | 5V |
| 2 | 0 V | BLACK | GND |
| 3 | Channel A | WHITE | D2 + R1 4.7 kΩ to 3V3 |
| 4 | Channel B | GREEN | D5 + R2 4.7 kΩ to 3V3 |

**J2 — 5-pin — PITCH (Omron E6B2-CWZ6C)**

| J2 pin | Function | Omron colour | Nano |
|---|---|---|---|
| 1 | +5 V | BROWN | 5V |
| 2 | 0 V | BLUE | GND |
| 3 | Channel A | BLACK | D6 + R3 4.7 kΩ to 3V3 |
| 4 | Channel B | WHITE | D7 + R4 4.7 kΩ to 3V3 |
| 5 | Channel Z | ORANGE | D8 + R5 4.7 kΩ to 3V3 |

Do not mix **HOK BLACK (0 V)** with **Omron BLACK (A)**.

**Hard rules**

1. Never drive Airtalk (no MCU TX on the bus).
2. Never put 5–24 V logic directly on GPIO. Pull-ups are to **3.3 V**.
3. Do not share D3 or D4 with encoders.
4. Keep Airtalk `invert=0` when encoder ISRs are enabled.
5. Do not run USB `test` with Airtalk still on D4.

---

## 6. Electrical Interface

**Output stage: NPN open collector on both encoders.** A **4.7 kΩ pull-up to Nano 3.3 V** on each signal is the aircraft wiring (confirmed on the HOK; Omron is specified NPN OC, same interface).

```text
             +3.3 V (Nano)
               |
             4.7 kΩ
               |
Encoder A/B/Z -+---------- GPIO

Encoder VCC --------------- Nano 5V
Encoder 0V ---------------- Nano GND
```

Pull-ups required: roll A, roll B, pitch A, pitch B, pitch Z (**five** resistors).

**Supply current:** negligible. Pi USB 5 V is acceptable for both encoders. Do **not** power them from 12–24 V into this Nano.

### 6.1 Unused alternative — push-pull 5 V divider

Not used. Both units are NPN OC.

### 6.2 Aircraft wiring

- Twisted A/B pairs; shield to Nano GND at **one end only**.
- Pitch Z with A/B in the same Omron cable.
- Keep encoder leads away from Airtalk and ignition leads.

See draw.io page **3 Encoder electrical**.

---

## 7. Quadrature Verification

```text
A  ____----____----____
        ┌────┐
B  __----____----____--
       ~90°
```

| Axis | x4 counts over one encoder shaft turn |
|---|---|
| Pitch | **8000** (2000 PPR) |
| Roll | **2400** (600 PPR) |

Pitch Z: one pulse per encoder revolution.

Direction convention (positive pitch = stick aft? positive roll = stick right?) is set after the first ground travel so it matches **this airframe**, not ARINC.

---

## 8. Nano Firmware

Source: `hardware/nano_airtalk_monitor/arduino/nano_airtalk_monitor/`. Banner becomes `nano_airtalk_monitor v4`.

### 8.1 State (volatile, ISR-updated)

```text
int32_t  roll_count
int32_t  pitch_count
uint32_t roll_error_count
uint32_t pitch_error_count
uint32_t pitch_z_count       // Omron Z edges
uint8_t  zero_valid          // 0 until USB zero
```

Main loop derives `roll_delta` / `pitch_delta`. Rate on the Pi = delta × 100 (counts/s). Stick degrees are **not** computed on the Nano.

### 8.2 Interrupt handlers

GPIOTE / pin-change on D2, D5, D6, D7 (and D8 for Z). Quadrature handlers shall only:

1. read the new A/B pair;
2. apply the x4 table (+1, −1, or illegal);
3. update count or error counter;
4. return immediately.

Z handler: increment `pitch_z_count` on the active edge; return. Do not zero `pitch_count` from Z unless a later calibration maps Z to stick neutral.

No USB, no floating-point, no `Serial` in the ISR. If `invert=1`, encoder ISRs shall not run.

### 8.3 Airtalk path (unchanged)

```text
D t=<us> n=<n> hex=82 … 83
```

D3 remains INPUT in flight. USB `test` is bench-only.

---

## 9. Nano-to-Pi USB Protocol

Control report **100 Hz**. Keep Airtalk `D` lines.

```text
C t=<micros> roll=<n> pitch=<n> rd=<n> pd=<n> rerr=<n> perr=<n> zp=<n> z=<0|1> psi=<f> pa=<f> tc=<f> praw=<n> pst=<n> ias=<f>
```

| Field | Meaning |
|---|---|
| `roll` / `pitch` | signed 32-bit raw counts |
| `rd` / `pd` | counts since previous `C` line |
| `rerr` / `perr` | illegal quadrature steps |
| `zp` | pitch Z edge count (Omron) |
| `z` | 1 after USB `zero`, else 0 |
| `psi` | Matek differential pressure, PSI (type A ±1 PSI) |
| `pa` | same pressure in pascals |
| `tc` | sensor temperature, °C |
| `praw` | 14-bit pressure counts |
| `pst` | MS4525 status: 0 good, 2 stale, 3 I²C fail |
| `ias` | indicated airspeed, knots (ISA, q = ½ρV²; 0 if q ≤ 0) |

Commands: existing `help` / `stats` / `invert` / `test`, plus `zero`, `zero roll`, `zero pitch`.

FIX-Gateway plugin `cozy_mgl_airtalk` remains the **sole owner** of the Nano USB port.

---

## 10. FIX and Historian

| Key | Type | Meaning |
|---|---|---|
| `CTRL_ROLL_COUNT` | int | Raw roll counts (600 PPR ×4) |
| `CTRL_PITCH_COUNT` | int | Raw pitch counts (2000 PPR ×4) |
| `CTRL_ROLL_RATE` | float | Counts/s |
| `CTRL_PITCH_RATE` | float | Counts/s |
| `CTRL_ROLL_ERRORS` | int | Illegal quadrature steps |
| `CTRL_PITCH_ERRORS` | int | Illegal quadrature steps |
| `CTRL_PITCH_Z` | int | Omron Z edge count |
| `CTRL_ZERO_VALID` | bool | False until USB `zero` |

Optional later, using the 1.75 ratio on the Pi: `CTRL_ROLL_STICK_DEG`, `CTRL_PITCH_STICK_DEG`. Raw counts remain the source of truth.

Historian: `CTRL_*` on the **10 Hz** table first.

---

## 11. Value for Flight Analysis

```text
pilot / control input
        ↓
CTRL_* encoder position / rate  (pitch 2000 PPR, roll 600 PPR, ratio 1.75)
        ↓
SP-7 Airtalk rates and attitude (MGL_AT_*)
        ↓
Stratux GPS / trajectory
```

Supports control effectiveness, damping, input-to-rate transfer functions, pilot activity, and system identification.

---

## 12. Commissioning Sequence

1. A/B pull-ups: **done** (4.7 kΩ to 3.3 V). Current: **negligible**.
2. Confirm roll 600 PPR (2400 x4 counts/turn) and pitch 2000 PPR (8000 x4 counts/turn); confirm pitch Z once per rev.
3. Five pull-ups: roll A/B, pitch A/B/Z.
4. Firmware v4: `C` lines, `zero`, Airtalk `D` lines still valid.
5. Soak both shafts while Airtalk dump runs.
6. FIX keys + historian 10 Hz; tests with fake `C` lines.
7. Aircraft wiring; confirm `MGL_AT_*` still live.
8. Ground: full stick travel, record counts, `zero` at known neutral; **measure** the 1.75 ratio.
9. Apply calibrated ratio before using stick-degree fields for analysis.

---

## 13. Configuration Summary

| Item | Choice |
|---|---|
| MCU | Nano 33 BLE, 3.3 V |
| Airtalk | D4 RX only, 10 kΩ/18 kΩ, invert=0 |
| Pitch | Omron E6B2-CWZ6C, **2000 PPR**, A/B/Z on D6/D7/D8 |
| Roll | HOK38H5-600N-G5-24, **600 PPR**, A/B on D2/D5 |
| Decoding | x4 |
| Stick-to-encoder ratio | **1.75** preliminary (`θ_encoder = 1.75 × θ_stick`) |
| USB | `D` lines + 100 Hz `C` lines |
| Zero | USB `zero` at known neutral |
| Supply | Nano 5 V; **current negligible** |
| A/B/Z interface | **4.7 kΩ pull-up to 3.3 V** (NPN) |

Open items: measured (not preliminary) mechanical ratio, sign convention, whether pitch Z aligns with stick neutral.

---

## 14. Non-goals

- Transmit on Airtalk.
- Replace Stratux or SP-7 as the attitude source.
- Absolute stick position at power-up (Z is shaft index only unless calibrated).
- Autopilot / servo closed loop from these encoders.
