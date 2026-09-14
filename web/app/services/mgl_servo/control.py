"""Runtime install-mode control file for the MGL servo emulator.

The Cozy web Autopilot page writes this JSON. The FIX plugin polls it so
identify/limits can be armed without restarting fixgateway.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from web.app.services.mgl_servo.emulator import ServoEmulator
from web.app.services.mgl_servo.protocol import (
    INT12_MAX,
    INT12_MIN,
    clamp_s12,
    stored_to_s12,
)

STEPS = ("idle", "preflight", "identify", "limits", "done")
AXES = ("roll", "pitch")
LIMIT_KEYS = {
    "roll": ("left", "right"),
    "pitch": ("down", "up"),
}
POS_MIN = INT12_MIN
POS_MAX = INT12_MAX
OFFSET_MIN = INT12_MIN
OFFSET_MAX = INT12_MAX


def control_path() -> Path:
    env = os.environ.get("COZY_MGL_SERVO_CONTROL", "").strip()
    if env:
        return Path(env)
    if Path("/cozy-data-system").is_dir():
        return Path("/cozy-data-system/data/mgl_servo_control.json")
    return Path(__file__).resolve().parents[4] / "data" / "mgl_servo_control.json"


def default_control() -> dict[str, Any]:
    return {
        "session": "",
        "install_mode": False,
        "axis": None,
        "step": "idle",
        "manual_position": 0,
        "limits": {
            "roll": {"left": None, "right": None},
            "pitch": {"down": None, "up": None},
        },
        "offsets": {"roll": 0, "pitch": 0},
        "note": None,
    }


def clamp_pos(value: int) -> int:
    return clamp_s12(value)


def clamp_offset(value: int) -> int:
    return clamp_s12(value)


def limit_span(raw: dict[str, Any] | None, role: str = "roll") -> tuple[int, int]:
    """Numeric clamp range from the two captured stops.

    Extreme bank right and pitch up are negative. Do not assume left/down
    is the lower number — use min/max of the two captures. Legacy unsigned
    pairs (0 and 4095) look like 0 and -1 after sign extension; treat a
    wide unsigned pair as the full 12-bit range.
    """
    keys = LIMIT_KEYS.get(role) or ("left", "right")
    a_raw = (raw or {}).get(keys[0])
    b_raw = (raw or {}).get(keys[1])
    lo = stored_to_s12(a_raw)
    hi = stored_to_s12(b_raw)
    if lo is None or hi is None:
        return INT12_MIN, INT12_MAX
    try:
        ua, ub = int(a_raw), int(b_raw)
    except (TypeError, ValueError):
        ua, ub = lo, hi
    if max(ua, ub) > INT12_MAX and abs(ua - ub) >= 2048:
        return INT12_MIN, INT12_MAX
    return (lo, hi) if lo <= hi else (hi, lo)


def load_control() -> dict[str, Any]:
    path = control_path()
    data = default_control()
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            data.update(raw)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as e:
        data["note"] = f"control file unreadable: {e}"
    data.setdefault("limits", default_control()["limits"])
    for axis, keys in LIMIT_KEYS.items():
        data["limits"].setdefault(axis, {})
        for key in keys:
            data["limits"][axis].setdefault(key, None)
    if data.get("step") not in STEPS:
        data["step"] = "idle"
    if data.get("axis") not in AXES:
        data["axis"] = None
    data["manual_position"] = clamp_pos(stored_to_s12(data.get("manual_position") or 0) or 0)
    data["install_mode"] = bool(data.get("install_mode"))
    data.setdefault("offsets", default_control()["offsets"])
    if not isinstance(data.get("offsets"), dict):
        data["offsets"] = default_control()["offsets"]
    for axis in AXES:
        try:
            data["offsets"][axis] = clamp_offset(int(data["offsets"].get(axis) or 0))
        except (TypeError, ValueError):
            data["offsets"][axis] = 0
    return data


def save_control(data: dict[str, Any]) -> dict[str, Any]:
    path = control_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = default_control()
    merged.update(data)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    return merged


def apply_install_control(emu: ServoEmulator, ctrl: dict[str, Any]) -> None:
    """Map the control file onto a running emulator (FIX plugin thread)."""
    session = str(ctrl.get("session") or "")
    prev = getattr(emu, "_install_session", None)
    install = bool(ctrl.get("install_mode"))
    axis = ctrl.get("axis") if ctrl.get("axis") in AXES else None
    step = str(ctrl.get("step") or "idle")
    if session != prev:
        emu._install_session = session
        if install and axis:
            emu.start_install(axis)
        else:
            emu.restore_operational()
            apply_runtime_trim(emu, ctrl)
            return
    if not install:
        apply_runtime_trim(emu, ctrl)
        return
    emu.cfg.enabled = True
    if axis is None:
        apply_runtime_trim(emu, ctrl)
        return
    for other in emu.servos:
        other.enabled = True
    servo = emu.servo_by_role(axis)
    servo.enabled = True
    if step in ("identify", "limits", "done"):
        emu.cfg.allow_tx = True
        emu.cfg.tx_armed = True
    else:
        apply_runtime_trim(emu, ctrl)
        return
    if step == "identify":
        servo.mode = "echo"
        servo.identify_armed = False
    else:
        emu.enter_limits(axis, int(ctrl.get("manual_position") or 0))
    apply_runtime_trim(emu, ctrl)


def apply_runtime_trim(emu: ServoEmulator, ctrl: dict[str, Any]) -> None:
    offsets = ctrl.get("offsets") or {}
    limits = ctrl.get("limits") or {}
    for role in AXES:
        servo = emu.servo_by_role(role)
        try:
            servo.offset = clamp_offset(int(offsets.get(role) or 0))
        except (TypeError, ValueError):
            servo.offset = 0
        lo, hi = limit_span(limits.get(role) or {}, role)
        servo.limit_lo = lo
        servo.limit_hi = hi
        if servo.mode != "manual":
            servo.current = servo.reported_position()


class ControlPoller:
    def maybe_apply(self, emu: ServoEmulator) -> None:
        apply_install_control(emu, load_control())
