from web.app.services.airtalk_frames import (
    FrameAssembler,
    dest_label,
    parse_frame,
    payload_views,
    xor_cs,
)
from web.app.services.airtalk_monitor import FIX_AT_KEYS
from web.app.services.units import FT_PER_M, c_to_f, m_to_ft


def test_c_to_f_and_m_to_ft():
    assert c_to_f(0) == 32.0
    assert c_to_f(100) == 212.0
    assert abs(m_to_ft(1.0) - FT_PER_M) < 1e-12
    assert abs(m_to_ft(39.9) - 39.9 * FT_PER_M) < 1e-12


def test_fix_at_keys_include_turn_and_status():
    assert "MGL_AT_TURN" in FIX_AT_KEYS
    assert "MGL_AT_MISC" in FIX_AT_KEYS
    assert "MGL_AT_HEAD_STATUS" in FIX_AT_KEYS
    assert "MGL_AT_PITCH" in FIX_AT_KEYS



def test_broadcast_type32_from_live_bus():
    raw = bytes.fromhex("82 FF 04 32 3F 00 02 51 83")
    frame = parse_frame(raw)
    assert frame.ok
    assert frame.dest == 0xFF
    assert dest_label(frame.dest) == "broadcast"
    assert frame.msg_type == 0x32
    assert frame.data == bytes([0x3F, 0x00, 0x02])
    assert xor_cs(raw[1:-2]) == frame.checksum


def test_broadcast_type37_checksum():
    raw = bytes.fromhex(
        "82 FF 12 37 05 C3 FF 23 00 94 0D 1A 02 01 04 00 00 00 00 FF FF E1 83"
    )
    frame = parse_frame(raw)
    assert frame.ok
    assert frame.length == 0x12
    assert frame.msg_type == 0x37
    assert len(frame.data) == 0x12 - 1


def test_ahrs_dest_e6():
    raw = bytes.fromhex("82 E6 05 01 80 00 00 00 C7 83")
    frame = parse_frame(raw)
    assert frame.ok
    assert dest_label(frame.dest) == "SP-7 AHRS"
    assert frame.msg_type == 0x01


def test_bad_checksum():
    raw = bytes.fromhex("82 FF 04 32 3F 00 02 00 83")
    frame = parse_frame(raw)
    assert frame.status == "BADCS"


def test_assembler_reassembles_split_bytes():
    raw = bytes.fromhex("82 FF 04 32 3F 00 02 51 83")
    asm = FrameAssembler()
    assert asm.feed(raw[:3]) == []
    frames = asm.feed(raw[3:])
    assert len(frames) == 1
    assert frames[0].ok


def test_ff32_heading_le_degrees():
    from web.app.services.airtalk_frames import decode_fields

    fields = decode_fields(0xFF, 0x32, bytes([0x5A, 0x00, 0x02]))
    assert fields[0]["name"] == "Magnetic heading"
    assert fields[0]["value"] == 90
    assert fields[1]["value"] == 2


def test_ff37_euler10_level():
    from web.app.services.airtalk_frames import decode_fields

    # Live sitting-still capture: subtype 05, bank/pitch ~0.
    data = bytes.fromhex("05 FF FF FD FF B1 0D 00 04 01 04 00 00 00 00 FF FF")
    fields = {f["name"]: f["value"] for f in decode_fields(0xFF, 0x37, data)}
    assert fields["Bank"] == -0.1
    assert fields["Pitch"] == -0.3
    assert fields["Slip"] == 0
    assert fields["G"] == 1.02
    assert fields["MISC"] == 4


def test_ff37_euler10_moved():
    from web.app.services.airtalk_frames import decode_fields

    data = bytes.fromhex("05 C3 FF 23 00 94 0D 1A 02 01 04 00 00 00 00 FF FF")
    fields = {f["name"]: f["value"] for f in decode_fields(0xFF, 0x37, data)}
    assert fields["Bank"] == -6.1
    assert fields["Pitch"] == 3.5
    assert fields["Slip"] == 26
    assert fields["G"] == 1.01


def test_decode_fix_values_heading_and_euler():
    from web.app.services.airtalk_frames import decode_fix_values

    heading = decode_fix_values(0xFF, 0x32, bytes([0x5A, 0x00, 0x02]))
    assert heading == {"MGL_AT_HEAD": 90.0, "MGL_AT_HEAD_STATUS": 2.0}

    data = bytes.fromhex("05 C3 FF 23 00 94 0D 1A 02 01 04 00 00 00 00 FF FF")
    att = decode_fix_values(0xFF, 0x37, data)
    assert att["MGL_AT_ROLL"] == -6.1
    assert att["MGL_AT_PITCH"] == 3.5
    assert att["MGL_AT_SLIP"] == 26.0
    assert att["MGL_AT_G"] == 1.01
    assert "MGL_AT_HEAD" not in att
    assert all(not k.endswith("HEADING") for k in att)


def test_payload_i16le():
    views = payload_views(bytes([0x3F, 0x00, 0x02]))
    assert views["i16le"] == [0x003F]
    assert views["i16be"] == [0x3F00]
