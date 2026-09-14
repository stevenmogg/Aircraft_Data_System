"""TX interlock for the MGL servo emulator.

All flags must be true. Default aircraft config leaves allow_tx false.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TxInterlock:
    allow_tx: bool = False
    tx_armed: bool = False
    emulator_enabled: bool = False
    interface_ok: bool = False
    servo_enabled: bool = False
    valid_state: bool = False
    valid_command: bool = False


def tx_allowed(lock: TxInterlock) -> bool:
    return bool(
        lock.allow_tx
        and lock.tx_armed
        and lock.emulator_enabled
        and lock.interface_ok
        and lock.servo_enabled
        and lock.valid_state
        and lock.valid_command
    )
