"""Host / network / service status helpers."""

from __future__ import annotations

import os
import re
import subprocess
import threading
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
_HISTORIAN_DISK = "/cozy-data-system/data/historian"

_util_lock = threading.Lock()
_prev_util: dict[str, Any] = {"t": None, "cpu": None, "net": None, "disk": None}


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


def parse_proc_stat(text: str) -> dict[str, int] | None:
    """Parse the aggregate `cpu` line from /proc/stat."""
    if not text:
        return None
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        if len(parts) < 5:
            return None
        try:
            nums = [int(x) for x in parts[1:]]
        except ValueError:
            return None
        user, nice, system, idle = nums[0], nums[1], nums[2], nums[3]
        iowait = nums[4] if len(nums) > 4 else 0
        irq = nums[5] if len(nums) > 5 else 0
        softirq = nums[6] if len(nums) > 6 else 0
        steal = nums[7] if len(nums) > 7 else 0
        idle_all = idle + iowait
        total = user + nice + system + idle + iowait + irq + softirq + steal
        return {
            "user": user + nice,
            "system": system + irq + softirq,
            "iowait": iowait,
            "idle": idle_all,
            "total": total,
        }
    return None


def cpu_percent_from_delta(
    prev: dict[str, int], curr: dict[str, int]
) -> dict[str, float] | None:
    dt = curr["total"] - prev["total"]
    if dt <= 0:
        return None
    busy = dt - (curr["idle"] - prev["idle"])
    return {
        "percent": round(100.0 * busy / dt, 1),
        "user_pct": round(100.0 * (curr["user"] - prev["user"]) / dt, 1),
        "system_pct": round(100.0 * (curr["system"] - prev["system"]) / dt, 1),
        "iowait_pct": round(100.0 * (curr["iowait"] - prev["iowait"]) / dt, 1),
    }


def parse_proc_net_dev(text: str) -> dict[str, dict[str, int]]:
    """Bytes received/transmitted per interface from /proc/net/dev."""
    out: dict[str, dict[str, int]] = {}
    if not text:
        return out
    for line in text.splitlines():
        if ":" not in line or line.strip().startswith("Inter") or line.strip().startswith("face"):
            continue
        name, rest = line.split(":", 1)
        iface = name.strip()
        if not _keep_net_iface(iface):
            continue
        cols = rest.split()
        if len(cols) < 9:
            continue
        try:
            out[iface] = {"rx_bytes": int(cols[0]), "tx_bytes": int(cols[8])}
        except ValueError:
            continue
    return out


def _keep_net_iface(name: str) -> bool:
    if name == "lo":
        return False
    return not name.startswith(
        ("docker", "veth", "br-", "virbr", "tun", "tap", "dummy", "sit", "cni")
    )


def parse_proc_diskstats(text: str, sector_bytes: int = 512) -> dict[str, dict[str, int]]:
    """Read/write bytes per whole disk from /proc/diskstats."""
    out: dict[str, dict[str, int]] = {}
    if not text:
        return out
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 10:
            continue
        name = cols[2]
        if not _is_whole_disk(name):
            continue
        try:
            rsect = int(cols[5])
            wsect = int(cols[9])
        except ValueError:
            continue
        out[name] = {
            "read_bytes": rsect * sector_bytes,
            "write_bytes": wsect * sector_bytes,
        }
    return out


def _is_whole_disk(name: str) -> bool:
    if name.startswith(("loop", "ram", "zram", "dm-", "md", "sr")):
        return False
    if re.match(r"^(mmcblk\d+|nvme\d+n\d+)p\d+$", name):
        return False
    if re.match(r"^(sd|hd|vd|xvd)[a-z]+\d+$", name):
        return False
    return True


def _disk_usage(path: str) -> dict[str, Any] | None:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - free
    return {
        "path": path,
        "total_bytes": total,
        "free_bytes": free,
        "used_bytes": used,
        "used_pct": round(100.0 * used / total, 1) if total else None,
    }


def _rate(prev: int, curr: int, dt: float) -> float | None:
    if dt <= 0:
        return None
    delta = curr - prev
    if delta < 0:
        return None
    return delta / dt


