"""NetFIX client wrapper for Historian sampling (polled reads)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Iterable

log = logging.getLogger("historian.fix")


@dataclass
class FixSample:
    key: str
    value: float | str | int | None
    flags: str  # subset of a,o,b,f,s
    raw: str | None = None


class FixClient:
    """Polled NetFIX reader against localhost FIX-Gateway.

    Uses synchronous ``@r`` reads each sample tick. Subscribe/push is avoided
    because connect callbacks + concurrent reads deadlock the upstream client.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 3490, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client = None
        self._lock = threading.RLock()
        self._keys: list[str] = []

    def connect(self, keys: Iterable[str] | None = None) -> None:
        import fixgw.netfix as netfix

        self._keys = list(keys or [])
        self._client = netfix.Client(self.host, self.port, timeout=self.timeout)
        ok = self._client.connect()
        if not ok:
            deadline = time.time() + self.timeout
            while time.time() < deadline and not self._client.isConnected():
                time.sleep(0.05)
        if not self._client.isConnected():
            raise ConnectionError(f"cannot connect to FIX at {self.host}:{self.port}")
        log.info("FIX connected %s:%s (%d keys)", self.host, self.port, len(self._keys))

    def is_connected(self) -> bool:
        return bool(self._client and self._client.isConnected())

    def read_one(self, key: str) -> FixSample:
        assert self._client is not None
        with self._lock:
            try:
                res = self._client.read(key)
            except Exception as e:
                log.debug("read %s failed: %s", key, e)
                return FixSample(key=key, value=None, flags="f", raw=None)
        if isinstance(res, int):
            return FixSample(key=key, value=None, flags="f", raw=None)
        if not isinstance(res, tuple) or len(res) < 2:
            return FixSample(key=key, value=None, flags="f", raw=None)
        raw = str(res[1])
        flags = res[2] if len(res) > 2 else ""
        return FixSample(key=key, value=self._parse_value(raw), flags=flags or "", raw=raw)

    def read_many(self, keys: Iterable[str]) -> dict[str, FixSample]:
        return {key: self.read_one(key) for key in keys}

    @staticmethod
    def _parse_value(raw: str) -> float | None:
        if raw is None or raw == "" or raw == "None":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
