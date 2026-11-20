# Nano pitch/roll encoder — implementation plan

**Spec (source of truth):** [Cozy_Pitch_Roll_Encoder_Nano_Interface.md](Cozy_Pitch_Roll_Encoder_Nano_Interface.md)  
**Board:** Arduino Nano 33 BLE already on the aircraft Airtalk tap  
**Diagrams:** [nano_airtalk_encoder.drawio](diagrams/nano_airtalk_encoder.drawio)  
**Airtalk:** [MGL_Airtalk_to_Pi_Data_Collector_Interface_v2.md](MGL_Airtalk_to_Pi_Data_Collector_Interface_v2.md)

Build order for mixed encoders on the existing Nano (one USB device: Airtalk + controls). Does **not** change the receive-only Airtalk tap.

| Axis | Encoder | PPR |
|---|---|---:|
| Pitch | Omron E6B2-CWZ6C | **2000** |
| Roll | HOK38H5-600N-G5-24 | **600** |

Preliminary stick-to-encoder ratio **1.75** (`θ_encoder = 1.75 × θ_stick`). Supply current **negligible**.

---

## 1. Constraints from the live Airtalk tap

| Fact | Consequence |
|------|-------------|
| 3.3 V I/O, not 5 V tolerant | 4.7 kΩ pull-up to **3.3 V** on every encoder signal. |
| D4 is Airtalk RX | Do not move it. |
| D3 is bench test TX, high-Z in flight | Do **not** put an encoder on D3. |
| All GPIOs can interrupt | D2/D5 roll, D6/D7 pitch, D8 pitch Z. |
| Airtalk invert=0 hardware UART | Do not enable encoder ISRs if `invert=1`. |

---

## 2. Pin map

| Function | Pin | Lead |
|----------|-----|------|
| Airtalk RX | D4 | as-built |
| Bench test TX | D3 | INPUT in flight |
| Roll A | D2 | HOK WHITE |
| Roll B | D5 | HOK GREEN |
| Pitch A | D6 | Omron BLACK |
| Pitch B | D7 | Omron WHITE |
| Pitch Z | D8 | Omron ORANGE |
| Encoder VCC | Nano **5V** | HOK RED, Omron BROWN |
| Encoder 0V | Nano **GND** | HOK BLACK, Omron BLUE |
| Pull-ups | 3.3 V via 4.7 kΩ | A, B, and pitch Z |

---

## 3. Electrical

Both encoders: NPN OC, **4.7 kΩ to 3.3 V**. Current **negligible** — USB 5 V is fine. No 12–24 V into this Nano.

x4 check: roll **2400** counts/turn (600 PPR), pitch **8000** counts/turn (2000 PPR), pitch Z once per rev.

---

## 4. Firmware (`hardware/nano_airtalk_monitor`)

Keep Airtalk `D` lines. Add x4 ISRs on D2/D5 and D6/D7, Z edge count on D8.

```text
C t=<us> roll=<n> pitch=<n> rd=<n> pd=<n> rerr=<n> perr=<n> zp=<n> z=<0|1> psi=<f> pa=<f> tc=<f> praw=<n> pst=<n> ias=<f>
```

Commands: `zero` / `zero roll` / `zero pitch`. Do not zero pitch from Z. Banner `v5`. Matek ASPD-4525 on A4/A5 (I²C 0x28) is polled at 50 Hz and cached onto the 100 Hz `C` line.

---

## 5. Pi / FIX / Historian / web

USB owner stays `cozy_mgl_airtalk`.

FIX: `CTRL_ROLL_COUNT`, `CTRL_PITCH_COUNT`, rates, errors, `CTRL_PITCH_Z`, `CTRL_ZERO_VALID`. Stick degrees later on the Pi using PPR and ratio 1.75. Historian 10 Hz first.

---

## 6. Delivery phases

### Phase 0 — electrical proof

- NPN + 4.7 kΩ to 3.3 V. **Done.**
- Supply current. **Negligible — closed.**
- Confirm 600 / 2000 PPR and pitch Z. Still do on the bench.

### Phase 1 — firmware on the bench Nano

- ISRs + `C` lines + `zero`; Airtalk `D` lines still work.
- Soak while spinning both shafts.

### Phase 2 — FIX + historian

- Parser + keys + 10 Hz columns; fake `C` line tests.

### Phase 3 — aircraft wiring

- Five pull-ups; confirm `MGL_AT_*` still live.
- Ground travel; `zero` at neutral; **measure** ratio 1.75.

### Phase 4 — calibration

- Replace preliminary 1.75 with measured stick-to-encoder ratio.
- Optional faster control table.

---

## 7. Tests

| Test | Pass |
|------|------|
| Roll x4 | One shaft turn ≈ **2400** counts (600 PPR) |
| Pitch x4 | One shaft turn ≈ **8000** counts (2000 PPR) |
| Pitch Z | One pulse per encoder rev |
| Direction | Reverse rotation reverses count |
| Zero | `zero` → counts 0, `z=1` (Z does not zero) |
| Airtalk coexistence | Valid `0x82…0x83` frames while shafts turn |
| Invert | `invert=1` does not run encoder ISRs |

---

## 8. Open items

- Output stage — **done.**
- Supply current — **negligible, closed.**
- Confirm PPR/Z on the bench (spec values: 600 / 2000).
- **Measure** mechanical ratio (preliminary 1.75).
- Sign convention after first ground move.

---

## 9. Non-goals

- Driving Airtalk, replacing SP-7/Stratux attitude, absolute stick at power-up, servo closed loop.
