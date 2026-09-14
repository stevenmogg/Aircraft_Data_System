"""NMEA 0183 → MGL_NMEA_* FIX values.

Does not write canonical LAT/LONG/GS/TRACK (those stay Stratux). Empty
fields are omitted so the last good value remains until FIX stale/tol.
"""

from __future__ import annotations

from typing import Any, Callable

from web.app.services.units import m_to_ft

_MAX_RAW = 120


def xor_checksum(body: str) -> int:
    c = 0
    for ch in body:
        c ^= ord(ch)
    return c


def checksum_ok(line: str) -> bool:
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, tail = line[1:].partition("*")
    try:
        got = int(tail.strip()[:2], 16)
    except ValueError:
        return False
    return xor_checksum(body) == got


def dm_to_deg(raw: str, hemi: str) -> float | None:
    raw = (raw or "").strip()
    hemi = (hemi or "").strip().upper()
    if not raw or hemi not in ("N", "S", "E", "W"):
        return None
    try:
        if hemi in ("N", "S"):
            if "." not in raw or len(raw.split(".", 1)[0]) < 3:
                return None
            deg = int(raw[:2])
            minutes = float(raw[2:])
        else:
            if "." not in raw or len(raw.split(".", 1)[0]) < 4:
                return None
            deg = int(raw[:3])
            minutes = float(raw[3:])
    except ValueError:
        return None
    val = deg + minutes / 60.0
    if hemi in ("S", "W"):
        val = -val
    return val


