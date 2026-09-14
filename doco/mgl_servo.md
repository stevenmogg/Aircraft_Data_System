# MGL servo emulator (Stage 1)

Virtual MGL **bank** and **pitch** autopilot servos on SocketCAN. The Pi does not drive an actuator. The XTreme is meant to see valid servos so steering commands can be logged.

This is **Plan B**: a separate FIX plugin from RDAC CAN ingest. See [Pi_MGL_Servo_Emulator_Specification_and_Test_Plan.md](Pi_MGL_Servo_Emulator_Specification_and_Test_Plan.md) (protocol, **§4.16 XTreme UI**, T13/T14 capture).

## What Stage 1 does

- Listens for host Identify (`0x010`) and Set Position (`0x011`)
- Runs the identify / echo / timeout state machine
- Publishes `MGL_SRV_*` (XTreme **commands** vs emulator **replies** are separate keys)
- Computes command rate, age, circular position error, timeout counts
- **Does not transmit** unless `allow_tx` and `tx_armed` are both true

RDAC logging stays in `cozy_mgl_can` (`receive_only: true`).

## Config

| Item | Path |
|------|------|
| Plugin | `fix_gateway_plugins/cozy_mgl_servo` |
| Connection | `config/fixgw/connections/mgl_servo.yaml` |
| FIX keys | `config/fixgw/database/mgl_servo.yaml` |
| Prefs | `MGL_SERVO: true` |

Aircraft defaults: plugin **on**, TX **off**.

## XTreme Identify (operating manual §4.16)

On this EFIS, **IDENTIFY BANK SERVO** / **IDENTIFY PITCH SERVO**:

- Bank/pitch servo must be selected as installed
- Autopilot not engaged, no flight active
- **Only one servo connected**
- After a few seconds: success, or **no data has been received** (check power and wiring)

The same chapter sets **limits** from a live **0..4095** current position while you move the stick, and talks about **serial** / **COM Extender** ports. That matters: this XTreme may be scoring identify on RS232 even though it also puts identify/position on CAN. Limit setup will not work with a frozen echo of target `0` (no servo encoder).

Bank/pitch torque, magnitude, heading control, VSI/ASI limits in that menu are later calibration (T16+), not identify.

## Autopilot install page

`/debug/mgl/autopilot` (MGL → **AutoPilot**) walks one axis at a time:

1. Choose Bank/Roll or Pitch
2. Preflight, then **Enable CAN TX** (drops listen-only)
3. Identify — Pi arms that virgin servo; run IDENTIFY BANK/PITCH on the XTreme
4. Limits — slider sets the reported 0–4095 current position (no encoder on the Pi); capture left/right or down/up locally, and copy the same number on the XTreme menu
5. Finish / Exit — disarms TX

Runtime state is `data/mgl_servo_control.json`. The FIX plugin polls it; no yaml restart is required. Aircraft default remains TX off.

## Passive capture (T13) — done 2026-09-13

`can0` must exist (MCP2515 Stage 0). Leave TX off. Live Pi is often **LISTEN-ONLY** for T13.

XTreme V1 (VH-COZ) on the wire:

- `0x010` DLC **8** `AA 55 01 FE` + pad (bank = servo **1**)
- `0x011` DLC **8** ~17 Hz to **both** servo 1 and 2, options `0x40`, target 0

Published protocol is DLC 4 for those host frames. The library accepts DLC 4–8.

## Arming for a real identify (T14)

Stationary aircraft. No physical MGL servo on the bus. No S-TEC hooked to this module. One virgin servo at a time. Take `can0` **out of listen-only**.

```yaml
allow_tx: true
tx_armed: true
reply_dlc: 5
servos:
  roll:
    identify_armed: true
  pitch:
    identify_armed: false
```

Restart `fixgateway`. Run **IDENTIFY BANK SERVO**. Then set `tx_armed: false` before pitch.

**T14 not passed (2026-09-13).** Pi accepted servo 1 and sent `0x101` with zero bus TX errors. XTreme still reported no data received:

| Attempt | Reply | Result |
|---|---|---|
| T14a | DLC 5, first frame +553 ms | fail |
| T14b | DLC 8, +1.6 ms | fail |
| T14c | DLC 5, +1.7 ms `00 00 00 58 00` | fail |

After `0x010` the XTreme pauses `0x011` for ~550 ms in every run. If TX throws, the plugin disarms `tx_armed` itself.

## Stage 1 tests

`web/tests/test_mgl_servo.py` covers spec T0–T5, T7, T8, T11 (no hardware).

```bash
PYTHONPATH=. python3 -c "import web.tests.test_mgl_servo as t
[getattr(t,n)() for n in dir(t) if n.startswith('test_')]"
```

## FIX keys (selected)

| Key | Meaning |
|-----|---------|
| `MGL_SRV_ALLOW_TX` / `MGL_SRV_TX_ARMED` | Interlocks |
| `MGL_SRV_ROLL_TGT` / `_CUR` | XTreme target vs echo current |
| `MGL_SRV_ROLL_ERR` | Circular 12-bit error |
| `MGL_SRV_ROLL_HZ` / `_AGE` / `_TMO` | Rate / age / timeouts |
| `MGL_SRV_ROLL_RPLY` | Replies actually sent |

Pitch uses `MGL_SRV_PITCH_*`.
