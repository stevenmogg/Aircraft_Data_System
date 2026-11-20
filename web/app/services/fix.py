"""FIX Gateway status helpers (independent of Historian)."""

from __future__ import annotations

import socket
from typing import Any


def fix_status(
    host: str = "127.0.0.1",
    port: int = 3490,
    sample_keys: tuple[str, ...] = (
        "STRX_PITCH",
        "STRX_ROLL",
        "STRX_LAT",
        "STRX_LONG",
        "STRX_GS",
    ),
) -> dict[str, Any]:
    reachable = False
    try:
        with socket.create_connection((host, port), timeout=0.5):
            reachable = True
    except OSError:
        reachable = False

    samples: dict[str, Any] = {}
    if reachable and sample_keys:
        try:
            from historian.capture.fix_client import FixClient

            client = FixClient(host=host, port=port, timeout=1.0)
            client.connect(list(sample_keys))
            for key in sample_keys:
                try:
                    value = client.read_one(key).value
                except Exception:
                    value = None
                samples[key.lower()] = value
                short = key.lower()
                if short.startswith("strx_"):
                    samples[short[5:]] = value
            client.disconnect()
        except Exception as e:
            return {
                "ok": False,
                "reachable": True,
                "host": host,
                "port": port,
                "error": str(e),
                "samples": samples,
            }

    out = {
        "ok": reachable,
        "reachable": reachable,
        "host": host,
        "port": port,
        "samples": samples,
    }
    # Back-compat for Live / older callers
    if "pitch" in samples:
        out["sample_pitch"] = samples["pitch"]
    return out
