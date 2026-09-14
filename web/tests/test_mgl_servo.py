from web.app.services.mgl_servo.emulator import (
    STATE_ACTIVE,
    STATE_IDENTIFIED,
    STATE_IDENTIFIED_IDLE,
    ServoEmulator,
)
from web.app.services.mgl_servo.interlock import TxInterlock, tx_allowed
from web.app.services.mgl_servo.protocol import (
    ARDUINO_IDLE_POSITION,
    ARDUINO_TORQUE_BYTE,
    ARDUINO_VOLTAGE_BYTE,
    IDENTIFY_ID,
    POSITION_ID,
    circular_error,
    decode_identify,
    decode_position,
    encode_identify,
    encode_position,
    encode_reply,
    reply_id,
    s12_to_u12,
    u12_to_s12,
    voltage_byte,
)

ARMED = {
    "enabled": True,
    "allow_tx": True,
    "tx_armed": True,
    "command_timeout_ms": 300,
    "unsolicited_interval_ms": 100,
    "engage_bit": 0,
    "servos": {
        "roll": {
            "enabled": True,
            "expected_number": 1,
            "servo_number": 1,
            "mode": "echo",
        },
        "pitch": {
            "enabled": True,
            "expected_number": 2,
            "servo_number": 2,
            "mode": "echo",
        },
    },
}


def _emu(**overrides) -> ServoEmulator:
    cfg = {**ARMED, **overrides}
    if "servos" in overrides:
        cfg["servos"] = overrides["servos"]
    emu = ServoEmulator.from_mapping(cfg)
    emu.cfg.interface_ok = True
    return emu


def test_t0_default_is_passive():
    emu = ServoEmulator.from_mapping({})
    assert emu.cfg.allow_tx is False
    assert emu.cfg.tx_armed is False
    assert emu.cfg.enabled is False
    lock = TxInterlock()
    assert tx_allowed(lock) is False
    reply = emu.handle_rx(IDENTIFY_ID, encode_identify(1), 1.0)
    assert reply is None


def test_t0_two_identify_armed_rejected():
    bad = {
        "enabled": True,
        "servos": {
            "roll": {"enabled": True, "identify_armed": True},
            "pitch": {"enabled": True, "identify_armed": True},
        },
    }
    try:
        ServoEmulator.from_mapping(bad)
    except ValueError as e:
        assert "identify_armed" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_t1_circular_error():
    cases = [
        (200, 100, 100),
        (100, 200, -100),
        (10, 4090, 16),
        (4090, 10, -16),
        (4095, 0, -1),
        (0, 4095, 1),
        # Antipode (2048) is ambiguous; the spec formula returns -2048 either way.
        (2048, 0, -2048),
        (0, 2048, -2048),
    ]
    for target, current, expect in cases:
        got = circular_error(target, current)
        assert got == expect, (target, current, got, expect)


def test_t2_identify_decoder():
    ok = decode_identify(IDENTIFY_ID, bytes([0xAA, 0x55, 0x01, 0xFE]))
    assert ok is not None and ok.servo_number == 1
    live = decode_identify(IDENTIFY_ID, bytes([0xAA, 0x55, 0x01, 0xFE, 0, 0, 0, 0]))
    assert live is not None and live.servo_number == 1
    assert decode_identify(IDENTIFY_ID, bytes([0xAA, 0x55, 0x01, 0xFF])) is None
    assert decode_identify(IDENTIFY_ID, bytes([0xAB, 0x55, 0x01, 0xFE])) is None
    assert decode_identify(IDENTIFY_ID, bytes([0xAA, 0x54, 0x01, 0xFE])) is None
    assert decode_identify(IDENTIFY_ID, bytes([0xAA, 0x55, 0x01])) is None
    assert decode_identify(IDENTIFY_ID, bytes([0xAA, 0x55, 0x01, 0xFE]), extended=True) is None
    assert decode_identify(0x011, bytes([0xAA, 0x55, 0x01, 0xFE])) is None


def test_s12_twos_complement():
    assert u12_to_s12(0) == 0
    assert u12_to_s12(1) == 1
    assert u12_to_s12(2047) == 2047
    assert u12_to_s12(2048) == -2048
    assert u12_to_s12(4095) == -1
    assert u12_to_s12(4096) == 0
    assert s12_to_u12(-1) == 4095
    assert s12_to_u12(-2) == 4094
    cmd = decode_position(POSITION_ID, encode_position(1, -1, 0x01))
    assert cmd is not None and cmd.target == -1
    wide = decode_position(POSITION_ID, bytes([0x01, 0x01, 0xFF, 0xFF]))
    assert wide is not None and wide.target == -1
    reply = encode_reply(1, position=-1, engaged=False, voltage_v=13.8, torque=0)
    assert reply.data[1] | (reply.data[2] << 8) == 4095


