"""MGL Autopilot install wizard: control file, FIX snapshot, can0 TX."""

from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any

from web.app.services.can_monitor import get_monitor
from web.app.services.mgl_servo.control import (
    AXES,
    LIMIT_KEYS,
    clamp_offset,
    default_control,
    limit_span,
    load_control,
    save_control,
)
from web.app.services.mgl_servo.protocol import IDENTIFY_ID, POSITION_ID, reply_id, s12_to_u12, stored_to_s12

log = logging.getLogger("cozy.web.mgl_servo_install")

FIX_KEYS = (
    "MGL_SRV_ALLOW_TX",
    "MGL_SRV_TX_ARMED",
    "MGL_SRV_LAST_ID",
    "MGL_SRV_LAST_ID_OK",
    "MGL_SRV_ROLL_NUM",
    "MGL_SRV_ROLL_IDARM",
    "MGL_SRV_ROLL_IDOK",
    "MGL_SRV_ROLL_STATE",
    "MGL_SRV_ROLL_CUR",
    "MGL_SRV_ROLL_TGT",
    "MGL_SRV_ROLL_HZ",
    "MGL_SRV_ROLL_RPLY",
    "MGL_SRV_ROLL_CMDS",
    "MGL_SRV_ROLL_ENG_REQ",
    "MGL_SRV_ROLL_ENG",
    "MGL_SRV_ROLL_OPT",
    "MGL_SRV_PITCH_NUM",
    "MGL_SRV_PITCH_IDARM",
    "MGL_SRV_PITCH_IDOK",
    "MGL_SRV_PITCH_STATE",
    "MGL_SRV_PITCH_CUR",
    "MGL_SRV_PITCH_TGT",
    "MGL_SRV_PITCH_HZ",
    "MGL_SRV_PITCH_RPLY",
    "MGL_SRV_PITCH_CMDS",
    "MGL_SRV_PITCH_ENG_REQ",
    "MGL_SRV_PITCH_ENG",
    "MGL_SRV_PITCH_OPT",
)

SETUP_CAN0 = "/cozy-data-system/scripts/setup_can0.sh"
BITRATE = 250000


def _new_session() -> str:
    return uuid.uuid4().hex[:12]


def _fix_snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "keys": {}}
    try:
        from historian.capture.fix_client import FixClient

        client = FixClient(host="127.0.0.1", port=3490, timeout=1.0)
        client.connect(list(FIX_KEYS))
        samples = client.read_many(FIX_KEYS)
        client.disconnect()
        keys = {k: (s.value if s.value is not None else s.raw) for k, s in samples.items()}
        out["ok"] = True
        out["keys"] = keys
    except Exception as e:
        out["error"] = str(e)
    return out


def _servo_frames(messages: list[dict[str, Any]]) -> dict[str, Any]:
    want = {IDENTIFY_ID, POSITION_ID, reply_id(1), reply_id(2)}
    found: dict[str, Any] = {}
    for msg in messages:
        cid = msg.get("can_id_int")
        if cid not in want:
            continue
        found[f"0x{int(cid):03X}"] = {
            "count": msg.get("count"),
            "age_ms": msg.get("age_ms"),
            "dlc": msg.get("dlc"),
            "payload": msg.get("payload"),
            "rate_hz": msg.get("rate_hz"),
        }
    return found


def _as_bool(value: Any) -> bool | None:
    if value is True or value == "True" or value == 1 or value == 1.0:
        return True
    if value is False or value == "False" or value == 0 or value == 0.0:
        return False
    return None


def _axis_view(role: str, keys: dict[str, Any], ctrl: dict[str, Any]) -> dict[str, Any]:
    prefix = "MGL_SRV_ROLL" if role == "roll" else "MGL_SRV_PITCH"
    lim = ((ctrl.get("limits") or {}).get(role) or {})
    lo, hi = limit_span(lim, role)
    offset = clamp_offset(int((ctrl.get("offsets") or {}).get(role) or 0))
    tgt = keys.get(f"{prefix}_TGT")
    cur = keys.get(f"{prefix}_CUR")
    command = None
    try:
        if tgt is not None and tgt != "":
            command = int(float(tgt))
    except (TypeError, ValueError):
        command = None
    response = None
    if command is not None:
        response = max(lo, min(hi, command + offset))
    try:
        if cur is not None and cur != "":
            response = int(float(cur))
    except (TypeError, ValueError):
        pass
    signed_limits = {key: stored_to_s12(lim.get(key)) for key in (LIMIT_KEYS.get(role) or ())}
    raw_cmd = s12_to_u12(command) if command is not None else None
    raw_resp = s12_to_u12(response) if response is not None else None
    return {
        "command": command,
        "command_raw": raw_cmd,
        "offset": offset,
        "response": response,
        "response_raw": raw_resp,
        "limit_lo": lo,
        "limit_hi": hi,
        "limits": signed_limits,
        "limits_raw": lim,
        "hz": keys.get(f"{prefix}_HZ"),
        "num": keys.get(f"{prefix}_NUM"),
        "replies": keys.get(f"{prefix}_RPLY"),
        "commands": keys.get(f"{prefix}_CMDS"),
        "engage_req": _as_bool(keys.get(f"{prefix}_ENG_REQ")),
        "engaged": _as_bool(keys.get(f"{prefix}_ENG")),
        "options": keys.get(f"{prefix}_OPT"),
    }


