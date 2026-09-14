"""Unix-socket control client/server protocol for the Historian daemon."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

DEFAULT_SOCKET = Path("/cozy-data-system/data/historian/historian.sock")


class ControlError(RuntimeError):
    pass


def socket_path_from_cfg(hist_cfg: dict[str, Any] | None = None) -> Path:
    if hist_cfg and hist_cfg.get("control_socket"):
        return Path(hist_cfg["control_socket"])
    return DEFAULT_SOCKET


def send_command(
    cmd: dict[str, Any],
    sock_path: Path | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    path = sock_path or DEFAULT_SOCKET
    if not path.exists():
        raise ControlError(
            f"historian daemon socket not found at {path}; "
            "is cozy-historian.service running?"
        )
    payload = (json.dumps(cmd) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(str(path))
        except OSError as e:
            raise ControlError(f"cannot connect to historian daemon at {path}: {e}") from e
        s.sendall(payload)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    if not buf:
        raise ControlError("empty response from historian daemon")
    try:
        resp = json.loads(buf.decode("utf-8").strip())
    except json.JSONDecodeError as e:
        raise ControlError(f"bad daemon response: {buf!r}") from e
    if not isinstance(resp, dict):
        raise ControlError(f"bad daemon response type: {resp!r}")
    return resp