def test_xtreme_dlc8_position():
    cmd = decode_position(POSITION_ID, bytes([0x02, 0x40, 0x00, 0x00, 0, 0, 0, 0]))
    assert cmd is not None
    assert cmd.servo_number == 2
    assert cmd.options == 0x40
    assert cmd.target == 0


def test_t3_ready_without_identify():
    emu = _emu()
    roll = emu.servo_by_role("roll")
    pitch = emu.servo_by_role("pitch")
    assert roll.servo_number == 1
    assert pitch.servo_number == 2
    assert roll.state == STATE_IDENTIFIED
    assert pitch.state == STATE_IDENTIFIED
    assert roll.reply_can_id() == 0x101
    assert pitch.reply_can_id() == 0x111
    assert emu.handle_rx(IDENTIFY_ID, encode_identify(1), 1.0) is None
    assert emu.last_identify_num == 1
    assert emu.last_identify_accepted is False
    assert roll.servo_number == 1


def test_t4_position_decoder_and_routing():
    cmd = decode_position(POSITION_ID, encode_position(1, 0x0567, 0x01))
    assert cmd is not None
    assert cmd.servo_number == 1
    assert cmd.target == 0x0567
    assert cmd.options == 0x01
    emu = _emu()
    reply = emu.handle_rx(POSITION_ID, encode_position(1, 0x0567, 0x01), 1.2)
    assert reply is not None
    assert reply.can_id == 0x101
    pitch = emu.handle_rx(POSITION_ID, encode_position(2, 100, 0x01), 1.3)
    assert pitch is not None and pitch.can_id == 0x111
    assert emu.servo_by_role("pitch").command_count == 1
    other = emu.handle_rx(POSITION_ID, encode_position(3, 100, 0x01), 1.4)
    assert other is None


def test_t5_reply_encoder():
    bank = encode_reply(1, position=0x0567, engaged=True, voltage_v=13.8, torque=0)
    assert bank.can_id == 0x101
    assert len(bank.data) == 5
    assert bank.data[1] == 0x67
    assert bank.data[2] == 0x05
    assert bank.data[3] == 88
    assert bank.data[0] & 0x01
    padded = encode_reply(1, position=0, engaged=False, voltage_v=13.8, torque=0, pad_dlc=8)
    assert padded.can_id == 0x101
    assert padded.data == bytes([0x00, 0x00, 0x00, 88, 0x00, 0x00, 0x00, 0x00])
    pitch = encode_reply(2, position=0x0567, engaged=True, voltage_v=13.8)
    assert pitch.can_id == 0x111
    assert voltage_byte(13.8) == 88


def test_arduino_reply_footer():
    emu = _emu()
    idle = emu.servo_by_role("roll").make_reply()
    assert idle is not None
    assert idle.data == bytes(
        [0x00, ARDUINO_IDLE_POSITION & 0xFF, 0x00, ARDUINO_VOLTAGE_BYTE, ARDUINO_TORQUE_BYTE]
    )
    reply = emu.handle_rx(POSITION_ID, encode_position(2, 0x0071, 0x00), 1.0)
    assert reply is not None
    assert reply.can_id == 0x111
    assert reply.data == bytes([0x00, 0x71, 0x00, 0x80, 0x70])
    engaged = emu.handle_rx(POSITION_ID, encode_position(2, 0x0071, 0x01), 1.1)
    assert engaged is not None
    assert engaged.data == bytes([0x01, 0x71, 0x00, 0x80, 0x70])


def test_t7_timeout_clears_engage_then_chirps():
    emu = _emu()
    reply = emu.handle_rx(POSITION_ID, encode_position(1, 100, 0x01), 10.0)
    assert reply is not None
    roll = emu.servo_by_role("roll")
    assert roll.state == STATE_ACTIVE
    assert roll.engaged is True
    early = emu.tick(10.2)
    assert roll.state == STATE_ACTIVE
    assert roll.engaged is True
    assert all(c.can_id != 0x101 for c in early)
    chirps = emu.tick(10.4)
    assert roll.state == STATE_IDENTIFIED_IDLE
    assert roll.engaged is False
    assert roll.timeout_count == 1
    by_id = {c.can_id: c for c in chirps}
    assert 0x101 in by_id
    assert by_id[0x101].data[0] == 0
    assert by_id[0x101].data[3] == 0x80
    assert by_id[0x101].data[4] == 0x70
    assert emu.handle_rx(0x101, b"\x00" * 5, 10.5) is None


