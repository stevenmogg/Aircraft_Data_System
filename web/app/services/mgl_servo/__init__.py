"""MGL autopilot servo emulator (Plan B: separate plugin, shared library)."""

from web.app.services.mgl_servo.emulator import ServoEmulator, VirtualServo
from web.app.services.mgl_servo.interlock import TxInterlock, tx_allowed
from web.app.services.mgl_servo.protocol import (
    IDENTIFY_ID,
    POSITION_ID,
    circular_error,
    decode_identify,
    decode_position,
    encode_reply,
    reply_id,
)

__all__ = [
    "IDENTIFY_ID",
    "POSITION_ID",
    "ServoEmulator",
    "TxInterlock",
    "VirtualServo",
    "circular_error",
    "decode_identify",
    "decode_position",
    "encode_reply",
    "reply_id",
    "tx_allowed",
]
