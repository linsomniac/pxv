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


def compose_luts(*luts: list[int]) -> list[int]:
    """Compose 256-entry LUTs left to right: result[i] = last(...(first[i])...)."""
    result = list(range(256))
    for lut in luts:
        result = [lut[v] for v in result]
    return result


def auto_levels(
    hist_rgb: list[int], clip_percent: float = 0.5
) -> tuple[LevelsChannel, LevelsChannel, LevelsChannel]:
    """Per-channel black/white points clipping clip_percent% of pixels per end.

    Takes the 768-entry Image.histogram() of the (pre-enhancement) working
    image. Channels with no data or a degenerate range come back as identity.
    """
    out: list[LevelsChannel] = []
    for c in range(3):
        bins = hist_rgb[c * 256 : (c + 1) * 256]
        total = sum(bins)
        if total == 0:
            out.append(LevelsChannel())
            continue
        clip = total * clip_percent / 100.0
        acc = 0
        lo = 0
        for i in range(256):
            acc += bins[i]
            if acc > clip:
                lo = i
                break
        acc = 0
        hi = 255
        for i in range(255, -1, -1):
            acc += bins[i]
            if acc > clip:
                hi = i
                break
        if hi <= lo:
            out.append(LevelsChannel())
        else:
            out.append(LevelsChannel(in_black=lo, in_white=hi))
    return (out[0], out[1], out[2])


def gamma_to_mid(in_black: int, in_white: int, gamma: float) -> float:
    """Marker x-position whose input value maps to 50% output (the gamma diamond).

    AIDEV-NOTE: levels_lut outputs 0.5 where t**(1/gamma) == 0.5, i.e. at
    t = 0.5**gamma — keep this and mid_to_gamma in sync with levels_lut.
    """
    span = max(1, in_white - in_black)
    return float(in_black) + span * math.pow(0.5, gamma)


def mid_to_gamma(in_black: int, in_white: int, x: float) -> float:
    """Inverse of gamma_to_mid, with t clamped so the result stays in [0.1, 10]."""
    span = max(1, in_white - in_black)
    t = min(0.9995, max(0.0005, (x - in_black) / span))
    return min(10.0, max(0.1, math.log(t) / math.log(0.5)))
