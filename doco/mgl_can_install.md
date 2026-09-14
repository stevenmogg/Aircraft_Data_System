# MGL CAN / MCP2515 — SocketCAN `can0`

Passive listen of the aircraft MGL CAN bus through an MCP2515 on SPI, exposed as SocketCAN `can0` at **250 kbit/s**.

The receive-only plugin `cozy_mgl_can` is wired (`MGL_CAN: true`) and writes `MGL_RDAC_*` keys defined in `config/fixgw/database/mgl_rdac.yaml`. Thermocouples are stored as compensated **°F** (wire °C + RDAC cold junction, then converted).

The autopilot **servo emulator** is a separate plugin (`MGL_SERVO`). It also needs `can0`. TX stays off until explicitly armed. See [mgl_servo.md](mgl_servo.md).

## Status (live Pi)

**`can0` is up** at 250 kbit/s. Overlay in `/boot/firmware/config.txt` (and the Stratux image `config.txt`):

```text
dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25,spimaxfrequency=500000
```

`spimaxfrequency=500000` is required on this harness; the default SPI clock fails probe (`MCP251x didn't enter in conf mode after reset`).

`cozy-can0.service` runs `setup_can0.sh --up` (listen-only) when `/sys/class/net/can0` exists. Autopilot TX uses `--up-tx` separately.

## Wiring (SPI0 CE0 = `mcp2515-can0`)

| MCP2515 | Function | Wire colour | Pi connection | Physical pin |
|---------|----------|-------------|---------------|--------------|
| VCC | +5 V | Red | 5 V | 2 or 4 |
| GND | Ground | Black | GND | 6 |
| CS | SPI Chip Select | Blue | CS0 / GPIO8 | 24 |
| SO / MISO | MCP2515 → Pi | Black | MISO / GPIO9 | 21 |
| SI / MOSI | Pi → MCP2515 | Green | MOSI / GPIO10 | 19 |
| SCK | SPI Clock | Yellow | SCLK / GPIO11 | 23 |
| INT | Interrupt | White | GPIO25 | 22 |

GND and SO are both black on this harness — do not mix them up. Power is **5 V**, not 3.3 V.

Pins already taken on this Pi (do not reuse for INT/CS):

| GPIO | Use |
|------|-----|
| 2 / 3 | AHRS I²C |
| 4 | `sc16is752-i2c` INT |
| 14 / 15 | Matek GPS UART |

Crystal: most cheap MCP2515+TJA1050 boards are **8 MHz**; some HATs are **16 MHz**. Wrong crystal does not cause this probe error; it would only skew bitrate after the chip answers SPI.

## What to check on the bench

1. Module powered from Pi **5 V** (red) and common ground (black to pin 6).
2. SO/MISO (black to pin 21) not swapped with SI/MOSI (green to pin 19), and not mixed with GND (also black).
3. CS on pin 24 (blue, CE0) for `mcp2515-can0`.
4. INT on pin 22 (white, GPIO25).
5. After a wiring fix, **do not transmit**. Bring the bus up listen-only.

MGL Extreme + RDAC staying up while the Pi is attached is required before calling Stage 1 done.

## Scripts

```bash
# status / runtime overlay probe (on Pi)
sudo /cozy-data-system/scripts/setup_can0.sh --status
sudo /cozy-data-system/scripts/setup_can0.sh --probe-overlay

# only after dmesg shows "MCP2515 successfully initialized"
sudo /cozy-data-system/scripts/setup_can0.sh --install   # config.txt; reboot
sudo /cozy-data-system/scripts/setup_can0.sh --up        # 250 kbit/s listen-only

# python-can capture + ID classification (candump -L format)
/cozy-data-system/venv/bin/python /cozy-data-system/scripts/mgl_can_stage0.py probe
/cozy-data-system/venv/bin/python /cozy-data-system/scripts/mgl_can_stage0.py up
/cozy-data-system/venv/bin/python /cozy-data-system/scripts/mgl_can_stage0.py capture \
  --seconds 30 --out /tmp/mgl_can_stage0.log
```

Copy the log into `tests/fixtures/mgl_can/` on the Mac as the Stage 4 replay fixture.

Expected ID split after a good capture (`addr = id>>4`, `msg = id&0x0F`):

- RDAC 32–35 (this aircraft has RDAC)
- Host / Extreme 1–15
- AHRS 40–43 / compass 36–39 only if those IDs actually appear

## Overlay snippet

`config/pi5/mcp2515.config.txt.snippet` matches the live / image `config.txt` block. New Stratux images get this overlay from `image_build/stage2/10-stratux/files/config.txt`.
