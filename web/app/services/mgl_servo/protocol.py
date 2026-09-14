"""MGL autopilot servo CAN frames (host 0x010/0x011, replies 0x101/0x111).

Not SP-10 flap/trim motors. 11-bit IDs, 250 kbit/s.
CAN_ID = (device_address << 4) | message_id
device_address = (servo_number - 1) + 16
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HOST_ADDR = 1
IDENTIFY_ID = (HOST_ADDR << 4) | 0  # 0x010
POSITION_ID = (HOST_ADDR << 4) | 1  # 0x011
SERVO_MSG_POSITION = 1
POS_MOD = 4096
INT12_MIN = -2048
INT12_MAX = 2047
POS_MAX = 4095  # unsigned 12-bit bit pattern
IDENTIFY_MAGIC = (0xAA, 0x55)

# Arduino Aircraft-Control-Trim-Flap-AutoPilot.ino msgID1 footer.
# Voltage byte 0x80 → 17.8 V; torque 0x70. DLC 5, never padded.
ARDUINO_VOLTAGE_BYTE = 0x80
ARDUINO_TORQUE_BYTE = 0x70
ARDUINO_VOLTAGE_V = 5.0 + 0.1 * ARDUINO_VOLTAGE_BYTE
ARDUINO_IDLE_POSITION = 0x71
ARDUINO_REPLY_DLC = 5


def u12_to_s12(raw: int) -> int:
    """12-bit two's complement: 4095 → -1, 2048 → -2048, 0 → 0."""
    v = int(raw) & 0xFFF
    return v - POS_MOD if v >= 2048 else v


def s12_to_u12(value: int) -> int:
    return int(value) & 0xFFF


def clamp_s12(value: int) -> int:
    return max(INT12_MIN, min(INT12_MAX, int(value)))


def stored_to_s12(value: Any) -> int | None:
    """Accept signed counts, or legacy unsigned 12-bit patterns (2048..4095)."""
    if value is None or value == "":
        return None
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw > INT12_MAX:
        return u12_to_s12(raw)
    if raw < INT12_MIN:
        return INT12_MIN
    return raw


def device_address(servo_number: int) -> int:
    return (servo_number - 1) + 16


def reply_id(servo_number: int) -> int:
    return (device_address(servo_number) << 4) | SERVO_MSG_POSITION


def voltage_byte(volts: float) -> int:
    """Vservo = 5.0 + 0.1 * byte → byte for simulated supply."""
    raw = int(round((float(volts) - 5.0) / 0.1))
    return max(0, min(255, raw))


def circular_error(target: int, current: int) -> int:
    """Shortest signed 12-bit step from current toward target."""
    return ((int(target) - int(current) + 2048) % 4096) - 2048


def step_unwrap(unwrap: float, prev_raw: int, new_raw: int) -> float:
    return float(unwrap) + float(circular_error(new_raw, prev_raw))


def parse_id(can_id: int) -> tuple[int, int]:
    return (int(can_id) >> 4) & 0x7F, int(can_id) & 0x0F


def engage_requested(options: int, engage_bit: int = 0) -> bool:
    return bool(int(options) & (1 << int(engage_bit)))


def torque_reset_requested(options: int) -> bool:
    """Provisional: bit 1. Raw options are always preserved."""
    return bool(int(options) & 0x02)


def torque_setting(options: int) -> int:
    return (int(options) >> 4) & 0x0F


def status_byte(*, engaged: bool, slipping: bool = False, voltage_alarm: bool = False) -> int:
    raw = 0
    if engaged:
        raw |= 0x01
    if slipping:
        raw |= 0x02
    if voltage_alarm:
        raw |= 0x04
    return raw


@dataclass(frozen=True)
class IdentifyCommand:
    servo_number: int
    raw: bytes


@dataclass(frozen=True)
class PositionCommand:
    servo_number: int
    options: int
    target: int
    raw: bytes


@dataclass(frozen=True)
class ServoReply:
    can_id: int
    data: bytes


def _host_payload(data: bytes) -> bytes | None:
    """XTreme V1 sends DLC 8 with the published 4 bytes padded. Accept 4..8."""
    raw = bytes(data)
    if len(raw) < 4 or len(raw) > 8:
        return None
    return raw


def decode_identify(can_id: int, data: bytes, *, extended: bool = False) -> IdentifyCommand | None:
    raw = _host_payload(data)
    if extended or int(can_id) != IDENTIFY_ID or raw is None:
        return None
    if raw[0] != IDENTIFY_MAGIC[0] or raw[1] != IDENTIFY_MAGIC[1]:
        return None
    number = int(raw[2])
    if raw[3] != (number ^ 0xFF):
        return None
    if number < 0 or number > 16:
        return None
    return IdentifyCommand(servo_number=number, raw=raw)


def decode_position(can_id: int, data: bytes, *, extended: bool = False) -> PositionCommand | None:
    raw = _host_payload(data)
    if extended or int(can_id) != POSITION_ID or raw is None:
        return None
    number = int(raw[0])
    if number < 1 or number > 16:
        return None
    target = u12_to_s12(int(raw[2]) | (int(raw[3]) << 8))
    return PositionCommand(
        servo_number=number,
        options=int(raw[1]),
        target=target,
        raw=raw,
    )


def encode_identify(servo_number: int) -> bytes:
    n = int(servo_number)
    return bytes([IDENTIFY_MAGIC[0], IDENTIFY_MAGIC[1], n, n ^ 0xFF])


def encode_position(servo_number: int, target: int, options: int = 0) -> bytes:
    t = s12_to_u12(target)
    return bytes([int(servo_number), int(options) & 0xFF, t & 0xFF, (t >> 8) & 0xFF])


def encode_reply(
    servo_number: int,
    *,
    position: int,
    engaged: bool,
    slipping: bool = False,
    voltage_alarm: bool = False,
    voltage_v: float = ARDUINO_VOLTAGE_V,
    torque: int = ARDUINO_TORQUE_BYTE,
    pad_dlc: int = ARDUINO_REPLY_DLC,
) -> ServoReply:
    pos = s12_to_u12(int(position))
    data = bytes(
        [
            status_byte(engaged=engaged, slipping=slipping, voltage_alarm=voltage_alarm),
            pos & 0xFF,
            (pos >> 8) & 0xFF,
            voltage_byte(voltage_v),
            max(0, min(255, int(torque))),
        ]
    )
    want = max(5, min(8, int(pad_dlc)))
    if want > len(data):
        data = data + bytes(want - len(data))
    return ServoReply(can_id=reply_id(servo_number), data=data)
