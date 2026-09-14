"""AvPlan GPX → MGL Extreme ERT/EWD, checked against the sample SD card dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from navigation.avplan_to_mgl import (
    RECORD_SIZE,
    NavidataIndex,
    convert,
    convert_gpx_dir,
    deg_to_enigma,
    ert_name_from_gpx,
    ert_prefix_from_gpx,
    iter_file_records,
    load_ewd,
    parse_avplan_gpx,
    parse_record,
    sanitize_ident,
    sync_card,
)

NAV = Path(__file__).resolve().parents[1]
SD = NAV / "SD_card"
GPX_HOME = NAV / "avplan" / "Home_APL_1824.gpx"
GPX_MCG = NAV / "avplan" / "MCG_FWO_1833.gpx"
NAVIDATA = SD / "Navidata.ewd"
SAMPLE_ERT = SD / "ROUTE000.ERT"
SAMPLE_EWD = SD / "WAYPOINT.EWD"

pytestmark = pytest.mark.skipif(
    not NAVIDATA.is_file() or not SAMPLE_ERT.is_file(),
    reason="navigation/SD_card samples not present",
)


def test_ert_8_3_serial_names():
    assert ert_prefix_from_gpx(Path("MCG_FWO_1833.gpx")) == "MCG_FWO"
    assert ert_prefix_from_gpx(Path("Home_APL_1824.gpx")) == "HOME_AP"
    taken: set[str] = set()
    assert ert_name_from_gpx(Path("MCG_FWO_1833.gpx"), taken) == "MCG_FWO0.ert"
    assert ert_name_from_gpx(Path("MCG_FWO_1900.gpx"), taken) == "MCG_FWO1.ert"
    taken.add("HOME_AP0")
    assert ert_name_from_gpx(GPX_HOME, taken) == "HOME_AP1.ert"
    assert len(Path("MCG_FWO0.ert").stem) == 8


def test_sanitize_and_enigma():
    assert sanitize_ident("Home") == "HOME"
    assert sanitize_ident("FWO") == "FWO"
    # GPSBabel truncation: -37.816959 * 180000 = -6807052.62 → -6807052
    assert deg_to_enigma(-37.816959) == -6807052
    assert deg_to_enigma(144.977336) == 26095920


def test_sample_ert_records():
    recs = iter_file_records(SAMPLE_ERT.read_bytes())
    assert len(recs) == 4
    assert recs[0].ident == "WPT!"
    assert recs[0].comment == "WAYPOINT"
    assert recs[1].ident == "MCTY"
    assert recs[2].ident == "FWO"
    assert recs[3].ident == "APL"


def test_navidata_lookup_matches_sample_route_legs():
    nav = NavidataIndex(NAVIDATA)
    sample = SAMPLE_ERT.read_bytes()
    expected = {
        "MCTY": (-37.808333, 144.958333, sample[RECORD_SIZE : 2 * RECORD_SIZE]),
        "FWO": (-37.795278, 144.993889, sample[2 * RECORD_SIZE : 3 * RECORD_SIZE]),
        "APL": (-37.855556, 144.975000, sample[3 * RECORD_SIZE : 4 * RECORD_SIZE]),
    }
    for ident, (lat, lon, ert_bytes) in expected.items():
        rec = nav.lookup(ident, lat, lon)
        assert rec is not None, ident
        packed = rec.pack(file_index=1)
        assert packed == ert_bytes, ident


def test_home_apl_conversion(tmp_path: Path):
    conv = convert(GPX_HOME, NAVIDATA)
    assert conv.db_count == 3
    assert conv.user_count == 1
    assert len(conv.ert) == 4 * RECORD_SIZE

    sample = SAMPLE_ERT.read_bytes()
    assert conv.ert[RECORD_SIZE:] == sample[RECORD_SIZE:]

    home = parse_record(conv.ert[:RECORD_SIZE])
    assert home is not None
    assert home.ident == "HOME"
    assert home.nav_type == 0
    assert home.latitude == pytest.approx(-37.816959, abs=1e-5)
    assert home.longitude == pytest.approx(144.977336, abs=1e-5)

    ewd = iter_file_records(conv.ewd)
    assert len(ewd) == 1
    assert ewd[0].ident == "HOME"

    out = tmp_path / "out"
    out.mkdir()
    (out / "ROUTE000.ERT").write_bytes(conv.ert)
    (out / "WAYPOINT.EWD").write_bytes(conv.ewd)
    assert (out / "ROUTE000.ERT").stat().st_size == 192


def test_mcg_fwo_all_from_navidata():
    conv = convert(GPX_MCG, NAVIDATA)
    assert conv.user_count == 0
    assert conv.db_count == 4
    assert conv.ewd == b""
    recs = iter_file_records(conv.ert)
    assert [r.ident for r in recs] == ["MCG", "WES", "MVC", "FWO"]
    assert recs[0].nav_type == 0
    assert all(r.nav_type == 1 for r in recs[1:])
    assert recs[3].comment.startswith("FREEWAY OVERPASS")


def test_gpx_route_order():
    name, points = parse_avplan_gpx(GPX_HOME)
    assert name == "Home to APL"
    assert [p.name for p in points] == ["Home", "MCTY", "FWO", "APL"]
    assert points[0].avplan_type == "U"


def test_wes_not_confused_with_westy():
    nav = NavidataIndex(NAVIDATA)
    rec = nav.lookup("WES", -37.829722, 144.896389)
    assert rec is not None
    assert rec.ident == "WES"
    assert "WESTGATE" in rec.comment


def test_batch_folder_keeps_existing_waypoints(tmp_path: Path):
    ewd = tmp_path / "WAYPOINT.EWD"
    ewd.write_bytes(SAMPLE_EWD.read_bytes())
    result = convert_gpx_dir(NAV / "avplan", NAVIDATA, tmp_path, ewd)
    names = sorted(p.name for p in tmp_path.glob("*.ert"))
    assert names == ["HOME_AP0.ert", "MCG_FWO0.ert"]
    assert all(len(Path(n).stem) == 8 for n in names)
    assert result.ewd_added == 1
    recs = load_ewd(ewd)
    assert [r.ident for r in recs] == ["WPT!", "WPT~", "HOME"]

    result2 = convert_gpx_dir(NAV / "avplan", NAVIDATA, tmp_path, ewd)
    names2 = sorted(p.name for p in tmp_path.glob("*.ert"))
    assert names2 == ["HOME_AP0.ert", "HOME_AP1.ert", "MCG_FWO0.ert", "MCG_FWO1.ert"]
    assert result2.ewd_added == 0
    recs2 = load_ewd(ewd)
    assert [r.ident for r in recs2] == ["WPT!", "WPT~", "HOME"]


def test_replace_routes_clears_old_erts(tmp_path: Path):
    ewd = tmp_path / "WAYPOINT.EWD"
    ewd.write_bytes(SAMPLE_EWD.read_bytes())
    (tmp_path / "ROUTE000.ERT").write_bytes(SAMPLE_ERT.read_bytes())
    (tmp_path / "MCG_FWO9.ert").write_bytes(b"\x00" * RECORD_SIZE)
    result = convert_gpx_dir(
        NAV / "avplan", NAVIDATA, tmp_path, ewd, replace_routes=True
    )
    names = sorted(p.name for p in tmp_path.glob("*.ert"))
    assert names == ["HOME_AP0.ert", "MCG_FWO0.ert"]
    assert "ROUTE000.ERT" in result.routes_removed
    assert not (tmp_path / "ROUTE000.ERT").exists()
    recs = load_ewd(ewd)
    assert recs[0].ident == "WPT!"
    assert recs[-1].ident == "HOME"


def test_sync_card_report(tmp_path: Path):
    card = tmp_path / "card"
    plans = tmp_path / "plans"
    card.mkdir()
    plans.mkdir()
    (card / "Navidata.ewd").symlink_to(NAVIDATA)
    (card / "WAYPOINT.EWD").write_bytes(SAMPLE_EWD.read_bytes())
    (card / "ROUTE000.ERT").write_bytes(SAMPLE_ERT.read_bytes())
    (plans / "MCG_FWO_1833.gpx").symlink_to(GPX_MCG)
    (plans / "Home_APL_1824.gpx").symlink_to(GPX_HOME)
    report = sync_card(plans, card)
    assert report["ok"] is True
    assert "ROUTE000.ERT" in report["routes_removed"]
    by_gpx = {row["gpx"]: row["ert"] for row in report["routes"]}
    assert by_gpx["MCG_FWO_1833.gpx"] == "MCG_FWO0.ert"
    assert by_gpx["Home_APL_1824.gpx"] == "HOME_AP0.ert"
    assert (card / "MCG_FWO0.ert").is_file()
    assert not (card / "ROUTE000.ERT").exists()
    assert report["ewd_added"] == 1
    assert [r.ident for r in load_ewd(card / "WAYPOINT.EWD")] == ["WPT!", "WPT~", "HOME"]