def test_t8_echo_follows_target_through_wrap():
    emu = _emu()
    t = 1.0
    for pos in (100, 200, -6, 10, 0, -1):
        t += 0.1
        emu.handle_rx(POSITION_ID, encode_position(1, pos, 0x01), t)
        roll = emu.servo_by_role("roll")
        assert roll.current == pos
        assert roll.target == pos
        assert roll.position_error() == 0


def test_t11_interlock_blocks_tx():
    for flags in (
        {"allow_tx": False, "tx_armed": True},
        {"allow_tx": True, "tx_armed": False},
    ):
        emu = _emu(**flags)
        emu.cfg.interface_ok = True
        assert emu.handle_rx(POSITION_ID, encode_position(1, 50, 0x01), 1.1) is None
        assert emu.servo_by_role("roll").reply_count == 0
    emu = _emu(allow_tx=True, tx_armed=True)
    emu.cfg.interface_ok = True
    assert emu.handle_rx(POSITION_ID, encode_position(1, 50, 0x01), 1.1) is not None
    emu.disarm_tx("test")
    assert emu.handle_rx(POSITION_ID, encode_position(1, 60, 0x01), 1.2) is None


def test_passive_identify_is_recorded_but_not_accepted():
    emu = ServoEmulator.from_mapping(
        {
            "enabled": True,
            "allow_tx": False,
            "servos": {
                "roll": {"enabled": True, "identify_armed": False},
                "pitch": {"enabled": True, "identify_armed": False},
            },
        }
    )
    emu.cfg.interface_ok = True
    assert emu.handle_rx(IDENTIFY_ID, encode_identify(1), 1.0) is None
    assert emu.last_identify_num == 1
    assert emu.last_identify_accepted is False
    assert emu.servo_by_role("roll").servo_number == 1
    assert emu.fix_values(1.0)["MGL_SRV_LAST_ID"] == 1.0


def test_fix_keys_are_in_database_yaml():
    from pathlib import Path

    yaml = Path(__file__).resolve().parents[2] / "config" / "fixgw" / "database" / "mgl_servo.yaml"
    defined = {
        line.split(":", 1)[1].strip()
        for line in yaml.read_text().splitlines()
        if line.startswith("- key:")
    }
    emu = _emu()
    emu.cfg.interface_ok = True
    missing = set(emu.fix_values(1.0)) - defined
    assert not missing, missing
    emu = _emu()
    emu.cfg.interface_ok = True
    emu.handle_rx(IDENTIFY_ID, encode_identify(1), 1.0)
    emu.handle_rx(POSITION_ID, encode_position(1, 0x123, 0x11), 1.1)
    vals = emu.fix_values(1.1)
    assert vals["MGL_SRV_ROLL_TGT"] == 0x123
    assert vals["MGL_SRV_ROLL_CUR"] == 0x123
    assert vals["MGL_SRV_ROLL_ENG_REQ"] is True
    assert vals["MGL_SRV_ROLL_RPLY"] == 1
    assert vals["MGL_SRV_TX_ARMED"] is True
    assert "MGL_SRV_PITCH_TGT" in vals


def test_identify_does_not_reassign():
    emu = _emu()
    emu.handle_rx(IDENTIFY_ID, encode_identify(3), 1.0)
    roll = emu.servo_by_role("roll")
    assert roll.servo_number == 1
    assert emu.last_identify_num == 3
    assert emu.last_identify_accepted is False
    assert reply_id(3) == 0x121