def snapshot() -> dict[str, Any]:
    ctrl = load_control()
    can: dict[str, Any] = {}
    frames: dict[str, Any] = {}
    try:
        snap = get_monitor().snapshot()
        can = snap.get("can") or {}
        frames = _servo_frames(snap.get("messages") or [])
    except Exception as e:
        can = {"error": str(e)}
    fix = _fix_snapshot()
    axis = ctrl.get("axis")
    prefix = "MGL_SRV_ROLL" if axis == "roll" else "MGL_SRV_PITCH"
    keys = fix.get("keys") or {}
    return {
        "ok": True,
        "control": ctrl,
        "can": can,
        "frames": frames,
        "fix": fix,
        "axes": {role: _axis_view(role, keys, ctrl) for role in AXES},
        "live": {
            "last_id": keys.get("MGL_SRV_LAST_ID"),
            "last_id_ok": keys.get("MGL_SRV_LAST_ID_OK"),
            "num": keys.get(f"{prefix}_NUM"),
            "identified": keys.get(f"{prefix}_IDOK"),
            "identify_armed": keys.get(f"{prefix}_IDARM"),
            "current": keys.get(f"{prefix}_CUR"),
            "target": keys.get(f"{prefix}_TGT"),
            "replies": keys.get(f"{prefix}_RPLY"),
            "commands": keys.get(f"{prefix}_CMDS"),
            "tx_armed": keys.get("MGL_SRV_TX_ARMED"),
            "allow_tx": keys.get("MGL_SRV_ALLOW_TX"),
        },
    }


def start_install(axis: str) -> dict[str, Any]:
    if axis not in AXES:
        raise ValueError("axis must be roll or pitch")
    prev = load_control()
    ctrl = default_control()
    ctrl["limits"] = prev.get("limits") or ctrl["limits"]
    ctrl["offsets"] = prev.get("offsets") or ctrl["offsets"]
    ctrl["session"] = _new_session()
    ctrl["install_mode"] = True
    ctrl["axis"] = axis
    ctrl["step"] = "preflight"
    ctrl["manual_position"] = 0
    save_control(ctrl)
    return snapshot()


def set_step(step: str) -> dict[str, Any]:
    allowed = ("preflight", "identify", "limits", "done")
    if step not in allowed:
        raise ValueError(f"step must be one of {allowed}")
    ctrl = load_control()
    if not ctrl.get("install_mode"):
        raise ValueError("not in install mode")
    ctrl["step"] = step
    save_control(ctrl)
    return snapshot()


def set_position(position: int) -> dict[str, Any]:
    ctrl = load_control()
    if not ctrl.get("install_mode"):
        raise ValueError("not in install mode")
    ctrl["manual_position"] = clamp_offset(int(position))
    if ctrl.get("step") != "limits":
        ctrl["step"] = "limits"
    save_control(ctrl)
    return snapshot()


def capture_limit(which: str) -> dict[str, Any]:
    ctrl = load_control()
    axis = ctrl.get("axis")
    if axis not in LIMIT_KEYS or which not in LIMIT_KEYS[axis]:
        raise ValueError("limit does not match the selected axis")
    pos = clamp_offset(int(ctrl.get("manual_position") or 0))
    ctrl["limits"][axis][which] = pos
    save_control(ctrl)
    return snapshot()


def set_offset(axis: str, offset: int) -> dict[str, Any]:
    if axis not in AXES:
        raise ValueError("axis must be roll or pitch")
    ctrl = load_control()
    ctrl.setdefault("offsets", default_control()["offsets"])
    ctrl["offsets"][axis] = clamp_offset(int(offset))
    save_control(ctrl)
    return snapshot()


def abort_install() -> dict[str, Any]:
    ctrl = load_control()
    ctrl["session"] = _new_session()
    ctrl["install_mode"] = False
    ctrl["step"] = "idle"
    ctrl["axis"] = None
    save_control(ctrl)
    return snapshot()


def _sudo(cmd: list[str], timeout: float = 8.0) -> tuple[int, str]:
    proc = subprocess.run(
        ["sudo", "-n", *cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, text


def set_can_tx(enable: bool) -> dict[str, Any]:
    """Drop or restore listen-only on can0 (passwordless sudo)."""
    script = Path(SETUP_CAN0)
    if script.is_file():
        flag = "--up-tx" if enable else "--up"
        rc, text = _sudo([str(script), flag])
        return {"ok": rc == 0, "enable": enable, "detail": text, "via": "setup_can0"}
    channel = "can0"
    _sudo(["ip", "link", "set", channel, "down"])
    if enable:
        _sudo(
            [
                "ip",
                "link",
                "set",
                channel,
                "type",
                "can",
                "bitrate",
                str(BITRATE),
                "listen-only",
                "off",
            ]
        )
        rc, text = _sudo(["ip", "link", "set", channel, "up"])
    else:
        rc, text = _sudo(
            [
                "ip",
                "link",
                "set",
                channel,
                "up",
                "type",
                "can",
                "bitrate",
                str(BITRATE),
                "listen-only",
                "on",
            ]
        )
    return {"ok": rc == 0, "enable": enable, "detail": text, "via": "ip"}
