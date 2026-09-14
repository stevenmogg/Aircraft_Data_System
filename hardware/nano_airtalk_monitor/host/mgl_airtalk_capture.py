#!/usr/bin/env python3
"""Read the Nano Airtalk monitor over USB. Phase 1: banner, hex dump, optional D3→D4 test."""

from __future__ import annotations

import argparse
import glob
import sys
import time

STX = 0x82
ETX = 0x83
CS_INIT = 0xA5

EXPECTED_TEST = bytes([0x82, 0xE4, 0x03, 0x32, 0x12, 0x34, 0xA5 ^ 0xE4 ^ 0x03 ^ 0x32 ^ 0x12 ^ 0x34, 0x83])


def xor_cs(body: bytes) -> int:
    cs = CS_INIT
    for b in body:
        cs ^= b
    return cs


def find_ports() -> list[str]:
    keys = (
        "/dev/cu.usbmodem*",
        "/dev/cu.usbserial*",
        "/dev/cu.wchusbserial*",
        "/dev/cu.wch*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/ttyACM*",
        "/dev/serial/by-id/usb-Arduino_Nano_33_BLE*",
    )
    found: list[str] = []
    for k in keys:
        found.extend(sorted(glob.glob(k)))
    return found


def parse_hex_field(line: str) -> bytes:
    if "hex=" not in line:
        return b""
    part = line.split("hex=", 1)[1].strip()
    try:
        return bytes(int(x, 16) for x in part.split() if x)
    except ValueError:
        return b""


def frames_in(buf: bytearray) -> list[tuple[bytes, str]]:
    """Return complete STX..ETX frames and a status (OK/BADLEN/BADCS)."""
    out: list[tuple[bytes, str]] = []
    while True:
        i = buf.find(bytes([STX]))
        if i < 0:
            buf.clear()
            return out
        if i:
            del buf[:i]
        if len(buf) < 5:
            return out
        # STX DST LEN TYPE ... CS ETX   LEN = type + data count
        ln = buf[2]
        total = 1 + 1 + 1 + ln + 1 + 1  # stx dst len payload cs etx
        if len(buf) < total:
            return out
        frame = bytes(buf[:total])
        del buf[:total]
        if frame[-1] != ETX:
            out.append((frame, "BADEND"))
            continue
        body = frame[1:-2]
        if xor_cs(body) != frame[-2]:
            out.append((frame, "BADCS"))
            continue
        out.append((frame, "OK"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", help="serial device (auto-detect if omitted)")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("--test", action="store_true", help="send 'test' and look for the self-test frame")
    ap.add_argument("--seconds", type=float, default=8.0, help="how long to listen after connect")
    args = ap.parse_args()

    try:
        import serial  # type: ignore
    except ImportError:
        print("pyserial is required: pip install pyserial", file=sys.stderr)
        return 2

    port = args.port
    if not port:
        ports = find_ports()
        if not ports:
            print("No Nano serial port found. Plug the Nano in (data USB cable).", file=sys.stderr)
            return 1
        port = ports[0]
        if len(ports) > 1:
            print(f"# using {port} (also saw {ports[1:]})", file=sys.stderr)

    ser = serial.Serial(port, args.baud, timeout=0.2)
    time.sleep(2.0)  # Nano reset on open
    ser.reset_input_buffer()
    ser.write(b"help\n")
    ser.flush()

    buf = bytearray()
    saw_banner = False
    saw_test_ok = False
    deadline = time.monotonic() + args.seconds
    sent_test = False

    if args.test:
        time.sleep(0.3)
        ser.write(b"test\n")
        ser.flush()
        sent_test = True

    while time.monotonic() < deadline:
        raw = ser.read(256)
        if not raw:
            continue
        text = raw.decode("ascii", errors="replace")
        sys.stdout.write(text)
        sys.stdout.flush()
        for line in text.splitlines():
            if line.startswith("# nano_airtalk_monitor"):
                saw_banner = True
            if line.startswith("D "):
                buf.extend(parse_hex_field(line))
                for frame, st in frames_in(buf):
                    hx = " ".join(f"{b:02X}" for b in frame)
                    print(f"# frame CHECK={st} {hx}")
                    if st == "OK":
                        dest, ln, typ = frame[1], frame[2], frame[3]
                        data = frame[4:-2]
                        print(
                            f"# DST={dest:02X} LEN={ln:02X} TYPE={typ:02X} "
                            f"DATA={' '.join(f'{b:02X}' for b in data)} CHECK={st}"
                        )
                    if st == "OK" and frame == EXPECTED_TEST:
                        saw_test_ok = True

    ser.close()
    if not saw_banner:
        print("# FAIL: no banner (wrong port, baud, or board not running this firmware)", file=sys.stderr)
        return 1
    if args.test and sent_test and not saw_test_ok:
        print("# FAIL: self-test frame not seen. Jumper D3 to D4 and retry.", file=sys.stderr)
        return 1
    if args.test and saw_test_ok:
        print("# PASS: self-test frame CHECK=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