def _f(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(s, 10)
    except ValueError:
        return None


def _s(s: str) -> str | None:
    s = (s or "").strip()
    return s or None


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    out[key] = value


def _g(fields: list[str], i: int) -> str:
    return fields[i] if i < len(fields) else ""


def _position(fields: list[str], lat_i: int, out: dict[str, Any]) -> None:
    lat_raw = _s(_g(fields, lat_i))
    ns = _s(_g(fields, lat_i + 1))
    lon_raw = _s(_g(fields, lat_i + 2))
    ew = _s(_g(fields, lat_i + 3))
    _put(out, "MGL_NMEA_LAT_RAW", lat_raw)
    _put(out, "MGL_NMEA_NS", ns)
    _put(out, "MGL_NMEA_LONG_RAW", lon_raw)
    _put(out, "MGL_NMEA_EW", ew)
    _put(out, "MGL_NMEA_LAT", dm_to_deg(lat_raw or "", ns or ""))
    _put(out, "MGL_NMEA_LONG", dm_to_deg(lon_raw or "", ew or ""))


def _gga(fields: list[str], out: dict[str, Any]) -> None:
    _put(out, "MGL_NMEA_TIME", _s(_g(fields, 0)))
    _position(fields, 1, out)
    qual = _i(_g(fields, 5))
    _put(out, "MGL_NMEA_QUAL", qual)
    if qual is not None:
        _put(out, "MGL_NMEA_VALID", qual >= 1)
    _put(out, "MGL_NMEA_SATS", _i(_g(fields, 6)))
    _put(out, "MGL_NMEA_HDOP", _f(_g(fields, 7)))
    alt = _f(_g(fields, 8))
    alt_unit = _s(_g(fields, 9))
    geoid = _f(_g(fields, 10))
    geoid_unit = _s(_g(fields, 11))
    if alt is not None and (not alt_unit or alt_unit.upper() == "M"):
        alt = round(m_to_ft(alt), 2)
    if geoid is not None and (not geoid_unit or geoid_unit.upper() == "M"):
        geoid = round(m_to_ft(geoid), 2)
    _put(out, "MGL_NMEA_ALT", alt)
    _put(out, "MGL_NMEA_ALT_UNIT", "ft" if alt is not None else alt_unit)
    _put(out, "MGL_NMEA_GEOID", geoid)
    _put(out, "MGL_NMEA_GEOID_UNIT", "ft" if geoid is not None else geoid_unit)
    _put(out, "MGL_NMEA_DGPS_AGE", _f(_g(fields, 12)))
    _put(out, "MGL_NMEA_DGPS_ID", _s(_g(fields, 13)))


def _rmc(fields: list[str], out: dict[str, Any]) -> None:
    _put(out, "MGL_NMEA_TIME", _s(_g(fields, 0)))
    status = _s(_g(fields, 1))
    _put(out, "MGL_NMEA_STATUS", status)
    if status is not None:
        _put(out, "MGL_NMEA_VALID", status.upper() == "A")
    _position(fields, 2, out)
    _put(out, "MGL_NMEA_GS", _f(_g(fields, 6)))
    _put(out, "MGL_NMEA_TRACK", _f(_g(fields, 7)))
    _put(out, "MGL_NMEA_DATE", _s(_g(fields, 8)))
    _put(out, "MGL_NMEA_MAGVAR", _f(_g(fields, 9)))
    _put(out, "MGL_NMEA_MAGVAR_EW", _s(_g(fields, 10)))
    _put(out, "MGL_NMEA_MODE", _s(_g(fields, 11)))
    _put(out, "MGL_NMEA_NAVSTAT", _s(_g(fields, 12)))


def _gll(fields: list[str], out: dict[str, Any]) -> None:
    _position(fields, 0, out)
    _put(out, "MGL_NMEA_TIME", _s(_g(fields, 4)))
    status = _s(_g(fields, 5))
    _put(out, "MGL_NMEA_STATUS", status)
    if status is not None:
        _put(out, "MGL_NMEA_VALID", status.upper() == "A")
    _put(out, "MGL_NMEA_MODE", _s(_g(fields, 6)))


def _vtg(fields: list[str], out: dict[str, Any]) -> None:
    _put(out, "MGL_NMEA_TRACK", _f(_g(fields, 0)))
    _put(out, "MGL_NMEA_TRACK_MAG", _f(_g(fields, 2)))
    _put(out, "MGL_NMEA_GS", _f(_g(fields, 4)))
    _put(out, "MGL_NMEA_GS_KMH", _f(_g(fields, 6)))
    _put(out, "MGL_NMEA_MODE", _s(_g(fields, 8)))


def _gsa(fields: list[str], out: dict[str, Any]) -> None:
    _put(out, "MGL_NMEA_GSA_MODE", _s(_g(fields, 0)))
    _put(out, "MGL_NMEA_GSA_FIX", _i(_g(fields, 1)))
    prns = [_s(_g(fields, i)) for i in range(2, 14)]
    used = ",".join(p for p in prns if p)
    _put(out, "MGL_NMEA_SATS_USED", used or None)
    _put(out, "MGL_NMEA_PDOP", _f(_g(fields, 14)))
    _put(out, "MGL_NMEA_HDOP", _f(_g(fields, 15)))
    _put(out, "MGL_NMEA_VDOP", _f(_g(fields, 16)))


def _gsv(fields: list[str], out: dict[str, Any]) -> None:
    _put(out, "MGL_NMEA_GSV_TOTAL", _i(_g(fields, 0)))
    _put(out, "MGL_NMEA_GSV_NUM", _i(_g(fields, 1)))
    _put(out, "MGL_NMEA_SATS_VIEW", _i(_g(fields, 2)))


_HANDLERS: dict[str, Callable[[list[str], dict[str, Any]], None]] = {
    "GGA": _gga,
    "RMC": _rmc,
    "GLL": _gll,
    "VTG": _vtg,
    "GSA": _gsa,
    "GSV": _gsv,
}


def parse_line(line: str) -> dict[str, Any]:
    """Return MGL_NMEA_* values for one line, or {} if it is not NMEA."""
    raw_in = line.strip("\r\n")
    dollar = raw_in.find("$")
    if dollar < 0:
        return {}
    raw_in = raw_in[dollar:]
    if "*" in raw_in:
        star = raw_in.index("*")
        raw_in = raw_in[: star + 3]
    if not raw_in.startswith("$") or len(raw_in) < 6:
        return {}
    ok = checksum_ok(raw_in)
    body = raw_in[1:].split("*", 1)[0]
    parts = body.split(",")
    tag = parts[0]
    if len(tag) < 4:
        return {}
    talker = tag[:-3]
    stype = tag[-3:].upper()
    fields = parts[1:]
    clipped = raw_in[:_MAX_RAW]
    out: dict[str, Any] = {
        "MGL_NMEA_RAW": clipped,
        "MGL_NMEA_TALKER": talker,
        "MGL_NMEA_TYPE": stype,
        "MGL_NMEA_CSUM_OK": ok,
    }
    if stype == "GGA":
        out["MGL_NMEA_GGA_RAW"] = clipped
    elif stype == "RMC":
        out["MGL_NMEA_RMC_RAW"] = clipped
    if not ok:
        return out
    handler = _HANDLERS.get(stype)
    if handler is not None:
        handler(fields, out)
    return out


_FIELD_LABELS: dict[str, tuple[str, str]] = {
    "MGL_NMEA_TIME": ("UTC time", ""),
    "MGL_NMEA_DATE": ("UTC date", ""),
    "MGL_NMEA_LAT": ("Latitude", "°"),
    "MGL_NMEA_LONG": ("Longitude", "°"),
    "MGL_NMEA_LAT_RAW": ("Lat raw", ""),
    "MGL_NMEA_NS": ("N/S", ""),
    "MGL_NMEA_LONG_RAW": ("Lon raw", ""),
    "MGL_NMEA_EW": ("E/W", ""),
    "MGL_NMEA_QUAL": ("Quality", ""),
    "MGL_NMEA_SATS": ("Sats used", ""),
    "MGL_NMEA_HDOP": ("HDOP", ""),
    "MGL_NMEA_ALT": ("Alt MSL", "ft"),
    "MGL_NMEA_ALT_UNIT": ("Alt unit", ""),
    "MGL_NMEA_GEOID": ("Geoid sep", "ft"),
    "MGL_NMEA_GEOID_UNIT": ("Geoid unit", ""),
    "MGL_NMEA_DGPS_AGE": ("DGPS age", "s"),
    "MGL_NMEA_DGPS_ID": ("DGPS id", ""),
    "MGL_NMEA_STATUS": ("Status", ""),
    "MGL_NMEA_VALID": ("Valid", ""),
    "MGL_NMEA_GS": ("Ground speed", "kt"),
    "MGL_NMEA_TRACK": ("Track true", "°"),
    "MGL_NMEA_MAGVAR": ("Mag var", "°"),
    "MGL_NMEA_MAGVAR_EW": ("Mag var E/W", ""),
    "MGL_NMEA_MODE": ("Mode", ""),
    "MGL_NMEA_NAVSTAT": ("Nav status", ""),
}

_GGA_ORDER = (
    "MGL_NMEA_TIME",
    "MGL_NMEA_LAT",
    "MGL_NMEA_NS",
    "MGL_NMEA_LONG",
    "MGL_NMEA_EW",
    "MGL_NMEA_QUAL",
    "MGL_NMEA_SATS",
    "MGL_NMEA_HDOP",
    "MGL_NMEA_ALT",
    "MGL_NMEA_GEOID",
    "MGL_NMEA_DGPS_AGE",
    "MGL_NMEA_DGPS_ID",
    "MGL_NMEA_LAT_RAW",
    "MGL_NMEA_LONG_RAW",
    "MGL_NMEA_VALID",
)

_RMC_ORDER = (
    "MGL_NMEA_TIME",
    "MGL_NMEA_DATE",
    "MGL_NMEA_STATUS",
    "MGL_NMEA_VALID",
    "MGL_NMEA_LAT",
    "MGL_NMEA_NS",
    "MGL_NMEA_LONG",
    "MGL_NMEA_EW",
    "MGL_NMEA_GS",
    "MGL_NMEA_TRACK",
    "MGL_NMEA_MAGVAR",
    "MGL_NMEA_MAGVAR_EW",
    "MGL_NMEA_MODE",
    "MGL_NMEA_NAVSTAT",
    "MGL_NMEA_LAT_RAW",
    "MGL_NMEA_LONG_RAW",
)

_TYPE_ORDER = {"GGA": _GGA_ORDER, "RMC": _RMC_ORDER}


def display_fields(parsed: dict[str, Any], stype: str | None = None) -> list[dict[str, Any]]:
    """Friendly field list for one parsed sentence (no meta/raw keys)."""
    kind = (stype or str(parsed.get("MGL_NMEA_TYPE") or "")).upper()
    order = _TYPE_ORDER.get(kind, ())
    rows: list[dict[str, Any]] = []
    for key in order:
        if key not in parsed:
            continue
        label, units = _FIELD_LABELS.get(key, (key, ""))
        rows.append({"key": key, "name": label, "value": parsed[key], "units": units})
    return rows
