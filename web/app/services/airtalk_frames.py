"""MGL Airtalk frame parser (STX/LEN/XOR/ETX) and MGL_AT_* FIX mapping."""

from __future__ import annotations

from dataclasses import dataclass

STX = 0x82
ETX = 0x83
CS_INIT = 0xA5

DEST_LABELS = {
    0xE4: "SP-2 compass",
    0xE6: "SP-7 AHRS",
    0xFF: "broadcast",
}


def xor_cs(body: bytes) -> int:
    cs = CS_INIT
    for b in body:
        cs ^= b
    return cs


def dest_label(dest: int) -> str:
    return DEST_LABELS.get(dest, "unknown")


def payload_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _i16(lo: int, hi: int) -> int:
    v = lo | (hi << 8)
    return v - 0x10000 if v >= 0x8000 else v


def _u16(lo: int, hi: int) -> int:
    return lo | (hi << 8)


def _i8(b: int) -> int:
    return b - 256 if b >= 128 else b


def _fps_le(lo: int, hi: int) -> float:
    """SP-4 fps: LSB fractional, MSB signed integer (little-endian on the wire)."""
    integ = hi if hi < 128 else hi - 256
    return integ + lo / 256.0


def _misc_text(b: int) -> str:
    mode = "gyro" if b & 1 else "accel"
    bits = [mode]
    if b & 2:
        bits.append("overrange")
    if b & 4:
        bits.append("at-temp")
    return f"0x{b:02X} ({', '.join(bits)})"


def decode_fields(dest: int, msg_type: int, data: bytes) -> list[dict]:
    """Provisional field decode from live XTreme comparison + SP-4 OEM type 0x37."""
    out: list[dict] = []
    if dest == 0xFF and msg_type == 0x32 and len(data) >= 2:
        hdg = _u16(data[0], data[1])
        out.append(
            {
                "name": "Magnetic heading",
                "value": hdg,
                "units": "deg",
                "note": "uint16 little-endian, 1 deg",
                    "highlight": True,
            }
        )
        if len(data) >= 3:
            out.append(
                {
                    "name": "Status",
                    "value": data[2],
                    "units": "",
                    "note": f"0x{data[2]:02X}",
                }
            )
        return out

    if dest == 0xFF and msg_type == 0x37 and len(data) >= 16:
        subtype = data[0]
        scale = 10.0 if subtype in (0x04, 0x05) else 1.0
        fmt = {0x00: "Euler", 0x04: "Euler2", 0x05: "Euler10"}.get(
            subtype, f"subtype 0x{subtype:02X}"
        )
        bank = round(_i16(data[1], data[2]) / scale, 1)
        pitch = round(_i16(data[3], data[4]) / scale, 1)
        yaw = round(_i16(data[5], data[6]) / scale, 1)
        out.extend(
            [
                {
                    "name": "Bank",
                    "value": bank,
                    "units": "deg",
                    "note": f"SP-4 {fmt} int16 LE / {scale:g}",
                    "highlight": True,
                },
                {
                    "name": "Pitch",
                    "value": pitch,
                    "units": "deg",
                    "note": f"SP-4 {fmt} int16 LE / {scale:g}",
                    "highlight": True,
                },
                {
                    "name": "Yaw",
                    "value": yaw,
                    "units": "deg",
                    "note": "AHRS yaw, not mag heading (that is FF/32)",
                },
                {
                    "name": "Slip",
                    "value": _i8(data[7]),
                    "units": "",
                    "note": "sint −50…+50",
                },
                {
                    "name": "G",
                    "value": round(_fps_le(data[8], data[9]), 2),
                    "units": "g",
                    "note": "fps little-endian",
                },
                {
                    "name": "MISC",
                    "value": data[10],
                    "units": "",
                    "note": _misc_text(data[10]),
                },
            ]
        )
        if len(data) >= 13:
            out.append(
                {
                    "name": "Gyro heading",
                    "value": _u16(data[11], data[12]),
                    "units": "deg",
                    "note": "SP-4 gyro heading field",
                }
            )
        if len(data) >= 15:
            out.append(
                {
                    "name": "Voltage",
                    "value": round(data[14] * 0.1, 1),
                    "units": "V",
                    "note": "0.1 V steps (unverified on SP-7)",
                }
            )
        if len(data) >= 17:
            out.append(
                {
                    "name": "Turn rate",
                    "value": _i16(data[15], data[16]),
                    "units": "",
                    "note": "raw int16, last two bytes",
                }
            )
        elif len(data) >= 16:
            out.append(
                {
                    "name": "Turn rate",
                    "value": _i8(data[15]),
                    "units": "",
                    "note": "sint",
                }
            )
    return out


