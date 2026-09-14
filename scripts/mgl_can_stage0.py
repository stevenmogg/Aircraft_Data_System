                                                                                                                                                            #!/usr/bin/env python3
"""Stage 0 / 1A — prove SocketCAN can0 and classify MGL CAN identifiers.

Usage on the Pi (FIX venv has python-can):

  /cozy-data-system/venv/bin/python scripts/mgl_can_stage0.py probe
  /cozy-data-system/venv/bin/python scripts/mgl_can_stage0.py up
  /cozy-data-system/venv/bin/python scripts/mgl_can_stage0.py capture --seconds 30 --out /tmp/mgl_can.log

Does not transmit. Bring-up uses listen-only when `ip` supports it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CHANNEL = os.environ.get("COZY_CAN_CHANNEL", "can0")
BITRATE = int(os.environ.get("COZY_CAN_BITRATE", "250000"))

DEVICE_FAMILIES = (
    ((1, 15), "host/EFIS"),
    ((32, 35), "RDAC"),
    ((36, 39), "compass"),
    ((40, 43), "AHRS/SP-7"),
    ((44, 45), "transponder"),
    ((48, 51), "SP10"),
    ((52, 59), "ECB"),
    ((60, 63), "TouchPad"),
    ((64, 67), "EFIS extender"),
    ((68, 69), "external AP"),
)


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def _sudo(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    if os.geteuid() == 0:
        return _run(cmd, timeout=timeout)
    return _run(["sudo", "-n"] + cmd, timeout=timeout)


def device_family(addr: int) -> str:
    for (lo, hi), name in DEVICE_FAMILIES:
        if lo <= addr <= hi:
            return name
    return "unknown"


def parse_id(can_id: int) -> tuple[int, int]:
    return (can_id >> 4) & 0x7F, can_id & 0x0F


def cmd_probe(_: argparse.Namespace) -> int:
    print(f"=== link {CHANNEL} ===")
    rc, out = _run(["ip", "-details", "link", "show", CHANNEL])
    print(out.strip() or f"(no {CHANNEL})")
    if rc != 0:
        print("FAIL: SocketCAN interface is missing.")
        print("Kernel overlay mcp2515-can0 is not bound. See doco/mgl_can_install.md")
        rc2, dmesg = _run(["dmesg"])
        if rc2 == 0:
            hits = [
                ln
                for ln in dmesg.splitlines()
                if "mcp251" in ln.lower() or "can0" in ln.lower()
            ]
            for ln in hits[-12:]:
                print("  dmesg:", ln)
        return 2

    print("=== python-can ===")
    try:
        import can  # noqa: F401

        print("python-can import OK")
    except ImportError as e:
        print("FAIL: python-can not importable:", e)
        return 3
    print("PASS: interface exists")
    return 0


def cmd_up(_: argparse.Namespace) -> int:
    rc, out = _run(["ip", "link", "show", CHANNEL])
    if rc != 0:
        print(out.strip() or f"no {CHANNEL}")
        return 2

    # Down first so type can be (re)applied.
    _sudo(["ip", "link", "set", CHANNEL, "down"])
    rc, out = _sudo(
        [
            "ip",
            "link",
            "set",
            CHANNEL,
            "up",
            "type",
            "can",
            "bitrate",
            str(BITRATE),
            "listen-only",
            "on",
        ]
    )
    if rc != 0:
        print("listen-only bring-up failed, retrying without listen-only:")
        print(out.strip())
        rc, out = _sudo(
            [
                "ip",
                "link",
                "set",
                CHANNEL,
                "up",
                "type",
                "can",
                "bitrate",
                str(BITRATE),
            ]
        )
        if rc != 0:
            print(out.strip())
            return 4
        print("WARN: interface is UP but not listen-only")
    else:
        print(f"UP {CHANNEL} bitrate={BITRATE} listen-only=on")

    rc, out = _run(["ip", "-details", "-s", "link", "show", CHANNEL])
    print(out)
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        import can
    except ImportError as e:
        print("FAIL: python-can not importable:", e)
        return 3

    seconds = float(args.seconds)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        bus = can.Bus(channel=CHANNEL, interface="socketcan", receive_own_messages=False)
    except Exception as e:
        print("FAIL: python-can open:", e)
        return 5

    counts: Counter[int] = Counter()
    last: dict[int, Any] = {}
    first_ts: dict[int, float] = {}
    last_ts: dict[int, float] = {}
    extended = 0
    errors = 0
    t0 = time.monotonic()
    print(f"capturing {CHANNEL} for {seconds:.0f}s -> {out_path}")
    try:
        with out_path.open("w", encoding="utf-8") as fh:
            while time.monotonic() - t0 < seconds:
                msg = bus.recv(timeout=0.25)
                if msg is None:
                    continue
                now = time.monotonic()
                ts = getattr(msg, "timestamp", None) or time.time()
                if msg.is_error_frame:
                    errors += 1
                    continue
                if msg.is_extended_id:
                    extended += 1
                can_id = int(msg.arbitration_id)
                counts[can_id] += 1
                last[can_id] = bytes(msg.data)
                first_ts.setdefault(can_id, now)
                last_ts[can_id] = now
                payload = "".join(f"{b:02X}" for b in msg.data)
                # candump -L : (timestamp) can0 123#DEADBEEF
                fh.write(
                    f"({ts:.6f}) {CHANNEL} {can_id:03X}#{payload}\n"
                )
    finally:
        bus.shutdown()

    elapsed = max(time.monotonic() - t0, 1e-6)
    total = sum(counts.values())
    print(f"frames={total} unique_ids={len(counts)} extended={extended} errors={errors} elapsed_s={elapsed:.1f}")
    if total == 0:
        print("FAIL: no frames received")
        return 6

    print()
    print(
        f"{'CAN_ID':>8} {'addr':>5} {'msg':>4} {'family':<14} {'n':>6} {'Hz':>7} {'dlc':>4} payload"
    )
    for can_id, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        addr, mid = parse_id(can_id)
        fam = device_family(addr)
        span = max(last_ts[can_id] - first_ts[can_id], 1e-6)
        hz = (n - 1) / span if n > 1 else n / elapsed
        payload = last[can_id].hex(" ").upper()
        print(
            f"0x{can_id:03X}   {addr:5d} {mid:4d} {fam:<14} {n:6d} {hz:7.2f} {len(last[can_id]):4d} {payload}"
        )

    families: dict[str, int] = defaultdict(int)
    for can_id, n in counts.items():
        families[device_family(parse_id(can_id)[0])] += n
    print()
    print("by family:")
    for fam, n in sorted(families.items(), key=lambda kv: -kv[1]):
        print(f"  {fam}: {n}")

    print()
    print(f"PASS: wrote {out_path} ({total} frames)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="check can0 exists and python-can imports")
    sub.add_parser("up", help="bring can0 UP at 250 kbit/s listen-only")
    cap = sub.add_parser("capture", help="receive frames, classify IDs, write candump -L log")
    cap.add_argument("--seconds", type=float, default=30.0)
    cap.add_argument(
        "--out",
        default="tests/fixtures/mgl_can/mgl_can_stage0.log",
    )
    args = p.parse_args()
    if args.cmd == "probe":
        return cmd_probe(args)
    if args.cmd == "up":
        return cmd_up(args)
    if args.cmd == "capture":
        return cmd_capture(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
