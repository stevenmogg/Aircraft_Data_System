from pathlib import Path

from web.app.services.mgl_decode import extract_field, fields_to_fix, parse_id

ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = ROOT / "config" / "mgl_can" / "decode_map.yaml"
RDAC_YAML = ROOT / "config" / "fixgw" / "database" / "mgl_rdac.yaml"


def _keys_from_yaml(path: Path, marker: str) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        if marker not in line:
            continue
        part = line.split(marker, 1)[1].strip()
        keys.add(part.split()[0].rstrip(","))
    return keys


def test_decode_map_fix_keys_are_in_rdac_yaml():
    mapped = _keys_from_yaml(MAP_PATH, "fix_key:")
    defined = _keys_from_yaml(RDAC_YAML, "- key:")
    missing = mapped - defined
    assert not missing, missing
    assert "MGL_RDAC_RPM1" in mapped
    assert not any("." in k for k in mapped)


def test_rdac_id8_rpm_map_current():
    assert parse_id(0x208) == (32, 8)
    data = bytes([0xE8, 0x03, 0x00, 0x00, 0x2A, 0x01, 0x10, 0x00])
    fields = [
        {"fix_key": "MGL_RDAC_RPM1", "value": extract_field(data, {"type": "le_u16", "offset": 0})},
        {"fix_key": "MGL_RDAC_RPM2", "value": extract_field(data, {"type": "le_u16", "offset": 2})},
        {"fix_key": "MGL_RDAC_MAP_RAW", "value": extract_field(data, {"type": "le_u16", "offset": 4})},
        {"fix_key": "MGL_RDAC_CURRENT_RAW", "value": extract_field(data, {"type": "le_u16", "offset": 6})},
    ]
    values = fields_to_fix(fields)
    assert values["MGL_RDAC_RPM1"] == 1000
    assert values["MGL_RDAC_RPM2"] == 0
    assert values["MGL_RDAC_MAP_RAW"] == 0x012A
    assert values["MGL_RDAC_CURRENT_RAW"] == 0x0010


def test_rdac_id2_thermocouples():
    data = bytes([0x4C, 0x01, 0x4D, 0x01, 0x4E, 0x01, 0x4F, 0x01])
    fields = [
        {"fix_key": f"MGL_RDAC_TC{i}", "value": extract_field(data, {"type": "le_i16", "offset": (i - 1) * 2})}
        for i in range(1, 5)
    ]
    values = fields_to_fix(fields)
    assert values["MGL_RDAC_TC1"] == 332
    assert values["MGL_RDAC_TC4"] == 335


def test_rdac_compensator_adds_cj_and_stores_f():
    from web.app.services.mgl_decode import RdacCompensator
    from web.app.services.units import c_to_f

    c = RdacCompensator()
    pending = c.apply({"MGL_RDAC_TC1": 332, "MGL_RDAC_RPM1": 1000})
    assert "MGL_RDAC_TC1" not in pending
    assert pending["MGL_RDAC_RPM1"] == 1000

    with_cj = c.apply({"MGL_RDAC_TEMP": 15})
    assert with_cj["MGL_RDAC_TEMP"] == round(c_to_f(15), 2)
    assert with_cj["MGL_RDAC_TC1"] == round(c_to_f(332 + 15), 2)

    next_tc = c.apply({"MGL_RDAC_TC1": 340})
    assert next_tc["MGL_RDAC_TC1"] == round(c_to_f(340 + 15), 2)
