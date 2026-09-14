# Pico 2 W — USB serial bridge for MGL SP-7 firmware

Appear on the Mac as a USB serial (CDC) port and bridge bytes to a UART wired to the SP-7 RS-232 pins **through a level shifter**.

## Important limits

1. **RS-232 levels** — SP-7 DB9 pins 3/4 are real RS-232, not 3.3 V TTL. The Pico UART is **3.3 V only**. You **must** use a **MAX3232** (or equivalent) between Pico and SP-7. Direct wiring can damage the Pico and/or SP-7.
2. **Baud** — ARMPROG’s serial default is **38400 8N1**. The SP-7’s normal (non-bootloader) RS-232 data rate is documented as **57600**. The Arduino bridge defaults to **38400** for firmware load; change it on the diagnostic page if needed.
3. **ARMPROG** — MGL’s updater is a **Windows** app. On a Mac use Windows in a VM/Parallels (or a Windows PC) and select the Pico’s COM/tty port. The Pico only provides the serial pipe.

## Wiring

```text
Mac USB ── Pico 2 W ── UART ── MAX3232 ── SP-7 DB9
```

| Pico 2 W | MAX3232 (3.3 V logic side) | SP-7 (RS-232 side) |
|----------|----------------------------|--------------------|
| GND | GND | Pin 1 or 2 (GND) |
| 3V3 | VCC | — |
| GP0 (UART0 TX) | T1IN | — |
| GP1 (UART0 RX) | R1OUT | — |
| — | T1OUT | Pin 3 RX (SP-7 receive) |
| — | R1IN | Pin 4 TX (SP-7 transmit) |

SP-7 still needs **+12 V on pins 6/7** and ground for programming (per MGL manual). Do not power the SP-7 from the Pico 3V3 rail.

Cross-check: **Pico TX → SP-7 RX**, **SP-7 TX → Pico RX** (after the MAX3232).

Default Arduino bridge baud: **38400 8N1** (ARMPROG). USB CDC ignores host baud; the SP-7 sees whatever UART baud is set on the Pico.

## Diagnostic Wi-Fi page (Arduino / Pico 2 W)

The Arduino firmware raises a local access point and serves a live hex dump of USB↔UART traffic.

| | |
|--|--|
| SSID | `SP7-Bridge` |
| Password | `sp7bridge` |
| URL | http://192.168.4.1 |

Green lines are host → SP-7; blue lines are SP-7 → host. The page can also change UART baud. Serial bridging stays first; the web UI is sniff-only.

## Flash MicroPython (recommended quick path)

1. Hold **BOOTSEL**, plug Pico into Mac, release — mounts as `RPI-RP2` (Pico 2 may show as RP2350 mass storage).
2. Download a **Pico 2 / RP2350** MicroPython `.uf2` from [micropython.org](https://micropython.org/download/).
3. Copy the UF2 onto the board; it reboots.
4. Copy [`micropython/main.py`](micropython/main.py) to the board as `main.py` (Thonny, `mpremote`, etc.).

```bash
# example with mpremote (pip install mpremote)
mpremote connect /dev/cu.usbmodem* cp micropython/main.py :main.py
mpremote reset
```

5. Unplug/replug. On the Mac you should see something like `/dev/cu.usbmodem*`.

## Arduino alternative

[`arduino/sp7_usb_uart_bridge.ino`](arduino/sp7_usb_uart_bridge.ino) — use **Earle Philhower Arduino-Pico** board package, board **Raspberry Pi Pico 2** / **Pico 2 W**, upload over USB.

## Using with ARMPROG (Windows)

1. Pico plugged in; note COM port (Device Manager).
2. SP-7 powered; MAX3232 wired as above.
3. Run ARMPROG → select that COM port → power-cycle SP-7 when prompted → Program.

## Optional baud override

MicroPython: edit `BAUD` in `main.py` (default `57600`).  
Arduino: default `38400`; change on the diagnostic page or in the `.ino`.

## LED

On-board LED blinks slowly while the bridge is idle/running (heartbeat). It is not a traffic indicator.
