"""Pure tone-mapping math for levels (and, in a later phase, curves).

AIDEV-NOTE: Everything here is display-free and unit-tested headlessly.
LevelsChannel is FROZEN on purpose: EnhancementParams snapshots use
dataclasses.replace() (a shallow copy), so every nested params field must be
immutable or undo/redo silently shares state (see the 2026-06-10 design).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LevelsChannel:
    """Input/output levels for one channel. Defaults are identity."""

    in_black: int = 0
    in_white: int = 255
    gamma: float = 1.0
    out_black: int = 0
    out_white: int = 255

    def is_identity(self) -> bool:
        return (
            self.in_black == 0
            and self.in_white == 255
            and self.gamma == 1.0
            and self.out_black == 0
            and self.out_white == 255
        )


def levels_lut(ch: LevelsChannel) -> list[int]:
    """256-entry LUT: out_b + clamp01((i - in_b)/(in_w - in_b))**(1/gamma) * (out_w - out_b)."""
    span = max(1, ch.in_white - ch.in_black)
    inv_gamma = 1.0 / ch.gamma if ch.gamma > 0 else 1.0
    out_span = ch.out_white - ch.out_black
    lut: list[int] = []
    for i in range(256):
        t = min(1.0, max(0.0, (i - ch.in_black) / span))
        v = ch.out_black + (t**inv_gamma) * out_span
        lut.append(max(0, min(255, int(v + 0.5))))
    return lut
