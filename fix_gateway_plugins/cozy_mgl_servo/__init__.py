"""MGL autopilot servo emulator → FIX (separate from RDAC CAN plugin).

Listens on the same SocketCAN interface. Sole CAN transmitter when
allow_tx and tx_armed are both true. Default aircraft config is listen-only.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

import can
import fixgw.plugin as plugin

from web.app.services.mgl_servo.control import ControlPoller
from web.app.services.mgl_servo.emulator import ServoEmulator
from web.app.services.mgl_servo.protocol import IDENTIFY_ID, POSITION_ID

_SKIP_CFG = {"load", "module"}


def _emulator_config(raw: dict) -> dict:
    return {k: v for k, v in raw.items() if k not in _SKIP_CFG}


class MainThread(threading.Thread):
    def __init__(self, parent: "Plugin"):
        super().__init__(daemon=True)
        self.parent = parent
        self.log = parent.log
        self.getout = False
        cfg = _emulator_config(dict(parent.config))
        self.channel = str(cfg.get("channel", "can0"))
        self.interface = str(cfg.get("interface", "socketcan"))
        self.emu = ServoEmulator.from_mapping(cfg)
        self.parent.emu = self.emu
        self._fail_logged = False
        self._control = ControlPoller()

    def run(self):
        self.log.info(
            "MGL servo emulator %s/%s enabled=%s allow_tx=%s tx_armed=%s",
            self.interface,
            self.channel,
            self.emu.cfg.enabled,
            self.emu.cfg.allow_tx,
            self.emu.cfg.tx_armed,
        )
        backoff = 1.0
        while not self.getout:
            bus = None
            try:
                bus = can.ThreadSafeBus(
                    self.channel,
                    interface=self.interface,
                    can_filters=[
                        {"can_id": IDENTIFY_ID, "can_mask": 0x7FF, "extended": False},
                        {"can_id": POSITION_ID, "can_mask": 0x7FF, "extended": False},
                    ],
                )
                self.emu.cfg.interface_ok = True
                self.parent.status["link"] = "UP"
                self.parent.status["error"] = None
                self._fail_logged = False
                backoff = 1.0
                self.log.info("MGL servo listening on %s", self.channel)
                while not self.getout:
                    msg = bus.recv(0.1)
                    now = time.time()
                    self._control.maybe_apply(self.emu)
                    replies = []
                    if msg is not None and not getattr(msg, "is_error_frame", False):
                        self.parent.status["rx_frames"] = (
                            int(self.parent.status.get("rx_frames", 0)) + 1
                        )
                        reply = self.emu.handle_rx(
                            int(msg.arbitration_id),
                            bytes(msg.data),
                            now,
                            extended=bool(msg.is_extended_id),
                        )
                        if reply is not None:
                            replies.append(reply)
                    elif msg is not None:
                        self.parent.status["error_frames"] = (
                            int(self.parent.status.get("error_frames", 0)) + 1
                        )
                    replies.extend(self.emu.tick(now))
                    for reply in replies:
                        try:
                            bus.send(
                                can.Message(
                                    arbitration_id=reply.can_id,
                                    data=reply.data,
                                    is_extended_id=False,
                                ),
                                timeout=0.1,
                            )
                            self.parent.status["tx_frames"] = (
                                int(self.parent.status.get("tx_frames", 0)) + 1
                            )
                        except Exception as e:
                            self.log.warning("MGL servo TX failed, disarming: %s", e)
                            self.emu.disarm_tx(str(e))
                            self.parent.status["link"] = "TX_DISARMED"
                            break
                    self._publish(now)
            except Exception as e:
                self.emu.cfg.interface_ok = False
                if not self._fail_logged:
                    self.log.warning("MGL servo bus error: %s", e)
                    self._fail_logged = True
                self.parent.status["link"] = "DOWN"
                self.parent.status["error"] = str(e)
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
            finally:
                if bus is not None:
                    try:
                        bus.shutdown()
                    except Exception:
                        pass

    def _publish(self, now: float) -> None:
        write = self.parent.db_write
        for key, value in self.emu.fix_values(now).items():
            try:
                write(key, value)
            except Exception as e:
                self.log.debug("db_write %s failed: %s", key, e)
        st = self.parent.status
        st["tx_armed"] = self.emu.cfg.tx_armed
        st["allow_tx"] = self.emu.cfg.allow_tx
        roll = self.emu.servo_by_role("roll")
        pitch = self.emu.servo_by_role("pitch")
        st["roll"] = roll.servo_number
        st["pitch"] = pitch.servo_number
        st["roll_state"] = roll.state
        st["pitch_state"] = pitch.state

    def stop(self):
        self.getout = True


class Plugin(plugin.PluginBase):
    def __init__(self, name, config, config_meta):
        super().__init__(name, config, config_meta)
        self.emu: ServoEmulator | None = None
        self.thread = MainThread(self)
        self.status = OrderedDict(
            {
                "channel": config.get("channel", "can0"),
                "link": "INIT",
                "rx_frames": 0,
                "tx_frames": 0,
                "error_frames": 0,
                "allow_tx": bool(config.get("allow_tx", False)),
                "tx_armed": bool(config.get("tx_armed", False)),
            }
        )

    def run(self):
        self.thread.start()

    def stop(self):
        self.thread.stop()
        if self.thread.is_alive():
            self.thread.join(2.0)
        if self.thread.is_alive():
            raise plugin.PluginFail

    def get_status(self):
        extra = self.emu.status() if self.emu is not None else {}
        merged = OrderedDict(self.status)
        merged["emulator"] = extra
        return merged