def test_install_mode_arms_tx_and_manual_position():
    import tempfile
    from pathlib import Path

    from web.app.services.mgl_servo import control as ctl

    path = Path(tempfile.mkdtemp()) / "ctrl.json"
    orig = ctl.control_path
    ctl.control_path = lambda: path
    try:
        emu = _emu(allow_tx=False, tx_armed=False)
        emu.cfg.yaml_allow_tx = False
        emu.cfg.yaml_tx_armed = False
        emu.cfg.interface_ok = True
        ctl.save_control(
            {
                "session": "s1",
                "install_mode": True,
                "axis": "roll",
                "step": "identify",
                "manual_position": 100,
            }
        )
        ctl.apply_install_control(emu, ctl.load_control())
        roll = emu.servo_by_role("roll")
        assert roll.identify_armed is False
        assert emu.servo_by_role("pitch").enabled is True
        assert emu.cfg.tx_armed is True
        assert emu.handle_rx(IDENTIFY_ID, encode_identify(1), 1.0) is None
        reply = emu.handle_rx(POSITION_ID, encode_position(1, 0, 0x40), 1.1)
        assert reply is not None and reply.can_id == 0x101
        ctl.save_control(
            {
                "session": "s1",
                "install_mode": True,
                "axis": "roll",
                "step": "limits",
                "manual_position": 1200,
            }
        )
        ctl.apply_install_control(emu, ctl.load_control())
        pos = emu.handle_rx(POSITION_ID, encode_position(1, 0, 0x40), 1.2)
        assert pos is not None
        assert emu.servo_by_role("roll").current == 1200
        assert pos.data[1] | (pos.data[2] << 8) == 1200
        ctl.save_control({"session": "s2", "install_mode": False, "step": "idle"})
        ctl.apply_install_control(emu, ctl.load_control())
        assert emu.cfg.tx_armed is False
        assert emu.servo_by_role("roll").identify_armed is False
        assert emu.servo_by_role("pitch").enabled is True
    finally:
        ctl.control_path = orig


def test_offset_added_and_clamped_to_limits():
    emu = _emu()
    roll = emu.servo_by_role("roll")
    roll.offset = 200
    roll.limit_lo = 100
    roll.limit_hi = 300
    reply = emu.handle_rx(POSITION_ID, encode_position(1, 150, 0x00), 1.0)
    assert reply is not None
    assert roll.target == 150
    assert roll.current == 300
    assert (reply.data[1] | (reply.data[2] << 8)) == 300
    roll.offset = -80
    reply = emu.handle_rx(POSITION_ID, encode_position(1, 150, 0x00), 1.1)
    assert roll.current == 100
    assert (reply.data[1] | (reply.data[2] << 8)) == 100


def test_control_offset_applies_in_idle():
    import tempfile
    from pathlib import Path

    from web.app.services.mgl_servo import control as ctl

    path = Path(tempfile.mkdtemp()) / "ctrl.json"
    orig = ctl.control_path
    ctl.control_path = lambda: path
    try:
        emu = _emu()
        emu.cfg.interface_ok = True
        emu.handle_rx(POSITION_ID, encode_position(1, 200, 0x00), 1.0)
        ctl.save_control(
            {
                "session": "idle1",
                "install_mode": False,
                "step": "idle",
                "offsets": {"roll": 50, "pitch": 0},
                "limits": {
                    "roll": {"left": 100, "right": 400},
                    "pitch": {"down": None, "up": None},
                },
            }
        )
        ctl.apply_install_control(emu, ctl.load_control())
        roll = emu.servo_by_role("roll")
        assert roll.offset == 50
        assert roll.limit_lo == 100
        assert roll.limit_hi == 400
        assert roll.current == 250
        ctl.save_control({**ctl.load_control(), "offsets": {"roll": 500, "pitch": 0}})
        ctl.apply_install_control(emu, ctl.load_control())
        assert emu.servo_by_role("roll").current == 400
    finally:
        ctl.control_path = orig


def test_negative_command_offset_and_legacy_full_limits():
    emu = _emu()
    roll = emu.servo_by_role("roll")
    reply = emu.handle_rx(POSITION_ID, encode_position(1, -1, 0x01), 1.0)
    assert roll.target == -1
    assert roll.current == -1
    assert (reply.data[1] | (reply.data[2] << 8)) == 4095
    roll.offset = -10
    reply = emu.handle_rx(POSITION_ID, encode_position(1, 0, 0x01), 1.1)
    assert roll.current == -10
    assert (reply.data[1] | (reply.data[2] << 8)) == s12_to_u12(-10)

    import tempfile
    from pathlib import Path

    from web.app.services.mgl_servo import control as ctl

    path = Path(tempfile.mkdtemp()) / "ctrl.json"
    orig = ctl.control_path
    ctl.control_path = lambda: path
    try:
        ctl.save_control(
            {
                "session": "legacy",
                "install_mode": False,
                "limits": {
                    "roll": {"left": 0, "right": 4095},
                    "pitch": {"down": 4095, "up": 0},
                },
            }
        )
        loaded = ctl.load_control()
        assert ctl.limit_span(loaded["limits"]["roll"], "roll") == (-2048, 2047)
        assert ctl.limit_span(loaded["limits"]["pitch"], "pitch") == (-2048, 2047)
        assert ctl.limit_span({"left": 400, "right": -400}, "roll") == (-400, 400)
        assert ctl.limit_span({"down": 300, "up": -800}, "pitch") == (-800, 300)
    finally:
        ctl.control_path = orig
