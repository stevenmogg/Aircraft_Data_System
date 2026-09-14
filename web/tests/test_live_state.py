from web.app.websocket.live import LIVE_KEYS, build_state_message


class _Sample:
    def __init__(self, value):
        self.value = value


def test_live_state_includes_mgl_above_stratux_keys():
    for key in ("MGL_AT_PITCH", "MGL_AT_ROLL", "MGL_AT_HEAD"):
        assert key in LIVE_KEYS
    samples = {
        "PITCH": _Sample(1.5),
        "ROLL": _Sample(-2.0),
        "HEAD": _Sample(90.0),
        "PALT": _Sample(1200.0),
        "VS": _Sample(0.0),
        "GS": _Sample(0.0),
        "MGL_AT_PITCH": _Sample(3.5),
        "MGL_AT_ROLL": _Sample(-6.1),
        "MGL_AT_HEAD": _Sample(90.0),
        "MGL_AT_YAW": _Sample(350.5),
        "MGL_AT_SLIP": _Sample(26.0),
        "MGL_AT_G": _Sample(1.01),
        "MGL_RDAC_RPM1": _Sample(0),
        "MGL_RDAC_MAP_RAW": _Sample(1575),
        "MGL_RDAC_TEMP": _Sample(15.0),
        "MGL_RDAC_TC1": _Sample(-5.0),
    }
    msg = build_state_message(samples, {"state": "IDLE"})
    assert msg["mgl"]["pitch"] == 3.5
    assert msg["mgl"]["roll"] == -6.1
    assert msg["mgl"]["heading"] == 90.0
    assert msg["rdac"]["rpm1"] == 0
    assert msg["rdac"]["map_raw"] == 1575
    assert msg["rdac"]["temp"] == 15.0
    assert msg["rdac"]["tc1"] == -5.0
    assert msg["attitude"]["pitch"] == 1.5
    assert msg["attitude"]["roll"] == -2.0
    assert "MGL_RDAC_RPM1" in LIVE_KEYS
    assert "MGL_RDAC_TC12" in LIVE_KEYS
    assert "MGL_NMEA_LAT" in LIVE_KEYS
    samples["MGL_NMEA_LAT"] = _Sample(-37.816528)
    samples["MGL_NMEA_LONG"] = _Sample(144.976586)
    samples["MGL_NMEA_GS"] = _Sample(0.547)
    samples["LAT"] = _Sample(-37.81654)
    samples["LONG"] = _Sample(144.97688)
    samples["TRACK"] = _Sample(12.5)
    samples["ALT"] = _Sample(78.4)
    samples["GPS_SATS_TRACKED"] = _Sample(17)
    samples["GPS_FIX_TYPE"] = _Sample(2)
    msg = build_state_message(samples, {"state": "IDLE"})
    assert msg["nmea"]["lat"] == -37.816528
    assert msg["nmea"]["lon"] == 144.976586
    assert msg["nmea"]["groundspeed"] == 0.547
    assert msg["position"]["lat"] == -37.81654
    assert msg["position"]["lon"] == 144.97688
    assert msg["position"]["track"] == 12.5
    assert msg["position"]["gps_alt"] == 78.4
    assert msg["position"]["sats"] == 17
    assert msg["position"]["fix_type"] == 2
    assert "GPS_SATS_TRACKED" in LIVE_KEYS
