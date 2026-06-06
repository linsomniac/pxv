"""Pure slideshow-interval helpers (no Tk), so the timing math is unit-testable.

The PxvApp owns the actual Tk ``after`` timer; this module only converts and clamps
interval values.
"""

from __future__ import annotations

DEFAULT_SLIDESHOW_SECONDS = 4
MIN_SLIDESHOW_SECONDS = 1


def interval_to_ms(seconds: float) -> int:
    """Clamp `seconds` to >= MIN_SLIDESHOW_SECONDS and convert to whole milliseconds."""
    return int(max(MIN_SLIDESHOW_SECONDS, seconds) * 1000)


def adjusted_interval_ms(current_ms: int, delta_seconds: float) -> int:
    """Apply a +/- seconds delta to a millisecond interval, clamped to the minimum."""
    return interval_to_ms(current_ms / 1000 + delta_seconds)
