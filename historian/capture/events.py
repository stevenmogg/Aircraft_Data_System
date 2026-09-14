"""FIX quality transition → Historian events."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityEvent:
    event_type: str
    parameter: str
    value: str | None
    text: str


def _state_from_flags(flags: str) -> str:
    flags = flags or ""
    if "f" in flags or "b" in flags:
        return "bad"
    if "o" in flags:
        return "stale"
    return "good"


class QualityTracker:
    """Emit events only on quality state transitions (spec §18)."""

    def __init__(self):
        self._state: dict[str, str] = {}

    def update(self, key: str, flags: str, value) -> list[QualityEvent]:
        new_state = _state_from_flags(flags)
        old = self._state.get(key)
        self._state[key] = new_state
        if old is None or old == new_state:
            return []

        events: list[QualityEvent] = []
        raw = None if value is None else str(value)

        if new_state == "stale" and old == "good":
            events.append(
                QualityEvent("PARAMETER_STALE", key, raw, f"{key} became stale")
            )
        elif new_state == "good" and old == "stale":
            events.append(
                QualityEvent("PARAMETER_RECOVERED", key, raw, f"{key} recovered")
            )
        elif new_state == "bad" and old != "bad":
            events.append(QualityEvent("PARAMETER_BAD", key, raw, f"{key} bad/fail"))
        elif new_state == "good" and old == "bad":
            events.append(QualityEvent("PARAMETER_GOOD", key, raw, f"{key} good again"))
        elif new_state == "stale" and old == "bad":
            events.append(
                QualityEvent("PARAMETER_STALE", key, raw, f"{key} stale after bad")
            )
        return events
