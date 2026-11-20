"""Load FIX-Gateway database YAML the same way fixgw expands variable suffixes."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _simple_yaml_mapping(text)


def _simple_yaml_mapping(text: str) -> dict[str, Any]:
    """Minimal parser for FIX database YAML (mappings + items lists)."""
    data: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_items = False
    in_vars = False
    variables: dict[str, int] = {}
    includes: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("variables:"):
            in_vars = True
            in_items = False
            continue
        if in_vars and line.startswith("  ") and ":" in line:
            k, v = line.strip().split(":", 1)
            k = k.strip()
            v = v.split("#", 1)[0].strip()
            if k:
                variables[k] = int(v)
            continue
        if line.startswith("items:"):
            in_items = True
            in_vars = False
            continue
        if line.startswith("entries:"):
            in_items = False
            continue
        if line.startswith("- include:"):
            includes.append({"include": line.split(":", 1)[1].strip()})
            continue
        if line.startswith("- key:"):
            if current:
                items.append(current)
            current = {
                "key": line.split(":", 1)[1].strip(),
                "type": "float",
                "units": "",
                "description": "",
            }
            in_items = True
            continue
        if current is not None and line.startswith("  ") and ":" in line:
            k, v = line.strip().split(":", 1)
            val = v.strip()
            if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
                val = val[1:-1]
            current[k] = val
    if current:
        items.append(current)
    if variables:
        data["variables"] = variables
    if items:
        data["items"] = items
    if includes:
        data["entries"] = includes
    return data

# Original 10 Hz columns — keep names so existing flights/analysis still work.
LEGACY_COLUMNS = {
    "STRX_LAT": "fix_lat",
    "STRX_LONG": "fix_long",
    "STRX_PITCH": "fix_pitch",
    "STRX_ROLL": "fix_roll",
    "STRX_HEAD": "fix_head",
    "STRX_ALT": "fix_alt",
    "STRX_PALT": "fix_palt",
    "STRX_VS": "fix_vs",
    "STRX_ALAT": "fix_alat",
    "STRX_GS": "fix_gs",
    "STRX_TRACK": "fix_track",
}

FAST_FILES = {
    "stratux.yaml",
    "mgl_airtalk.yaml",
    "mgl_rdac.yaml",
    "mgl_nmea.yaml",
    "mgl_servo.yaml",
}

SKIP_KEYS = {"ZZLOADER"}
META_FIELDS = ("description", "min", "max", "initial", "tol", "aux")


def _check_var(key: str) -> str | None:
    for ch in key:
        if ch.islower():
            return ch
    return None


def _expand_entry(entry: dict[str, Any], var: str, count: int, variables: dict[str, int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(count):
        newentry = copy.deepcopy(entry)
        newentry["key"] = newentry["key"].replace(var, str(i + 1))
        desc = newentry.get("description") or ""
        newentry["description"] = desc.replace("%" + var, str(i + 1))
        ch = _check_var(newentry["key"])
        if ch:
            out.extend(_expand_entry(newentry, ch, variables[ch], variables))
        else:
            out.append(newentry)
    return out


def iter_fix_items(database_dir: Path) -> list[dict[str, Any]]:
    """Return expanded FIX items: key, type, units, description, source_file."""
    index = _load_yaml((database_dir / ".." / "database.yaml").resolve())
    variables: dict[str, int] = {}
    var_path = database_dir / "variables.yaml"
    if var_path.exists():
        raw = _load_yaml(var_path)
        variables = {str(k): int(v) for k, v in (raw.get("variables") or {}).items()}

    items: list[dict[str, Any]] = []
    for entry in index.get("entries") or []:
        inc = entry.get("include")
        if not inc:
            continue
        path = (database_dir / ".." / inc).resolve()
        data = _load_yaml(path)
        source = path.name
        for raw in data.get("items") or []:
            if not isinstance(raw, dict) or "key" not in raw:
                continue
            ch = _check_var(raw["key"])
            expanded = _expand_entry(raw, ch, variables[ch], variables) if ch else [raw]
            for item in expanded:
                key = item["key"]
                if key in SKIP_KEYS:
                    continue
                out = {
                    "key": key,
                    "type": str(item.get("type") or "float"),
                    "units": item.get("units") if item.get("units") is not None else "",
                    "description": item.get("description") or "",
                    "source_file": source,
                }
                for field in META_FIELDS:
                    if field == "description":
                        continue
                    if field in item and item[field] is not None:
                        out[field] = item[field]
                items.append(out)
    return items


RESERVED_COLUMNS = {
    "flight_id",
    "frame_number",
    "historian_time_utc",
    "flight_time_s",
}


def sqlite_type(fix_type: str) -> str:
    t = (fix_type or "float").lower()
    if t in ("str", "string"):
        return "TEXT"
    if t in ("int", "bool"):
        return "INTEGER"
    return "REAL"


def column_name(key: str) -> str:
    col = LEGACY_COLUMNS.get(key, key)
    if col.lower() in RESERVED_COLUMNS:
        return f"FIX_{key}"
    return col


def coerce_value(raw, spec: dict[str, Any]):
    """Coerce a NetFIX / raw string into the FIX type for SQLite storage."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s == "None":
        return None
    t = (spec.get("type") or "float").lower()
    if t in ("str", "string"):
        return s
    if t == "bool":
        low = s.lower()
        if low in ("1", "true", "t", "yes", "on"):
            return 1
        if low in ("0", "false", "f", "no", "off"):
            return 0
        try:
            return 1 if float(s) else 0
        except ValueError:
            return None
    if t in ("int", "integer"):
        try:
            return int(float(s))
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def rate_hz(item: dict[str, Any]) -> int:
    if sqlite_type(item["type"]) == "TEXT":
        return 1
    return 10 if item["source_file"] in FAST_FILES else 1