def _host_utilisation() -> dict[str, Any]:
    """CPU / disk / network utilisation from /proc counters."""
    cpu_a = parse_proc_stat(_read_text("/proc/stat") or "")
    net_a = parse_proc_net_dev(_read_text("/proc/net/dev") or "")
    disk_a = parse_proc_diskstats(_read_text("/proc/diskstats") or "")
    t_a = time.monotonic()

    with _util_lock:
        prev_t = _prev_util["t"]
        prev_cpu = _prev_util["cpu"]
        prev_net = _prev_util["net"]
        prev_disk = _prev_util["disk"]
        seeded = prev_t is not None

    if not seeded:
        time.sleep(0.08)
        cpu_b = parse_proc_stat(_read_text("/proc/stat") or "")
        net_b = parse_proc_net_dev(_read_text("/proc/net/dev") or "")
        disk_b = parse_proc_diskstats(_read_text("/proc/diskstats") or "")
        t_b = time.monotonic()
        prev_t, prev_cpu, prev_net, prev_disk = t_a, cpu_a, net_a, disk_a
        cpu_now, net_now, disk_now, t_now = cpu_b, net_b, disk_b, t_b
    else:
        cpu_now, net_now, disk_now, t_now = cpu_a, net_a, disk_a, t_a

    dt = None if prev_t is None else (t_now - prev_t)
    cpu_pct = (
        cpu_percent_from_delta(prev_cpu, cpu_now) if prev_cpu and cpu_now else None
    )
    net_ifaces: list[dict[str, Any]] = []
    if dt and prev_net:
        for name, curr in net_now.items():
            old = prev_net.get(name)
            if not old:
                continue
            net_ifaces.append(
                {
                    "iface": name,
                    "rx_bps": _rate(old["rx_bytes"], curr["rx_bytes"], dt),
                    "tx_bps": _rate(old["tx_bytes"], curr["tx_bytes"], dt),
                }
            )
        net_ifaces.sort(key=lambda x: x["iface"])
    disk_io: list[dict[str, Any]] = []
    if dt and prev_disk:
        for name, curr in disk_now.items():
            old = prev_disk.get(name)
            if not old:
                continue
            disk_io.append(
                {
                    "name": name,
                    "read_bps": _rate(old["read_bytes"], curr["read_bytes"], dt),
                    "write_bps": _rate(old["write_bytes"], curr["write_bytes"], dt),
                }
            )
        disk_io.sort(key=lambda x: x["name"])

    with _util_lock:
        _prev_util["t"] = t_now
        _prev_util["cpu"] = cpu_now
        _prev_util["net"] = net_now
        _prev_util["disk"] = disk_now

    cpu_out: dict[str, Any] = {
        "nproc": os.cpu_count(),
        "percent": None,
        "user_pct": None,
        "system_pct": None,
        "iowait_pct": None,
    }
    if cpu_pct:
        cpu_out.update(cpu_pct)
    return {
        "cpu": cpu_out,
        "network": {"interfaces": net_ifaces},
        "disk_io": disk_io,
    }


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

    historian_disk = _disk_usage(_HISTORIAN_DISK)
    root_disk = _disk_usage("/")
    volumes = [v for v in (historian_disk, root_disk) if v]
    # Keep a unique list if historian is on the same filesystem as /
    seen: set[str] = set()
    unique_volumes: list[dict[str, Any]] = []
    for vol in volumes:
        key = vol["path"]
        if key in seen:
            continue
        seen.add(key)
        unique_volumes.append(vol)

    disk = historian_disk or root_disk
    try:
        util = _host_utilisation()
    except Exception:
        util = {
            "cpu": {
                "nproc": os.cpu_count(),
                "percent": None,
                "user_pct": None,
                "system_pct": None,
                "iowait_pct": None,
            },
            "network": {"interfaces": []},
            "disk_io": [],
        }
    if disk is None:
        disk = {"path": None, "free_bytes": None, "total_bytes": None}
    disk = dict(disk)
    disk["volumes"] = unique_volumes
    disk["io"] = util.get("disk_io") or []

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
        "cpu": util.get("cpu"),
        "disk": disk,
        "network": util.get("network"),
        "fan": fan_status(),
        "power": power_status(),
        "samba": samba_status(),
        "services": services_status(),
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