# Source-specific FIX keys. STRX_PITCH/STRX_ROLL/STRX_HEAD stay Stratux-owned.
FIX_EULER_KEYS = {
    "Bank": "MGL_AT_ROLL",
    "Pitch": "MGL_AT_PITCH",
    "Yaw": "MGL_AT_YAW",
    "Slip": "MGL_AT_SLIP",
    "G": "MGL_AT_G",
    "MISC": "MGL_AT_MISC",
    "Turn rate": "MGL_AT_TURN",
}


def decode_fix_values(dest: int, msg_type: int, data: bytes) -> dict[str, float]:
    """Map a decoded Airtalk payload onto MGL_AT_* FIX keys.

    Roll is bank as received (positive left on this airframe). Gyro heading
    and voltage are not published — heading comes from FF/32.
    """
    out: dict[str, float] = {}
    for field in decode_fields(dest, msg_type, data):
        name = field["name"]
        value = field["value"]
        if dest == 0xFF and msg_type == 0x32:
            if name == "Magnetic heading":
                out["MGL_AT_HEAD"] = float(value)
            elif name == "Status":
                out["MGL_AT_HEAD_STATUS"] = float(value)
        elif dest == 0xFF and msg_type == 0x37:
            key = FIX_EULER_KEYS.get(name)
            if key is not None:
                out[key] = float(value)
    return out


def payload_views(data: bytes) -> dict:
    """Candidate number views so a payload can be compared to the XTreme."""
    i16le: list[int] = []
    i16be: list[int] = []
    u16le: list[int] = []
    u16be: list[int] = []
    for i in range(0, len(data) - 1, 2):
        i16le.append(_i16(data[i], data[i + 1]))
        u16le.append(_u16(data[i], data[i + 1]))
        i16be.append(_i16(data[i + 1], data[i]))
        u16be.append(_u16(data[i + 1], data[i]))
    return {
        "hex": payload_hex(data),
        "bytes": list(data),
        "i16le": i16le,
        "i16be": i16be,
        "u16le": u16le,
        "u16be": u16be,
    }


@dataclass(frozen=True)
class AirtalkFrame:
    dest: int
    length: int
    msg_type: int
    data: bytes
    checksum: int
    raw: bytes
    status: str  # OK / BADCS / BADEND / BADLEN

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def key(self) -> str:
        return f"{self.dest:02X}:{self.msg_type:02X}"


class FrameAssembler:
    """Feed raw Airtalk bytes; pull complete STX..ETX frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[AirtalkFrame]:
        if chunk:
            self._buf.extend(chunk)
        return self._drain()

    def _drain(self) -> list[AirtalkFrame]:
        out: list[AirtalkFrame] = []
        while True:
            i = self._buf.find(bytes([STX]))
            if i < 0:
                self._buf.clear()
                return out
            if i:
                del self._buf[:i]
            if len(self._buf) < 5:
                return out
            ln = self._buf[2]
            if ln > 48:
                del self._buf[0]
                continue
            total = 1 + 1 + 1 + ln + 1 + 1
            if len(self._buf) < total:
                return out
            raw = bytes(self._buf[:total])
            del self._buf[:total]
            out.append(parse_frame(raw))
        return out


def parse_frame(raw: bytes) -> AirtalkFrame:
    if len(raw) < 5 or raw[0] != STX:
        return AirtalkFrame(0, 0, 0, b"", 0, raw, "BADLEN")
    dest = raw[1]
    length = raw[2]
    total = 1 + 1 + 1 + length + 1 + 1
    if len(raw) != total:
        return AirtalkFrame(dest, length, 0, b"", 0, raw, "BADLEN")
    if raw[-1] != ETX:
        return AirtalkFrame(dest, length, raw[3] if length else 0, raw[4:-2], raw[-2], raw, "BADEND")
    msg_type = raw[3] if length else 0
    data = raw[4:-2]
    cs = raw[-2]
    status = "OK" if xor_cs(raw[1:-2]) == cs else "BADCS"
    return AirtalkFrame(dest, length, msg_type, data, cs, raw, status)


def parse_monitor_hex_line(line: str) -> bytes:
    """Bytes from a Nano `D t=… hex=` dump line."""
    if "hex=" not in line:
        return b""
    part = line.split("hex=", 1)[1].strip()
    try:
        return bytes(int(x, 16) for x in part.split() if x)
    except ValueError:
        return b""
