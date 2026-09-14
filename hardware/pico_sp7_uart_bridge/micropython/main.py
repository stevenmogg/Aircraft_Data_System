"""USB CDC <-> UART0 bridge for MGL SP-7 firmware updates.

Pico 2 W (RP2350): appears as a USB serial port on the Mac.
Wire UART0 through a MAX3232 to SP-7 RS-232 (see README).

Default baud 57600 (MGL SP-7 RS-232).
"""

from machine import UART, Pin
import sys
import time
import uselect
import micropython

# ARMPROG sends binary. Default Ctrl-C (0x03) would kill this script.
micropython.kbd_intr(-1)

BAUD = 57600
UART_TX = 0  # GP0
UART_RX = 1  # GP1

uart = UART(
    0,
    baudrate=BAUD,
    bits=8,
    parity=None,
    stop=1,
    tx=Pin(UART_TX),
    rx=Pin(UART_RX),
    timeout=0,
)

try:
    led = Pin("LED", Pin.OUT)
except (ValueError, TypeError):
    led = Pin(25, Pin.OUT)

usb_in = sys.stdin.buffer
usb_out = sys.stdout.buffer

poll = uselect.poll()
poll.register(sys.stdin, uselect.POLLIN)

led_t = time.ticks_ms()
led_on = False

while True:
    # USB -> UART
    if poll.poll(0):
        chunk = usb_in.read(64)
        if chunk:
            uart.write(chunk)

    # UART -> USB
    n = uart.any()
    if n:
        data = uart.read(n)
        if data:
            usb_out.write(data)
            try:
                usb_out.flush()
            except Exception:
                pass

    now = time.ticks_ms()
    if time.ticks_diff(now, led_t) >= 500:
        led_t = now
        led_on = not led_on
        led.value(1 if led_on else 0)
