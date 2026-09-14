#!/usr/bin/env python3
"""Convert an AvPlan GPX flight plan to MGL Extreme .ert route and WAYPOINT.EWD.

MGL Extreme stores routes and the user waypoint file as packed 48-byte Enigma
records (see GPSBabel ``enigma`` / MGL Enigma waypoint format):

    int32 latitude      degrees * 180000, little-endian
    int32 longitude     degrees * 180000, little-endian
    int32 extra         altitude_ft + 1000, or 0 / frequency for navaids
    uint8 type          in ERT/EWD: 0 = first record in the file, 1 = later
    uint8 shortname_len 1–6
    char  shortname[6]  ident; first shortname_len chars are the displayed name
    uint8 longname_len  0–27
    char  longname[27]  comment / description

``Navidata.ewd`` is the compiled MGL navigation database (header ``NAVIDATA``,
then 52-byte slots whose first 48 bytes are the same record). Official AvPlan
waypoints (MCTY, FWO, APL, …) must be **copied** from this file so the EFIS
keeps the 6-character database id (e.g. ``MCTYLP``) and published coordinates.
User waypoints (AvPlan type ``U``, or any ident not in the database) are
synthesised from the GPX lat/lon.

In a route file the Extreme overwrites the navidata type byte with 0 for the
first point and 1 for the rest; this converter does the same.

Examples::

    python3 navigation/avplan_to_mgl.py \\
        --gpx navigation/avplan \\
        --navidata navigation/SD_card/Navidata.ewd

    python3 navigation/avplan_to_mgl.py \\
        --card-sync --gpx /cozy-data-system/data/flight-plans \\
        --card-root /media/cozy-mgl --json-out /tmp/routes.json

    # MCG_FWO_1833.gpx → MCG_FWO0.ert (8.3 name, serial 0–9 then A–Z)
    # Home_APL_1824.gpx → HOME_AP0.ert
    # --card-sync deletes existing *.ert on the card first, then writes the current GPX set.
    # new user waypoints are appended to WAYPOINT.EWD; existing records are kept

    python3 navigation/avplan_to_mgl.py --dump navigation/SD_card/ROUTE000.ERT
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

RECORD_SIZE = 48
ENIGMA_SCALE = 180000
MAX_SHORT = 6
MAX_LONG = 27
MAX_NAV_TYPE = 26
# Ignore navidata hits further than this (degrees) from the AvPlan position.
MAX_LOOKUP_DEG = 1.0
ALTITUDE_BIAS = 1000  # stored extra = altitude_feet + 1000
ERT_NAME_LEN = 8
ERT_PREFIX_LEN = ERT_NAME_LEN - 1  # last character is the serial
ERT_SERIALS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def deg_to_enigma(val: float) -> int:
    """Match GPSBabel ``decToEnigmaPosition`` (truncate toward zero)."""
    sign = -1 if val < 0 else 1
    aval = abs(val)
    degrees = int(aval)
    frac = aval - degrees
    return sign * (degrees * ENIGMA_SCALE + int(ENIGMA_SCALE * frac))


def enigma_to_deg(val: int) -> float:
    return val / ENIGMA_SCALE


def sanitize_ident(name: str) -> str:
    chars = [c.upper() for c in name if c.isalnum()]
    ident = "".join(chars)[:MAX_SHORT]
    return ident or "WPT"


def ert_prefix_from_gpx(gpx_path: Path) -> str:
    """AvPlan ``MCG_FWO_1833.gpx`` → ``MCG_FWO`` (max 7 chars, uppercase).

    Drops a trailing ``_HHMM`` (or other ``_digits``) time suffix, then truncates
    so ``prefix + serial`` fits in an 8-character FAT name.
    """
    parts = gpx_path.stem.split("_")
    if len(parts) >= 2 and parts[-1].isdigit():
        parts = parts[:-1]
    prefix = "_".join(parts).upper()
    return prefix[:ERT_PREFIX_LEN]


def ert_name_from_gpx(gpx_path: Path, taken: set[str] | None = None) -> str:
    """8-character route name with a serial, e.g. ``MCG_FWO0.ert``."""
    return allocate_ert_name(gpx_path, taken if taken is not None else set())


def existing_ert_stems(directory: Path) -> set[str]:
    stems: set[str] = set()
    if not directory.is_dir():
        return stems
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() == ".ert":
            stems.add(path.stem.upper())
    return stems


def allocate_ert_name(gpx_path: Path, taken: set[str]) -> str:
    """Pick the next free ``PREFIX#`` name and add it to ``taken`` (uppercase stems)."""
    prefix = ert_prefix_from_gpx(gpx_path)
    for serial in ERT_SERIALS:
        stem = f"{prefix}{serial}"
        if stem.upper() in taken:
            continue
        taken.add(stem.upper())
        return f"{stem}.ert"
    raise RuntimeError(
        f"no free 8-character serial for prefix {prefix!r} (0-9, A-Z exhausted)"
    )


