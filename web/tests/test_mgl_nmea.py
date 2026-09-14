from pathlib import Path

from web.app.services.mgl_nmea import parse_line, xor_checksum

ROOT = Path(__file__).resolve().parents[2]
NMEA_YAML = ROOT / "config" / "fixgw" / "database" / "mgl_nmea.yaml"

GGA = "$GPGGA,082242.75,3748.99168,S,14458.59516,E,2,07,1.10,39.9,M,-1.8,M,,*6B"
RMC = "$GPRMC,082242.75,A,3748.99168,S,14458.59516,E,0.547,310.39,130926,,,D*7E"


def _nmea(body: str) -> str:
    return f"${body}*{xor_checksum(body):02X}"


def _yaml_keys() -> set[str]:
    keys: set[str] = set()
    for line in NMEA_YAML.read_text().splitlines():
        if line.startswith("- key:"):
            keys.add(line.split(":", 1)[1].strip())
    return keys


def test_live_gga_fields():
    v = parse_line(GGA)
    assert v["MGL_NMEA_CSUM_OK"] is True
    assert v["MGL_NMEA_TALKER"] == "GP"
    assert v["MGL_NMEA_TYPE"] == "GGA"
    assert v["MGL_NMEA_GGA_RAW"] == GGA
    assert "MGL_NMEA_RMC_RAW" not in v
    assert v["MGL_NMEA_TIME"] == "082242.75"
    assert v["MGL_NMEA_LAT_RAW"] == "3748.99168"
    assert v["MGL_NMEA_NS"] == "S"
    assert v["MGL_NMEA_LONG_RAW"] == "14458.59516"
    assert v["MGL_NMEA_EW"] == "E"
    assert abs(v["MGL_NMEA_LAT"] - (-(37 + 48.99168 / 60.0))) < 1e-9
    assert abs(v["MGL_NMEA_LONG"] - (144 + 58.59516 / 60.0)) < 1e-9
    assert v["MGL_NMEA_QUAL"] == 2
    assert v["MGL_NMEA_VALID"] is True
    assert v["MGL_NMEA_SATS"] == 7
    assert v["MGL_NMEA_HDOP"] == 1.10
    assert v["MGL_NMEA_ALT"] == round(39.9 * 3.280839895, 2)
    assert v["MGL_NMEA_ALT_UNIT"] == "ft"
    assert v["MGL_NMEA_GEOID"] == round(-1.8 * 3.280839895, 2)
    assert v["MGL_NMEA_GEOID_UNIT"] == "ft"
    assert "MGL_NMEA_DGPS_AGE" not in v
    assert "LAT" not in v
    assert "LONG" not in v


def test_live_rmc_fields():
    v = parse_line(RMC)
    assert v["MGL_NMEA_CSUM_OK"] is True
    assert v["MGL_NMEA_RMC_RAW"] == RMC
    assert "MGL_NMEA_GGA_RAW" not in v
    assert v["MGL_NMEA_STATUS"] == "A"
    assert v["MGL_NMEA_VALID"] is True
    assert v["MGL_NMEA_GS"] == 0.547
    assert v["MGL_NMEA_TRACK"] == 310.39
    assert v["MGL_NMEA_DATE"] == "130926"
    assert v["MGL_NMEA_MODE"] == "D"
    assert "MGL_NMEA_MAGVAR" not in v


def test_gga_feet_not_double_converted():
    line = _nmea("GPGGA,082242.75,3748.99168,S,14458.59516,E,2,07,1.10,131.0,F,-6.0,F,,")
    v = parse_line(line)
    assert v["MGL_NMEA_ALT"] == 131.0
    assert v["MGL_NMEA_ALT_UNIT"] == "ft"
    assert v["MGL_NMEA_GEOID"] == -6.0
    assert v["MGL_NMEA_GEOID_UNIT"] == "ft"


