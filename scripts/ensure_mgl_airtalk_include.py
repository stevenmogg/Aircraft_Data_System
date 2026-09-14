#!/usr/bin/env python3
"""Insert Cozy connection includes into FIX-Gateway default.yaml."""

from pathlib import Path
import sys

EXTRAS = (
    "MGL_AIRTALK_CONFIG",
    "MGL_CAN_CONFIG",
    "MGL_NMEA_CONFIG",
    "MGL_SERVO_CONFIG",
)
ANCHOR = "  - STRATUX_CONFIG\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ensure_mgl_airtalk_include.py /path/to/default.yaml", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    text = path.read_text()
    if ANCHOR not in text:
        print(f"STRATUX_CONFIG include not found in {path}", file=sys.stderr)
        return 1
    missing = [name for name in EXTRAS if f"- {name}" not in text]
    if not missing:
        print(f"already present: {path}")
        return 0
    block = ANCHOR + "".join(f"  - {name}\n" for name in missing)
    path.write_text(text.replace(ANCHOR, block, 1))
    print(f"inserted {', '.join(missing)} in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
