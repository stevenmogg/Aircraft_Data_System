"""Virtual MGL bank/pitch servos: ready replies, echo position, rates, timeouts.

Identify is ignored. Bank is servo 1 (0x101), pitch is servo 2 (0x111).
Replies match the Arduino program that the XTreme already accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from web.app.services.mgl_servo.interlock import TxInterlock, tx_allowed
from web.app.services.mgl_servo.protocol import (
    ARDUINO_IDLE_POSITION,
    ARDUINO_REPLY_DLC,
    ARDUINO_TORQUE_BYTE,
    ARDUINO_VOLTAGE_V,
    INT12_MAX,
    INT12_MIN,
    IdentifyCommand,
    PositionCommand,
    ServoReply,
    circular_error,
    clamp_s12,
    decode_identify,
    decode_position,
    device_address,
    engage_requested,
    encode_reply,
    reply_id,
    step_unwrap,
    torque_reset_requested,
    torque_setting,
)

STATE_DISABLED = 0
STATE_VIRGIN = 1
STATE_IDENTIFIED = 2
STATE_ACTIVE = 3
STATE_IDENTIFIED_IDLE = 4

STATE_NAME = {
    STATE_DISABLED: "DISABLED",
    STATE_VIRGIN: "VIRGIN",
    STATE_IDENTIFIED: "IDENTIFIED",
    STATE_ACTIVE: "ACTIVE",
    STATE_IDENTIFIED_IDLE: "IDENTIFIED_IDLE",
}


@dataclass
class VirtualServo:
    role: str
    expected_number: int
    enabled: bool = False
    identify_armed: bool = False
    mode: str = "echo"
    manual_position: int = 0
    simulated_voltage_v: float = ARDUINO_VOLTAGE_V
    simulated_torque: int = ARDUINO_TORQUE_BYTE
    engage_bit: int = 0
    reply_dlc: int = ARDUINO_REPLY_DLC
    timeout_s: float = 0.3
    unsolicited_interval_s: float = 0.1

    servo_number: int = 0
    state: int = STATE_DISABLED
    mismatch: bool = False

    target: int = ARDUINO_IDLE_POSITION
    current: int = ARDUINO_IDLE_POSITION
    unwrap_target: float = 0.0
    unwrap_current: float = 0.0
    options_raw: int = 0
    engage_req: bool = False
    engaged: bool = False
    slipping: bool = False
    voltage_alarm: bool = False
    offset: int = 0
    limit_lo: int = INT12_MIN
    limit_hi: int = INT12_MAX

    command_count: int = 0
    reply_count: int = 0
    invalid_count: int = 0
    timeout_count: int = 0
    first_cmd_ts: float | None = None
    last_cmd_ts: float | None = None
    last_unsolicited_ts: float | None = None
    last_interval_s: float | None = None
    min_interval_s: float | None = None
    max_interval_s: float | None = None
    warn: str | None = None

    def device_address(self) -> int:
        if self.servo_number <= 0:
            return 0
        return device_address(self.servo_number)

    def reply_can_id(self) -> int:
        if self.servo_number <= 0:
            return 0
        return reply_id(self.servo_number)

    def identified(self) -> bool:
        return self.servo_number > 0 and self.state != STATE_DISABLED

    def command_rate_hz(self) -> float:
        if self.command_count < 2 or self.first_cmd_ts is None or self.last_cmd_ts is None:
            return 0.0
        elapsed = max(self.last_cmd_ts - self.first_cmd_ts, 1e-6)
        return (self.command_count - 1) / elapsed

    def command_age_ms(self, now: float) -> float:
        if self.last_cmd_ts is None:
            return 0.0
        return max(0.0, (now - self.last_cmd_ts) * 1000.0)

    def note_command(self, now: float) -> None:
        if self.last_cmd_ts is not None:
            interval = now - self.last_cmd_ts
            self.last_interval_s = interval
            self.min_interval_s = interval if self.min_interval_s is None else min(self.min_interval_s, interval)
            self.max_interval_s = interval if self.max_interval_s is None else max(self.max_interval_s, interval)
        if self.first_cmd_ts is None:
            self.first_cmd_ts = now
        self.last_cmd_ts = now
        self.command_count += 1

    def reported_position(self) -> int:
        if self.mode == "manual":
            return clamp_s12(self.manual_position)
        raw = clamp_s12(int(self.target) + int(self.offset))
        lo = min(int(self.limit_lo), int(self.limit_hi))
        hi = max(int(self.limit_lo), int(self.limit_hi))
        return max(lo, min(hi, raw))

    def apply_echo(self, cmd: PositionCommand) -> None:
        prev_t = self.target
        prev_c = self.current
        self.target = cmd.target
        self.options_raw = cmd.options
        self.engage_req = engage_requested(cmd.options, self.engage_bit)
        self.engaged = self.engage_req
        self.current = self.reported_position()
        self.unwrap_target = step_unwrap(self.unwrap_target, prev_t, self.target)
        self.unwrap_current = step_unwrap(self.unwrap_current, prev_c, self.current)
        self.slipping = False
        self.voltage_alarm = False

    def position_error(self) -> int:
        return circular_error(self.target, self.current)

    def make_reply(self) -> ServoReply | None:
        if self.servo_number <= 0:
            return None
        return encode_reply(
            self.servo_number,
            position=self.current,
            engaged=self.engaged,
            slipping=self.slipping,
            voltage_alarm=self.voltage_alarm,
            voltage_v=self.simulated_voltage_v,
            torque=self.simulated_torque,
            pad_dlc=self.reply_dlc,
        )

    def tick_timeout(self, now: float) -> None:
        if self.state != STATE_ACTIVE or self.last_cmd_ts is None:
            return
        if (now - self.last_cmd_ts) < self.timeout_s:
            return
        self.state = STATE_IDENTIFIED_IDLE
        self.engaged = False
        self.timeout_count += 1

    def due_unsolicited(self, now: float) -> bool:
        """Arduino watchdog: keep chirping 0x101/0x111 when 0x011 is missing."""
        if not self.enabled or self.state == STATE_DISABLED or self.servo_number <= 0:
            return False
        if self.state == STATE_ACTIVE and self.last_cmd_ts is not None:
            if (now - self.last_cmd_ts) < self.timeout_s:
                return False
        last = self.last_unsolicited_ts
        if last is not None and (now - last) < self.unsolicited_interval_s:
            return False
        return True

    def fix_prefix(self) -> str:
        return "MGL_SRV_ROLL" if self.role == "roll" else "MGL_SRV_PITCH"

    def fix_values(self, now: float) -> dict[str, Any]:
        p = self.fix_prefix()
        return {
            f"{p}_NUM": float(self.servo_number),
            f"{p}_ADDR": float(self.device_address()),
            f"{p}_STATE": float(self.state),
            f"{p}_TGT": float(self.target),
            f"{p}_TGT_UNW": float(self.unwrap_target),
            f"{p}_CUR": float(self.current),
            f"{p}_CUR_UNW": float(self.unwrap_current),
            f"{p}_ERR": float(self.position_error()),
            f"{p}_OPT": float(self.options_raw),
            f"{p}_ENG_REQ": bool(self.engage_req),
            f"{p}_TRQ_SET": float(torque_setting(self.options_raw)),
            f"{p}_TRQ_RST": bool(torque_reset_requested(self.options_raw)),
            f"{p}_STAT": float(
                (1 if self.engaged else 0)
                | (2 if self.slipping else 0)
                | (4 if self.voltage_alarm else 0)
            ),
            f"{p}_ENG": bool(self.engaged),
            f"{p}_SLIP": bool(self.slipping),
            f"{p}_VALARM": bool(self.voltage_alarm),
            f"{p}_VOLT": float(self.simulated_voltage_v),
            f"{p}_TRQ": float(self.simulated_torque),
            f"{p}_HZ": float(self.command_rate_hz()),
            f"{p}_AGE": float(self.command_age_ms(now)),
            f"{p}_CMDS": float(self.command_count),
            f"{p}_RPLY": float(self.reply_count),
            f"{p}_BAD": float(self.invalid_count),
            f"{p}_TMO": float(self.timeout_count),
            f"{p}_IDOK": bool(self.identified()),
            f"{p}_IDARM": bool(self.identify_armed),
        }


@dataclass
class EmulatorConfig:
    enabled: bool = False
    allow_tx: bool = False
    tx_armed: bool = False
    command_timeout_ms: int = 300
    unsolicited_interval_ms: int = 100
    engage_bit: int = 0
    reply_dlc: int = ARDUINO_REPLY_DLC
    interface_ok: bool = False
    channel: str = "can0"
    yaml_allow_tx: bool = False
    yaml_tx_armed: bool = False


class ServoEmulator:
    """Two virtual servos. Sole producer of TX frames when interlock allows."""

    def __init__(self, cfg: EmulatorConfig, servos: Iterable[VirtualServo]):
        self.cfg = cfg
        self.servos = list(servos)
        self._assert_identify_lock()
        timeout_s = max(0.05, cfg.command_timeout_ms / 1000.0)
        chirp_s = max(0.05, cfg.unsolicited_interval_ms / 1000.0)
        for s in self.servos:
            s.timeout_s = timeout_s
            s.unsolicited_interval_s = chirp_s
            s.engage_bit = cfg.engage_bit
            s.reply_dlc = cfg.reply_dlc
            if s.servo_number <= 0:
                s.servo_number = s.expected_number
            if not cfg.enabled or not s.enabled:
                s.state = STATE_DISABLED
            else:
                s.state = STATE_IDENTIFIED
        self.tx_disarmed_reason: str | None = None
        self.last_identify_num: int = 0
        self.last_identify_accepted: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "ServoEmulator":
        data = dict(raw or {})
        cfg = EmulatorConfig(
            enabled=bool(data.get("enabled", False)),
            allow_tx=bool(data.get("allow_tx", False)),
            tx_armed=bool(data.get("tx_armed", False)),
            command_timeout_ms=int(data.get("command_timeout_ms", 300)),
            unsolicited_interval_ms=int(data.get("unsolicited_interval_ms", 100)),
            engage_bit=int(data.get("engage_bit", 0)),
            reply_dlc=int(data.get("reply_dlc", ARDUINO_REPLY_DLC)),
            channel=str(data.get("channel", "can0")),
        )
        cfg.yaml_allow_tx = cfg.allow_tx
        cfg.yaml_tx_armed = cfg.tx_armed
        servos_cfg = data.get("servos") or {}
        servos = [
            _servo_from_cfg("roll", 1, servos_cfg.get("roll") or {}, cfg),
            _servo_from_cfg("pitch", 2, servos_cfg.get("pitch") or {}, cfg),
        ]
        return cls(cfg, servos)

    def _assert_identify_lock(self) -> None:
        armed = [s for s in self.servos if s.identify_armed]
        if len(armed) > 1:
            raise ValueError("only one virtual servo may be identify_armed")

    def servo_by_role(self, role: str) -> VirtualServo:
        for s in self.servos:
            if s.role == role:
                return s
        raise KeyError(role)

    def servo_by_number(self, number: int) -> VirtualServo | None:
        for s in self.servos:
            if s.servo_number == number and number > 0:
                return s
        return None

    def set_tx_armed(self, armed: bool) -> None:
        self.cfg.tx_armed = bool(armed)
        if not armed:
            self.tx_disarmed_reason = "operator"

    def reset_ready(self, role: str) -> None:
        servo = self.servo_by_role(role)
        servo.servo_number = servo.expected_number
        servo.state = STATE_IDENTIFIED if servo.enabled else STATE_DISABLED
        servo.identify_armed = False
        servo.mismatch = False
        servo.warn = None
        servo.mode = "echo"
        servo.manual_position = 0
        servo.target = ARDUINO_IDLE_POSITION
        servo.current = ARDUINO_IDLE_POSITION
        servo.command_count = 0
        servo.reply_count = 0
        servo.invalid_count = 0
        servo.timeout_count = 0
        servo.first_cmd_ts = None
        servo.last_cmd_ts = None
        servo.last_unsolicited_ts = None

    def start_install(self, axis: str) -> None:
        if axis not in ("roll", "pitch"):
            raise ValueError("axis must be roll or pitch")
        self.cfg.enabled = True
        self.cfg.allow_tx = True
        self.cfg.tx_armed = True
        self.tx_disarmed_reason = None
        for servo in self.servos:
            servo.identify_armed = False
            servo.enabled = True
            if servo.servo_number <= 0:
                servo.servo_number = servo.expected_number
            if servo.state in (STATE_DISABLED, STATE_VIRGIN):
                servo.state = STATE_IDENTIFIED
        chosen = self.servo_by_role(axis)
        chosen.enabled = True
        chosen.mode = "echo"

    def enter_limits(self, axis: str, position: int) -> None:
        servo = self.servo_by_role(axis)
        servo.identify_armed = False
        servo.mode = "manual"
        servo.manual_position = clamp_s12(position)
        servo.current = servo.manual_position

    def restore_operational(self) -> None:
        """Both axes ready at bank=1 / pitch=2. TX follows yaml defaults."""
        self.cfg.allow_tx = self.cfg.yaml_allow_tx
        self.cfg.tx_armed = self.cfg.yaml_tx_armed
        self.tx_disarmed_reason = None if (self.cfg.allow_tx and self.cfg.tx_armed) else "operator"
        for servo in self.servos:
            servo.identify_armed = False
            servo.mode = "echo"
            servo.enabled = True
            if servo.servo_number <= 0:
                servo.servo_number = servo.expected_number
            if servo.state in (STATE_DISABLED, STATE_VIRGIN):
                servo.state = STATE_IDENTIFIED if self.cfg.enabled else STATE_DISABLED

    def abort_install(self) -> None:
        self.restore_operational()

    def disarm_tx(self, reason: str) -> None:
        self.cfg.tx_armed = False
        self.tx_disarmed_reason = reason

    def tick(self, now: float) -> list[ServoReply]:
        replies: list[ServoReply] = []
        for servo in self.servos:
            servo.tick_timeout(now)
            if not servo.due_unsolicited(now):
                continue
            servo.engaged = False
            reply = self._maybe_tx(servo, identified=True)
            if reply is None:
                continue
            servo.last_unsolicited_ts = now
            replies.append(reply)
        return replies

    def handle_rx(
        self,
        can_id: int,
        data: bytes,
        now: float,
        *,
        extended: bool = False,
    ) -> ServoReply | None:
        ident = decode_identify(can_id, data, extended=extended)
        if ident is not None:
            return self._on_identify(ident, now)
        pos = decode_position(can_id, data, extended=extended)
        if pos is not None:
            return self._on_position(pos, now)
        return None

    def _on_identify(self, cmd: IdentifyCommand, now: float) -> ServoReply | None:
        del now
        self.last_identify_num = cmd.servo_number
        self.last_identify_accepted = False
        return None

    def _maybe_tx(self, servo: VirtualServo, *, identified: bool) -> ServoReply | None:
        reply = servo.make_reply()
        if reply is None:
            return None
        ready = servo.identified() or identified or servo.state == STATE_ACTIVE
        lock = TxInterlock(
            allow_tx=self.cfg.allow_tx,
            tx_armed=self.cfg.tx_armed,
            emulator_enabled=self.cfg.enabled,
            interface_ok=self.cfg.interface_ok,
            servo_enabled=servo.enabled,
            valid_state=ready,
            valid_command=True,
        )
        if not tx_allowed(lock):
            return None
        servo.reply_count += 1
        return reply

    def _on_position(self, cmd: PositionCommand, now: float) -> ServoReply | None:
        servo = self.servo_by_number(cmd.servo_number)
        if servo is None or not servo.enabled or servo.state == STATE_DISABLED:
            return None
        servo.note_command(now)
        servo.apply_echo(cmd)
        servo.state = STATE_ACTIVE
        return self._maybe_tx(servo, identified=True)

    def fix_values(self, now: float) -> dict[str, Any]:
        out: dict[str, Any] = {
            "MGL_SRV_ENABLED": bool(self.cfg.enabled),
            "MGL_SRV_ALLOW_TX": bool(self.cfg.allow_tx),
            "MGL_SRV_TX_ARMED": bool(self.cfg.tx_armed),
            "MGL_SRV_LAST_ID": float(self.last_identify_num),
            "MGL_SRV_LAST_ID_OK": bool(self.last_identify_accepted),
        }
        for s in self.servos:
            out.update(s.fix_values(now))
        return out

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.cfg.enabled,
            "allow_tx": self.cfg.allow_tx,
            "tx_armed": self.cfg.tx_armed,
            "tx_disarmed_reason": self.tx_disarmed_reason,
            "channel": self.cfg.channel,
            "interface_ok": self.cfg.interface_ok,
            "servos": {
                s.role: {
                    "state": STATE_NAME.get(s.state, s.state),
                    "servo_number": s.servo_number,
                    "reply_id": f"0x{s.reply_can_id():03X}" if s.servo_number else None,
                    "identify_armed": s.identify_armed,
                    "mismatch": s.mismatch,
                    "warn": s.warn,
                    "target": s.target,
                    "current": s.current,
                    "offset": s.offset,
                    "limit_lo": s.limit_lo,
                    "limit_hi": s.limit_hi,
                    "engaged": s.engaged,
                    "hz": round(s.command_rate_hz(), 2),
                    "commands": s.command_count,
                    "replies": s.reply_count,
                    "timeouts": s.timeout_count,
                }
                for s in self.servos
            },
        }


def _servo_from_cfg(role: str, expected: int, raw: dict[str, Any], cfg: EmulatorConfig) -> VirtualServo:
    enabled = bool(raw.get("enabled", False))
    expected_number = int(raw.get("expected_number", expected))
    number = int(raw.get("servo_number", expected_number))
    if number <= 0:
        number = expected_number
    return VirtualServo(
        role=role,
        expected_number=expected_number,
        enabled=enabled,
        identify_armed=bool(raw.get("identify_armed", False)),
        mode=str(raw.get("mode", "echo")),
        simulated_voltage_v=float(raw.get("simulated_voltage_v", ARDUINO_VOLTAGE_V)),
        simulated_torque=int(raw.get("simulated_torque", ARDUINO_TORQUE_BYTE)),
        engage_bit=cfg.engage_bit,
        servo_number=number,
        current=ARDUINO_IDLE_POSITION,
        target=ARDUINO_IDLE_POSITION,
    )