def signal_spec(item: dict[str, Any]) -> dict[str, Any]:
    spec = {
        "column": column_name(item["key"]),
        "units": item.get("units") if item.get("units") is not None else "",
        "type": item["type"],
        "rate_hz": rate_hz(item),
        "source": item["source_file"].replace(".yaml", ""),
        "description": item.get("description") or "",
    }
    for field in ("min", "max", "initial", "tol", "aux"):
        if field in item and item[field] is not None:
            spec[field] = item[field]
    return spec


def load_signals_from_historian_cfg(hist: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize historian.yaml signals (new mapping or legacy KEY: column)."""
    signals = hist.get("signals")
    if isinstance(signals, dict) and signals:
        out: dict[str, dict[str, Any]] = {}
        for key, spec in signals.items():
            if isinstance(spec, str):
                out[key] = {
                    "column": spec,
                    "units": "",
                    "type": "float",
                    "rate_hz": 10,
                    "source": "",
                }
            elif isinstance(spec, dict):
                out[key] = {
                    "column": spec.get("column") or column_name(key),
                    "units": spec.get("units") if spec.get("units") is not None else "",
                    "type": spec.get("type") or "float",
                    "rate_hz": int(spec.get("rate_hz") or 10),
                    "source": spec.get("source") or "",
                    "description": spec.get("description") or "",
                }
                for field in ("min", "max", "initial", "tol", "aux"):
                    if field in spec and spec[field] is not None:
                        out[key][field] = spec[field]
        return out
    out = {}
    for key, col in (hist.get("fast_signals") or {}).items():
        out[key] = {"column": col, "units": "", "type": "float", "rate_hz": 10, "source": ""}
    for key, col in (hist.get("slow_signals") or {}).items():
        out[key] = {"column": col, "units": "", "type": "float", "rate_hz": 1, "source": ""}
    return out


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        inner = ", ".join(
            v if isinstance(v, str) else _yaml_scalar(v) for v in value
        )
        return f"[{inner}]"
    s = str(value)
    if s == "" or any(c in s for c in ":#%{}[]&*?|>'\"\\") or s[:1] in "-?":
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def dump_historian_yaml(database_dir: Path) -> str:
    """Build historian.yaml text from the current FIX database."""
    header = """# Cozy Aircraft Historian — sampling configuration
#
# Every FIX-Gateway database key is listed under signals with the units
# stored in FIX (empty string if FIX has none), plus description and limits
# copied from the FIX item. Convert on ingest into FIX; Historian records
# those values unchanged.
#
# column: SQLite column on historian_10hz (rate_hz 10) or historian_1hz (rate_hz 1).
# Regenerated from config/fixgw/database/ via historian.database.fix_catalog.

historian:
  database_path: /cozy-data-system/data/historian/cozy_historian.sqlite
  aircraft_id: COZ
  fast_rate_hz: 10
  slow_rate_hz: 1
  commit_every_frames: 10
  sample_tolerance_s: 0.05
  control_socket: /cozy-data-system/data/historian/historian.sock

  fix:
    host: 127.0.0.1
    port: 3490

  signals:
"""
    lines = [header]
    for item in iter_fix_items(database_dir):
        spec = signal_spec(item)
        lines.append(f"    {item['key']}:\n")
        for field in (
            "column",
            "units",
            "type",
            "rate_hz",
            "source",
            "description",
            "min",
            "max",
            "initial",
            "tol",
            "aux",
        ):
            if field not in spec:
                continue
            if field in ("min", "max", "initial", "tol", "aux") and spec[field] is None:
                continue
            lines.append(f"      {field}: {_yaml_scalar(spec[field])}\n")
    return "".join(lines)
