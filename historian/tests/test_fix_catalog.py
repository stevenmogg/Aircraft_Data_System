"""FIX database expansion and historian signal mapping."""

from __future__ import annotations

from pathlib import Path

from historian.database.fix_catalog import (
    coerce_value,
    iter_fix_items,
    load_signals_from_historian_cfg,
    signal_spec,
)

ROOT = Path(__file__).resolve().parents[2]
FIX_DB = ROOT / "config" / "fixgw" / "database"
HIST_YAML = ROOT / "config" / "historian" / "historian.yaml"


def test_catalog_covers_fix_db():
    items = iter_fix_items(FIX_DB)
    by_key = {i["key"]: i for i in items}
    assert "ZZLOADER" not in by_key
    assert "BTN1" not in by_key
    assert "OILP1" not in by_key
    assert "STRX_LAT" in by_key
    assert "STRX_PITCH" in by_key
    assert "LAT" not in by_key
    assert "PITCH" not in by_key
    assert "MGL_AT_PITCH" in by_key
    assert "MGL_RDAC_TEMP" in by_key
    assert "MGL_NMEA_ALT" in by_key
    assert by_key["STRX_LAT"]["source_file"] == "stratux.yaml"
    assert 100 < len(items) < 250

    lat = signal_spec(by_key["STRX_LAT"])
    assert lat["column"] == "fix_lat"
    assert lat["units"] == "deg"
    assert lat["rate_hz"] == 10
    assert lat["description"] == "Stratux GPS latitude"
    assert lat["min"] == -90.0
    assert lat["max"] == 90.0

    temp = signal_spec(by_key["MGL_RDAC_TEMP"])
    assert temp["units"] == "degF"
    assert temp["rate_hz"] == 10
    assert temp["min"] == -60.0
    assert temp["max"] == 320.0

    alt = signal_spec(by_key["MGL_NMEA_ALT"])
    assert alt["units"] == "ft"

    gga = signal_spec(by_key["MGL_NMEA_GGA_RAW"])
    assert gga["type"] == "str"
    assert gga["rate_hz"] == 1


def test_historian_yaml_lists_every_fix_key():
    import yaml

    hist = (yaml.safe_load(HIST_YAML.read_text()) or {}).get("historian") or {}
    signals = load_signals_from_historian_cfg(hist)
    items = iter_fix_items(FIX_DB)
    keys = {i["key"] for i in items}
    assert set(signals) == keys
    assert "BTN1" not in signals
    assert signals["STRX_PITCH"]["column"] == "fix_pitch"
    assert signals["STRX_PITCH"]["units"] == "deg"
    assert signals["STRX_PITCH"]["source"] == "stratux"
    assert signals["STRX_PITCH"]["description"] == "Stratux pitch angle"
    assert signals["STRX_PITCH"]["min"] == -90.0
    assert signals["STRX_PITCH"]["max"] == 90.0
    assert signals["MGL_RDAC_TEMP"]["units"] == "degF"
    assert signals["MGL_RDAC_TEMP"]["description"]
    assert signals["MGL_NMEA_ALT"]["units"] == "ft"
    assert signals["MGL_NMEA_GGA_RAW"]["rate_hz"] == 1


def test_coerce_value():
    assert coerce_value("12.5", {"type": "float"}) == 12.5
    assert coerce_value("True", {"type": "bool"}) == 1
    assert coerce_value("off", {"type": "bool"}) == 0
    assert coerce_value("3.9", {"type": "int"}) == 3
    assert coerce_value("GGA", {"type": "str"}) == "GGA"
    assert coerce_value("None", {"type": "float"}) is None
    assert coerce_value("", {"type": "float"}) is None