def test_junk_prefix_still_parses():
    v = parse_line("PK\xa6\x13" + GGA)
    assert v["MGL_NMEA_TYPE"] == "GGA"
    assert v["MGL_NMEA_QUAL"] == 2


def test_bad_checksum_does_not_store_position():
    v = parse_line(GGA[:-2] + "00")
    assert v["MGL_NMEA_CSUM_OK"] is False
    assert "MGL_NMEA_LAT" not in v
    assert v["MGL_NMEA_RAW"].startswith("$GPGGA")


def test_gsa_vtg():
    gsa = _nmea("GPGSA,A,3,04,05,09,12,24,,,,,,,,2.5,1.3,2.1")
    vtg = _nmea("GPVTG,310.39,T,298.1,M,0.547,N,1.013,K,D")
    gsa_v = parse_line(gsa)
    assert gsa_v["MGL_NMEA_GSA_FIX"] == 3
    assert gsa_v["MGL_NMEA_SATS_USED"] == "04,05,09,12,24"
    assert gsa_v["MGL_NMEA_PDOP"] == 2.5
    assert gsa_v["MGL_NMEA_HDOP"] == 1.3
    assert gsa_v["MGL_NMEA_VDOP"] == 2.1
    vtg_v = parse_line(vtg)
    assert vtg_v["MGL_NMEA_TRACK"] == 310.39
    assert vtg_v["MGL_NMEA_TRACK_MAG"] == 298.1
    assert vtg_v["MGL_NMEA_GS"] == 0.547
    assert vtg_v["MGL_NMEA_GS_KMH"] == 1.013
    assert vtg_v["MGL_NMEA_MODE"] == "D"


def test_parser_keys_are_in_database_yaml():
    defined = _yaml_keys()
    seen: set[str] = set()
    for line in (GGA, RMC, _nmea("GPGSA,A,3,04,,,,,,,,,,,,2.5,1.3,2.1"),
                 _nmea("GPVTG,1,T,2,M,3,N,4,K,A"),
                 _nmea("GPGLL,3748.99,S,14458.59,E,082242.75,A,D"),
                 _nmea("GPGSV,2,1,07,04,45,123,40")):
        seen.update(parse_line(line))
    missing = seen - defined
    assert not missing, missing
    assert "MGL_NMEA_LAT" in defined
    assert "MGL_NMEA_GGA_RAW" in defined
    assert "MGL_NMEA_RMC_RAW" in defined


def test_display_fields_split_gga_rmc():
    from web.app.services.mgl_nmea import display_fields

    gga_names = [r["name"] for r in display_fields(parse_line(GGA), "GGA")]
    rmc_names = [r["name"] for r in display_fields(parse_line(RMC), "RMC")]
    assert "Quality" in gga_names
    assert "Alt MSL" in gga_names
    assert "Ground speed" not in gga_names
    assert "Ground speed" in rmc_names
    assert "Track true" in rmc_names
    assert "Quality" not in rmc_names


def test_nmea_monitor_splits_traffic():
    from web.app.services.nmea_monitor import NmeaMonitor

    mon = NmeaMonitor()
    mon.apply_raws(GGA, RMC, now=1000.0)
    mon.apply_raws(GGA, RMC, now=1001.0)
    body = "GPGGA,082243.75,3748.99168,S,14458.59516,E,2,07,1.10,39.9,M,-1.8,M,,"
    gga2 = _nmea(body)
    mon.apply_raws(gga2, RMC, now=1002.0)
    snap = mon.snapshot()
    assert snap["gga"]["count"] == 2
    assert snap["rmc"]["count"] == 1
    assert snap["gga"]["raw"] == gga2
    assert snap["rmc"]["raw"] == RMC
    assert any(x["name"] == "Quality" for x in snap["gga"]["fields"])
    assert any(x["name"] == "Ground speed" for x in snap["rmc"]["fields"])
    assert len(snap["gga"]["recent"]) == 2
    assert len(snap["rmc"]["recent"]) == 1
