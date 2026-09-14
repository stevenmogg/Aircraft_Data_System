"""Monotonic Historian timebase helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time


def utc_iso(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class TimingStats:
    expected_frames: int = 0
    actual_frames: int = 0
    periods: list[float] | None = None
    timing_overruns: int = 0

    def __post_init__(self):
        if self.periods is None:
            self.periods = []

    def note_period(self, period_s: float) -> None:
        assert self.periods is not None
        self.periods.append(period_s)

    def summary(self) -> dict:
        periods = self.periods or []
        return {
            "expected_10hz_frames": self.expected_frames,
            "actual_10hz_frames": self.actual_frames,
            "mean_sample_period_s": (sum(periods) / len(periods)) if periods else None,
            "minimum_sample_period_s": min(periods) if periods else None,
            "maximum_sample_period_s": max(periods) if periods else None,
            "timing_overruns": self.timing_overruns,
        }


class FlightClock:
    """Single timebase: frame_number / rate defines flight_time_s."""

    def __init__(self, rate_hz: float = 10.0):
        self.rate_hz = float(rate_hz)
        self.period_s = 1.0 / self.rate_hz
        self.t0_mono: float | None = None
        self.t0_utc: datetime | None = None
        self.frame_number = 0
        self._last_sample_mono: float | None = None
        self.stats = TimingStats()

    def start(self) -> None:
        self.t0_mono = time.monotonic()
        self.t0_utc = datetime.now(timezone.utc)
        self.frame_number = 0
        self._last_sample_mono = None
        self.stats = TimingStats()

    def wait_next(self, tolerance_s: float = 0.05) -> tuple[int, float, str, bool]:
        """
        Sleep until the next frame time.

        Returns (frame_number, flight_time_s, historian_time_utc, overrun).
        """
        if self.t0_mono is None or self.t0_utc is None:
            raise RuntimeError("FlightClock not started")

        target = self.t0_mono + self.frame_number * self.period_s
        now = time.monotonic()
        delay = target - now
        if delay > 0:
            time.sleep(delay)

        sample_mono = time.monotonic()
        overrun = (sample_mono - target) > tolerance_s
        if overrun:
            self.stats.timing_overruns += 1

        if self._last_sample_mono is not None:
            self.stats.note_period(sample_mono - self._last_sample_mono)
        self._last_sample_mono = sample_mono

        flight_time_s = self.frame_number / self.rate_hz
        hist_utc = self.t0_utc + timedelta(seconds=flight_time_s)
        frame = self.frame_number
        self.frame_number += 1
        self.stats.expected_frames = frame + 1
        self.stats.actual_frames += 1
        return frame, flight_time_s, utc_iso(hist_utc), overrun