def list_gpx_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() != ".gpx":
            raise ValueError(f"not a GPX file: {path}")
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    return sorted(
        p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".gpx"
    )


def find_ci_file(directory: Path, *names: str) -> Path | None:
    """Find a file in ``directory`` by case-insensitive name."""
    if not directory.is_dir():
        return None
    want = {n.lower() for n in names}
    for candidate in directory.iterdir():
        if candidate.is_file() and candidate.name.lower() in want:
            return candidate
    return None


def delete_route_files(directory: Path, dry_run: bool = False) -> list[str]:
    """Remove every ``*.ert`` from ``directory``. Returns names removed."""
    removed: list[str] = []
    if not directory.is_dir():
        return removed
    for candidate in list(directory.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() == ".ert":
            removed.append(candidate.name)
            if not dry_run:
                candidate.unlink()
    return sorted(removed, key=str.lower)


@dataclass
class WaypointRecord:
    latitude_e: int
    longitude_e: int
    extra: int
    nav_type: int
    shortname: bytes  # 6 bytes, including database suffix
    shortname_len: int
    longname: bytes
    raw: bytes | None = None
    source: str = "synth"  # "navidata" or "synth"

    @property
    def ident(self) -> str:
        return self.shortname[: self.shortname_len].decode("latin1", "replace")

    @property
    def latitude(self) -> float:
        return enigma_to_deg(self.latitude_e)

    @property
    def longitude(self) -> float:
        return enigma_to_deg(self.longitude_e)

    @property
    def comment(self) -> str:
        return self.longname.decode("latin1", "replace")

    def pack(self, file_index: int) -> bytes:
        """Pack a 48-byte ERT/EWD record. ``file_index`` 0 → type 0, else 1."""
        flag = 0 if file_index == 0 else 1
        if self.raw is not None:
            buf = bytearray(self.raw)
            buf[12] = flag
            return bytes(buf)
        buf = bytearray(RECORD_SIZE)
        struct.pack_into("<iii", buf, 0, self.latitude_e, self.longitude_e, self.extra)
        buf[12] = flag
        buf[13] = self.shortname_len
        ident = self.shortname[:MAX_SHORT].ljust(MAX_SHORT, b"\x00")
        buf[14:20] = ident
        comment = self.longname[:MAX_LONG]
        buf[20] = len(comment)
        buf[21 : 21 + len(comment)] = comment
        return bytes(buf)


@dataclass
class AvPlanPoint:
    name: str
    lat: float
    lon: float
    ele_m: float | None
    desc: str
    avplan_type: str


def parse_record(data: bytes) -> WaypointRecord | None:
    """Parse one 48-byte Enigma record, or None if it looks like garbage."""
    if len(data) < RECORD_SIZE:
        return None
    nav_type = data[12]
    slen = data[13]
    llen = data[20]
    if nav_type > MAX_NAV_TYPE or not (1 <= slen <= MAX_SHORT) or llen > MAX_LONG:
        return None
    ident = bytes(data[14:20])
    short = ident[:slen]
    if not short or any(b < 33 or b > 126 for b in short):
        return None
    if any(b != 0 and (b < 32 or b > 126) for b in ident[slen:]):
        return None
    lat_e, lon_e, extra = struct.unpack_from("<iii", data)
    lat = enigma_to_deg(lat_e)
    lon = enigma_to_deg(lon_e)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    comment = bytes(data[21 : 21 + llen])
    if llen:
        printable = sum(32 <= b < 127 for b in comment)
        if printable < llen * 0.85:
            return None
    return WaypointRecord(
        latitude_e=lat_e,
        longitude_e=lon_e,
        extra=extra,
        nav_type=nav_type,
        shortname=ident,
        shortname_len=slen,
        longname=comment,
        raw=bytes(data[:RECORD_SIZE]),
        source="navidata",
    )


def iter_file_records(data: bytes) -> list[WaypointRecord]:
    recs: list[WaypointRecord] = []
    if len(data) % RECORD_SIZE != 0:
        return recs
    for off in range(0, len(data), RECORD_SIZE):
        rec = parse_record(data[off : off + RECORD_SIZE])
        if rec is None:
            break
        recs.append(rec)
    return recs


def format_record(rec: WaypointRecord, index: int | None = None) -> str:
    prefix = f"R{index} " if index is not None else ""
    return (
        f"{prefix}{rec.ident:6} type={rec.nav_type:2} extra={rec.extra:6} "
        f"lat={rec.latitude:11.6f} lon={rec.longitude:12.6f}  {rec.comment}"
    )


class NavidataIndex:
    """Lookup compiled MGL waypoints in Navidata.ewd by ident + position."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        if not self.data.startswith(b"NAVIDATA"):
            raise ValueError(f"{path} does not start with NAVIDATA header")

    def lookup(self, ident: str, lat: float, lon: float) -> WaypointRecord | None:
        needle = sanitize_ident(ident).encode("ascii")
        if not needle:
            return None
        hits: list[WaypointRecord] = []
        seen: set[int] = set()
        start = 0
        while True:
            pos = self.data.find(needle, start)
            if pos < 0:
                break
            rec_start = pos - 14
            start = pos + 1
            if rec_start < 0 or rec_start in seen:
                continue
            rec = parse_record(self.data[rec_start : rec_start + RECORD_SIZE])
            if rec is None:
                continue
            if rec.ident.upper() != needle.decode("ascii"):
                continue
            seen.add(rec_start)
            hits.append(rec)
        if not hits:
            return None

        def dist2(rec: WaypointRecord) -> float:
            return (rec.latitude - lat) ** 2 + (rec.longitude - lon) ** 2

        best = min(hits, key=dist2)
        if math.sqrt(dist2(best)) > MAX_LOOKUP_DEG:
            return None
        return best


def parse_avplan_gpx(path: Path) -> tuple[str, list[AvPlanPoint]]:
    tree = ET.parse(path)
    root = tree.getroot()
    rte = next((el for el in root.iter() if _local(el.tag) == "rte"), None)

    route_name = path.stem
    points: list[AvPlanPoint] = []
    if rte is not None:
        for child in rte:
            if _local(child.tag) == "name" and child.text:
                route_name = child.text.strip()
        for el in rte:
            if _local(el.tag) == "rtept":
                points.append(_gpx_point(el))
    if not points:
        for el in root:
            if _local(el.tag) == "wpt":
                points.append(_gpx_point(el))
    if not points:
        raise ValueError(f"{path} has no <rtept> or <wpt> points")
    return route_name, points


def _gpx_point(el: ET.Element) -> AvPlanPoint:
    lat = float(el.attrib["lat"])
    lon = float(el.attrib["lon"])
    name = ""
    desc = ""
    av_type = ""
    ele_m: float | None = None
    for child in el:
        tag = _local(child.tag)
        if tag == "name" and child.text:
            name = child.text.strip()
        elif tag == "desc" and child.text:
            desc = child.text.strip()
        elif tag == "type" and child.text:
            av_type = child.text.strip()
        elif tag == "ele" and child.text:
            try:
                ele_m = float(child.text)
            except ValueError:
                ele_m = None
        elif tag == "extensions":
            for ext in child.iter():
                et = _local(ext.tag)
                if et == "desc" and ext.text and not desc:
                    desc = ext.text.strip()
    return AvPlanPoint(
        name=name or "WPT",
        lat=lat,
        lon=lon,
        ele_m=ele_m,
        desc=desc or name or "WPT",
        avplan_type=av_type,
    )


def synthesize(point: AvPlanPoint) -> WaypointRecord:
    ident = sanitize_ident(point.name)
    comment = (point.desc or point.name)[:MAX_LONG].encode("ascii", "replace")
    extra = ALTITUDE_BIAS
    if point.ele_m:
        extra = int(round(point.ele_m * 3.28084)) + ALTITUDE_BIAS
    return WaypointRecord(
        latitude_e=deg_to_enigma(point.lat),
        longitude_e=deg_to_enigma(point.lon),
        extra=extra,
        nav_type=0,
        shortname=ident.encode("ascii").ljust(MAX_SHORT, b"\x00"),
        shortname_len=len(ident),
        longname=comment,
        raw=None,
        source="synth",
    )


def resolve_points(
    points: list[AvPlanPoint], navidata: NavidataIndex
) -> list[tuple[AvPlanPoint, WaypointRecord]]:
    resolved: list[tuple[AvPlanPoint, WaypointRecord]] = []
    for point in points:
        rec = None
        if point.avplan_type.upper() != "U":
            rec = navidata.lookup(point.name, point.lat, point.lon)
        if rec is None:
            rec = synthesize(point)
        resolved.append((point, rec))
    return resolved


def pack_records(records: list[WaypointRecord]) -> bytes:
    return b"".join(rec.pack(i) for i, rec in enumerate(records))


@dataclass
class Conversion:
    route_name: str
    ert: bytes
    ewd: bytes
    resolved: list[tuple[AvPlanPoint, WaypointRecord]] = field(default_factory=list)

    @property
    def user_count(self) -> int:
        return sum(1 for _, rec in self.resolved if rec.source == "synth")

    @property
    def db_count(self) -> int:
        return sum(1 for _, rec in self.resolved if rec.source == "navidata")


def convert(gpx_path: Path, navidata: NavidataIndex | Path) -> Conversion:
    if not isinstance(navidata, NavidataIndex):
        navidata = NavidataIndex(navidata)
    route_name, points = parse_avplan_gpx(gpx_path)
    resolved = resolve_points(points, navidata)
    ert = pack_records([rec for _, rec in resolved])
    user = [rec for _, rec in resolved if rec.source == "synth"]
    ewd = pack_records(user) if user else b""
    return Conversion(route_name=route_name, ert=ert, ewd=ewd, resolved=resolved)


def waypoint_key(rec: WaypointRecord) -> tuple[str, int, int]:
    return (rec.ident.upper(), rec.latitude_e, rec.longitude_e)


def load_ewd(path: Path) -> list[WaypointRecord]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    data = path.read_bytes()
    if len(data) % RECORD_SIZE != 0:
        raise ValueError(
            f"{path} length {len(data)} is not a multiple of {RECORD_SIZE}; refusing to merge"
        )
    recs = iter_file_records(data)
    if len(recs) * RECORD_SIZE != len(data):
        raise ValueError(f"{path} has unreadable records; refusing to merge")
    return recs


def merge_user_waypoints(
    existing: list[WaypointRecord], new: list[WaypointRecord]
) -> tuple[list[WaypointRecord], int]:
    """Append user waypoints that are not already present. Never removes records."""
    have = {waypoint_key(rec) for rec in existing}
    out = list(existing)
    added = 0
    for rec in new:
        key = waypoint_key(rec)
        if key in have:
            continue
        out.append(rec)
        have.add(key)
        added += 1
    return out, added


@dataclass
class BatchResult:
    conversions: list[tuple[Path, Path, Conversion]] = field(default_factory=list)
    ewd_path: Path | None = None
    ewd_added: int = 0
    ewd_total: int = 0
    navidata_path: Path | None = None
    routes_removed: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False


def convert_gpx_dir(
    gpx_path: Path,
    navidata_path: Path,
    out_dir: Path,
    ewd_path: Path,
    ert_name: str | None = None,
    replace_routes: bool = False,
    dry_run: bool = False,
) -> BatchResult:
    result = BatchResult(navidata_path=navidata_path, ewd_path=ewd_path, dry_run=dry_run)
    try:
        gpx_files = list_gpx_files(gpx_path) if gpx_path.exists() else []
    except ValueError as e:
        result.error = str(e)
        return result

    if not gpx_files and not replace_routes:
        result.error = f"no .gpx files in {gpx_path}"
        return result

    if replace_routes:
        result.routes_removed = delete_route_files(out_dir, dry_run=dry_run)

    navidata = NavidataIndex(navidata_path)
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    taken = existing_ert_stems(out_dir) if not replace_routes else set()
    existing_ewd = load_ewd(ewd_path)
    new_user: list[WaypointRecord] = []

    for gpx in gpx_files:
        try:
            conv = convert(gpx, navidata)
        except Exception as e:
            result.errors.append({"gpx": gpx.name, "error": str(e)})
            continue
        if ert_name and len(gpx_files) == 1:
            name = ert_name
            taken.add(Path(name).stem.upper())
        else:
            name = allocate_ert_name(gpx, taken)
        ert_file = out_dir / name
        if not dry_run:
            ert_file.write_bytes(conv.ert)
        result.conversions.append((gpx, ert_file, conv))
        new_user.extend(rec for _, rec in conv.resolved if rec.source == "synth")

    merged, added = merge_user_waypoints(existing_ewd, new_user)
    result.ewd_added = added
    result.ewd_total = len(merged)
    if added and not dry_run:
        ewd_path.parent.mkdir(parents=True, exist_ok=True)
        ewd_path.write_bytes(pack_records(merged))
    return result


def batch_report(result: BatchResult) -> dict:
    routes = []
    for gpx, ert_file, conv in result.conversions:
        routes.append(
            {
                "gpx": gpx.name,
                "ert": ert_file.name,
                "on_card": str(ert_file),
                "db_waypoints": [
                    point.name for point, rec in conv.resolved if rec.source == "navidata"
                ],
                "user_waypoints": [
                    point.name for point, rec in conv.resolved if rec.source == "synth"
                ],
            }
        )
    ok = result.error is None and not result.errors
    return {
        "ok": ok,
        "dry_run": result.dry_run,
        "navidata": str(result.navidata_path) if result.navidata_path else None,
        "ewd": str(result.ewd_path) if result.ewd_path else None,
        "ewd_added": result.ewd_added,
        "ewd_total": result.ewd_total,
        "routes_removed": result.routes_removed,
        "routes": routes,
        "gpx_count": len(result.conversions),
        "errors": result.errors,
        "error": result.error,
    }


def sync_card(
    gpx_dir: Path,
    card_root: Path,
    dry_run: bool = False,
) -> dict:
    """Replace card ``*.ert`` with conversions of every GPX; merge user waypoints."""
    navidata = find_ci_file(card_root, "Navidata.ewd", "navidata.ewd")
    ewd = find_ci_file(card_root, "WAYPOINT.EWD", "waypoint.ewd")
    if ewd is None:
        ewd = card_root / "WAYPOINT.EWD"
    if navidata is None:
        return {
            "ok": False,
            "error": f"Navidata.ewd not found on card ({card_root})",
            "dry_run": dry_run,
            "navidata": None,
            "ewd": str(ewd),
            "ewd_added": 0,
            "ewd_total": 0,
            "routes_removed": [],
            "routes": [],
            "gpx_count": 0,
            "errors": [],
        }
    result = convert_gpx_dir(
        gpx_dir,
        navidata,
        card_root,
        ewd,
        replace_routes=True,
        dry_run=dry_run,
    )
    return batch_report(result)


def dump_path(path: Path) -> None:
    data = path.read_bytes()
    if data.startswith(b"NAVIDATA"):
        print(f"{path}: Navidata database, {len(data)} bytes")
        print("Use --gpx with this file as --navidata; not a route dump.")
        return
    recs = iter_file_records(data)
    print(f"{path}: {len(data)} bytes, {len(recs)} record(s)")
    for i, rec in enumerate(recs):
        print(" ", format_record(rec, i))


def _report_batch(result: BatchResult) -> None:
    for name in result.routes_removed:
        print(f"removed route {name}")
    for gpx, ert_file, conv in result.conversions:
        print(
            f"wrote {ert_file.name} from {gpx.name} "
            f"({len(conv.ert)} bytes, {len(conv.resolved)} waypoints)"
        )
        for i, (point, rec) in enumerate(conv.resolved):
            origin = "navidata" if rec.source == "navidata" else "user"
            packed = parse_record(rec.pack(i)) or rec
            print(f"  {point.name:6} {origin:9} → {format_record(packed, i)}")
    ewd_path = result.ewd_path
    if ewd_path is None:
        return
    if result.ewd_added:
        print(
            f"appended {result.ewd_added} user waypoint(s) to {ewd_path} "
            f"({result.ewd_total} total)"
        )
    elif ewd_path.is_file():
        print(f"no new user waypoints — left {ewd_path} unchanged")
    else:
        print("no user waypoints — WAYPOINT.EWD not written")


def _write_json(path: Path | None, payload: dict) -> None:
    text = json.dumps(payload, indent=2)
    if path is None:
        return
    path.write_text(text + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert AvPlan GPX folder to MGL Extreme 8.3 ERT routes + merged EWD"
    )
    parser.add_argument(
        "--gpx",
        type=Path,
        help="AvPlan GPX file, or a folder containing one or more .gpx files",
    )
    parser.add_argument(
        "--navidata",
        type=Path,
        help="MGL Navidata.ewd from the Extreme SD card (required unless --card-sync)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="directory for .ert files (default: the GPX folder)",
    )
    parser.add_argument(
        "--ert-name",
        default=None,
        help="override route filename (single GPX only; default is PREFIX# 8.3 name)",
    )
    parser.add_argument(
        "--ewd",
        type=Path,
        default=None,
        help="WAYPOINT.EWD to merge into (default: next to Navidata.ewd)",
    )
    parser.add_argument(
        "--card-sync",
        action="store_true",
        help="replace all *.ert on --card-root with conversions of --gpx; merge WAYPOINT.EWD",
    )
    parser.add_argument(
        "--card-root",
        type=Path,
        default=None,
        help="mounted MGL card root (with --card-sync)",
    )
    parser.add_argument(
        "--replace-routes",
        action="store_true",
        help="delete existing *.ert in the output directory before writing new ones",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="write a JSON report (for mgl_card_sync / the web UI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report actions without writing or deleting files",
    )
    parser.add_argument(
        "--dump",
        type=Path,
        metavar="FILE",
        help="print records from an existing .ERT / .EWD and exit",
    )
    args = parser.parse_args(argv)

    if args.dump:
        dump_path(args.dump)
        return 0

    if args.card_sync:
        if not args.gpx or not args.card_root:
            parser.error("--card-sync requires --gpx and --card-root")
        report = sync_card(args.gpx, args.card_root, dry_run=args.dry_run)
        _write_json(args.json_out, report)
        if report.get("error"):
            print(report["error"], file=sys.stderr)
            return 1
        # Human-readable summary from the report
        for removed in report.get("routes_removed") or []:
            print(f"removed route {removed}")
        for route in report.get("routes") or []:
            print(f"wrote {route['ert']} from {route['gpx']}")
            for ident in route.get("db_waypoints") or []:
                print(f"  {ident} navidata")
            for ident in route.get("user_waypoints") or []:
                print(f"  {ident} user")
        if report.get("ewd_added"):
            print(
                f"appended {report['ewd_added']} user waypoint(s) to {report.get('ewd')} "
                f"({report.get('ewd_total')} total)"
            )
        elif report.get("ewd"):
            print(f"no new user waypoints — left {report['ewd']} unchanged")
        return 0 if report.get("ok") else 1

    if not args.gpx or not args.navidata:
        parser.error("--gpx and --navidata are required (or pass --card-sync / --dump)")
    gpx_path = args.gpx
    out_dir = args.out_dir if args.out_dir is not None else (
        gpx_path if gpx_path.is_dir() else gpx_path.parent
    )
    ewd_path = args.ewd if args.ewd is not None else args.navidata.parent / "WAYPOINT.EWD"
    result = convert_gpx_dir(
        gpx_path,
        args.navidata,
        out_dir,
        ewd_path,
        ert_name=args.ert_name,
        replace_routes=args.replace_routes,
        dry_run=args.dry_run,
    )
    report = batch_report(result)
    _write_json(args.json_out, report)
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    _report_batch(result)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
