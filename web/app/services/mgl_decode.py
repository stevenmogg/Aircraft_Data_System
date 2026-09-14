"""MGL CAN ID parsing and YAML-driven field decode."""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any

from web.app.services.units import c_to_f

log = logging.getLogger("cozy.web.mgl_decode")

DEVICE_FAMILIES = (
    ((1, 15), "host/EFIS"),
    ((16, 31), "servo"),
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

DEFAULT_MAP_PATHS = (
    Path("/cozy-data-system/config/mgl_can/decode_map.yaml"),
    Path(__file__).resolve().parents[3] / "config" / "mgl_can" / "decode_map.yaml",
)


def parse_id(can_id: int) -> tuple[int, int]:
    return (can_id >> 4) & 0x7F, can_id & 0x0F


def device_family(addr: int) -> str:
    for (lo, hi), name in DEVICE_FAMILIES:
        if lo <= addr <= hi:
            return name
    return "unknown"


def payload_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def extract_field(data: bytes, field: dict[str, Any]) -> Any:
    """Extract one field from a CAN payload using decode_map field rules."""
    ftype = str(field.get("type") or "raw_hex")
    offset = int(field.get("offset") or 0)
    scale = float(field.get("scale") if field.get("scale") is not None else 1.0)
    offset_add = float(field.get("offset_add") if field.get("offset_add") is not None else 0.0)

    if ftype == "raw_hex":
        return payload_hex(data[offset:]) if offset < len(data) else ""

    try:
        if ftype == "u8":
            if offset >= len(data):
                return None
            raw: int | float = data[offset]
        elif ftype == "le_i16":
            if offset + 2 > len(data):
                return None
            raw = struct.unpack_from("<h", data, offset)[0]
        elif ftype == "le_u16":
            if offset + 2 > len(data):
                return None
            raw = struct.unpack_from("<H", data, offset)[0]
        elif ftype == "le_i32":
            if offset + 4 > len(data):
                return None
            raw = struct.unpack_from("<i", data, offset)[0]
        else:
            log.warning("unknown field type %s", ftype)
            return None
    except struct.error:
        return None

    value = float(raw) * scale + offset_add
    if scale == 1.0 and offset_add == 0.0 and ftype != "raw_hex":
        return int(raw)
    if value == int(value):
        return int(value)
    return round(value, 4)


class DecodeMap:
    """Loaded decode_map.yaml with lookup by (device, msg)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path | None = path
        self.mtime: float | None = None
        self.channel = "can0"
        self.bitrate = 250000
        self.devices: dict[int, dict[str, Any]] = {}
        self._messages: dict[tuple[int, int], dict[str, Any]] = {}
        self.error: str | None = None
        self.reload(path)

    def reload(self, path: Path | None = None) -> None:
        if path is not None:
            self.path = path
        elif self.path is None:
            for p in DEFAULT_MAP_PATHS:
                if p.is_file():
                    self.path = p
                    break
        if self.path is None or not self.path.is_file():
            self.error = f"decode map not found ({self.path})"
            self.devices = {}
            self._messages = {}
            self.mtime = None
            return

        try:
            import yaml

            text = self.path.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}
            self.channel = str(data.get("channel") or "can0")
            self.bitrate = int(data.get("bitrate") or 250000)
            devices_raw = data.get("devices") or {}
            self.devices = {int(k): (v or {}) for k, v in devices_raw.items()}
            self._messages = {}
            for msg in data.get("messages") or []:
                key = (int(msg["device"]), int(msg["msg"]))
                self._messages[key] = msg
            self.mtime = self.path.stat().st_mtime
            self.error = None
        except Exception as e:
            self.error = str(e)
            log.exception("failed to load decode map %s", self.path)

    def maybe_reload(self) -> bool:
        """Reload if file mtime changed. Returns True if reloaded."""
        if self.path is None or not self.path.is_file():
            return False
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if self.mtime is None or mtime != self.mtime:
            self.reload()
            return True
        return False

    @property
    def message_rule_count(self) -> int:
        return len(self._messages)

    def has_mapping(self, device: int, msg: int) -> bool:
        return (device, msg) in self._messages

    def device_label(self, device: int) -> str:
        d = self.devices.get(device) or {}
        return str(d.get("name") or d.get("family") or device_family(device))

    def decode_frame(self, can_id: int, data: bytes) -> list[dict[str, Any]]:
        device, msg = parse_id(can_id)
        rule = self._messages.get((device, msg))
        if not rule:
            return []
        out: list[dict[str, Any]] = []
        for field in rule.get("fields") or []:
            value = extract_field(data, field)
            out.append(
                {
                    "name": field.get("name"),
                    "fix_key": field.get("fix_key"),
                    "units": field.get("units") or "",
                    "value": value,
                    "can_id": f"0x{can_id:X}",
                    "device": device,
                    "msg": msg,
                }
            )
        return out


def fields_to_fix(fields: list[dict[str, Any]]) -> dict[str, float | int]:
    """Map decode_map fields onto FIX keys (skip dotted / non-numeric)."""
    out: dict[str, float | int] = {}
    for field in fields:
        key = field.get("fix_key")
        if not key or not isinstance(key, str) or "." in key:
            continue
        value = field.get("value")
        if value is None or isinstance(value, (str, bool)):
            continue
        if isinstance(value, int):
            out[key] = value
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


class RdacCompensator:
    """Convert RDAC wire °C into FIX °F, with cold-junction added to TCs."""

    def __init__(self) -> None:
        self.cj_c: float | None = None
        self.tc_c: dict[int, float] = {}

    def apply(self, values: dict[str, float | int]) -> dict[str, float | int]:
        out: dict[str, float | int] = dict(values)
        cj_updated = False
        if "MGL_RDAC_TEMP" in values and values["MGL_RDAC_TEMP"] is not None:
            self.cj_c = float(values["MGL_RDAC_TEMP"])
            out["MGL_RDAC_TEMP"] = round(c_to_f(self.cj_c), 2)
            cj_updated = True
        tc_updated = False
        for i in range(1, 13):
            key = f"MGL_RDAC_TC{i}"
            if key in values and values[key] is not None:
                self.tc_c[i] = float(values[key])
                tc_updated = True
        if not cj_updated and not tc_updated:
            return out
        if self.cj_c is None:
            for i in range(1, 13):
                out.pop(f"MGL_RDAC_TC{i}", None)
            return out
        for i, delta_c in self.tc_c.items():
            out[f"MGL_RDAC_TC{i}"] = round(c_to_f(delta_c + self.cj_c), 2)
        return out
