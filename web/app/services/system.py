"""Host / network / service status helpers."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Pi 5 USB-C rail: ~5.0–5.1 V healthy; PMIC trips near 4.63 V.
EXT5V_OK_V = 4.95
EXT5V_TRIP_V = 4.63

_THROTTLE_BITS = (
    (1 << 0, "undervoltage now"),
    (1 << 1, "freq capped now"),
    (1 << 2, "throttled now"),
    (1 << 3, "soft temp limit now"),
    (1 << 16, "undervoltage occurred"),
    (1 << 17, "freq capped occurred"),
    (1 << 18, "throttled occurred"),
    (1 << 19, "soft temp limit occurred"),
)

_SMB_SHARE = "cozy-data"
_SMB_PATH = "/cozy-data-system/data"


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return (p.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _service_state(unit: str) -> dict[str, Any]:
    active = _run(["systemctl", "is-active", unit]) or "unknown"
    enabled = _run(["systemctl", "is-enabled", unit]) or "unknown"
    return {
        "unit": unit,
        "active": active,
        "enabled": enabled,
        "ok": active == "active" or (unit.endswith(".path") and active in ("active",)),
    }


def parse_throttled(text: str) -> int | None:
    """Parse `vcgencmd get_throttled` (`throttled=0x50005`)."""
    if not text:
        return None
    m = re.search(r"0x[0-9a-fA-F]+", text)
    if not m:
        return None
    try:
        return int(m.group(0), 16)
    except ValueError:
        return None


def parse_ext5v(text: str) -> float | None:
    """Parse `vcgencmd pmic_read_adc EXT5V_V` (`EXT5V_V volt=4.83012000V`)."""
    if not text:
        return None
    m = re.search(r"volt\s*=\s*(\d+(?:\.\d+)?)\s*V", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+\.\d+)\s*V", text, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def throttle_flags(mask: int) -> list[str]:
    return [label for bit, label in _THROTTLE_BITS if mask & bit]


def classify_power(
    ext5v_v: float | None,
    mask: int | None,
) -> tuple[bool | None, str | None]:
    """Return (ok, level) for Status badges. None if no Pi power data."""
    if ext5v_v is None and mask is None:
        return None, None
    uv_now = bool(mask is not None and mask & (1 << 0))
    throttled_now = bool(mask is not None and mask & (1 << 2))
    uv_occurred = bool(mask is not None and mask & (1 << 16))
    if uv_now or (ext5v_v is not None and ext5v_v < EXT5V_TRIP_V):
        return False, "bad"
    if throttled_now or (ext5v_v is not None and ext5v_v < EXT5V_OK_V):
        return False, "warn"
    if uv_occurred:
        return True, "warn"
    return True, "ok"


def _port_listening(port: int) -> bool | None:
    hexport = f"{port:04X}"
    saw_table = False
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        text = _read_text(path)
        if not text:
            continue
        saw_table = True
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            local = parts[1].upper()
            state = parts[3]
            if state == "0A" and local.endswith(":" + hexport):
                return True
    if saw_table:
        return False
    ss = _run(["ss", "-ltn"])
    if not ss:
        return None
    return bool(re.search(rf":{port}(?:\s|$)", ss))


def power_status() -> dict[str, Any]:
    throttled_raw = _run(["vcgencmd", "get_throttled"])
    ext5v_raw = _run(["vcgencmd", "pmic_read_adc", "EXT5V_V"])
    mask = parse_throttled(throttled_raw)
    ext5v_v = parse_ext5v(ext5v_raw)
    ok, level = classify_power(ext5v_v, mask)
    flags = throttle_flags(mask) if mask is not None else []
    return {
        "ok": ok,
        "level": level,
        "available": mask is not None or ext5v_v is not None,
        "ext5v_v": ext5v_v,
        "throttled": None if mask is None else f"0x{mask:x}",
        "undervoltage_now": None if mask is None else bool(mask & (1 << 0)),
        "undervoltage_occurred": None if mask is None else bool(mask & (1 << 16)),
        "throttled_now": None if mask is None else bool(mask & (1 << 2)),
        "throttled_occurred": None if mask is None else bool(mask & (1 << 18)),
        "flags": flags,
    }


def samba_status() -> dict[str, Any]:
    smbd = _service_state("smbd.service")
    listening = _port_listening(445)
    active = smbd["active"] == "active"
    ok = active and listening is not False
    return {
        "ok": ok,
        "share": _SMB_SHARE,
        "path": _SMB_PATH,
        "smbd": smbd,
        "listening_445": listening,
    }


def fan_status() -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False}
    cooling = Path("/sys/class/thermal/cooling_device0")
    if cooling.is_dir():
        try:
            out["cooling_type"] = (cooling / "type").read_text().strip()
            out["cur_state"] = int((cooling / "cur_state").read_text().strip())
            out["max_state"] = int((cooling / "max_state").read_text().strip())
            out["ok"] = True
        except (OSError, ValueError):
            pass
    for h in Path("/sys/class/hwmon").glob("hwmon*"):
        name = _read_text(str(h / "name")) or ""
        if "pwmfan" in name or name == "pwmfan":
            rpm = _read_text(str(h / "fan1_input"))
            pwm = _read_text(str(h / "pwm1"))
            try:
                out["rpm"] = int(rpm) if rpm else 0
            except ValueError:
                out["rpm"] = None
            try:
                out["pwm"] = int(pwm) if pwm else None
            except ValueError:
                out["pwm"] = None
            out["hwmon"] = name
            out["ok"] = True
            break
    return out


def services_status() -> dict[str, Any]:
    units = [
        "stratux.service",
        "fixgateway.service",
        "cozy-web.service",
        "cozy-historian.service",
        "cozy-historian-data.service",
        "cozy-mgl-plans.path",
    ]
    items = [_service_state(u) for u in units]
    critical = [i for i in items if i["unit"] in (
        "stratux.service",
        "fixgateway.service",
        "cozy-web.service",
        "cozy-historian.service",
        "cozy-historian-data.service",
    )]
    return {
        "ok": all(i["active"] == "active" for i in critical),
        "items": items,
    }


def system_status() -> dict[str, Any]:
    uptime_s = None
    raw = _read_text("/proc/uptime")
    if raw:
        try:
            uptime_s = float(raw.split()[0])
        except ValueError:
            pass

    disk = None
    try:
        st = os.statvfs("/cozy-data-system/data/historian")
        disk = {
            "path": "/cozy-data-system/data/historian",
            "free_bytes": st.f_bavail * st.f_frsize,
            "total_bytes": st.f_blocks * st.f_frsize,
        }
    except OSError:
        pass

    temp_c = None
    traw = _read_text("/sys/class/thermal/thermal_zone0/temp")
    if traw and traw.isdigit():
        temp_c = int(traw) / 1000.0

    loadavg = None
    try:
        loadavg = list(os.getloadavg())
    except OSError:
        pass

    return {
        "hostname": os.uname().nodename if hasattr(os, "uname") else None,
        "uptime_s": uptime_s,
        "cpu_temp_c": temp_c,
        "loadavg": loadavg,
        "disk": disk,
        "fan": fan_status(),
        "power": power_status(),
        "samba": samba_status(),
        "services": services_status(),
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
