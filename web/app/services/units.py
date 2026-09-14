"""Canonical unit conversions for FIX ingest (store aircraft units)."""

from __future__ import annotations

FT_PER_M = 3.280839895


def c_to_f(celsius: float) -> float:
    return float(celsius) * 9.0 / 5.0 + 32.0


def m_to_ft(meters: float) -> float:
    return float(meters) * FT_PER_M
