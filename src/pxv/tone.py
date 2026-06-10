"""Pure tone-mapping math for levels and curves.

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


CurvePoints = tuple[tuple[int, int], ...]
IDENTITY_CURVE: CurvePoints = ((0, 0), (255, 255))


def curve_lut(points: CurvePoints) -> list[int]:
    """256-entry LUT through control points via monotone cubic interpolation.

    x must be strictly increasing; y is free in 0-255, so non-monotone curves
    (solarize) are allowed. Outside the x range the LUT extends flat.

    AIDEV-NOTE: Fritsch–Butland tangents — zero at local extrema, weighted
    harmonic mean elsewhere — keep every segment monotone between its control
    points (|m| <= 3|d| condition), which is what prevents overshoot. Keep
    this property: the curve editor promises "no wiggles between handles".
    """
    if len(points) < 2:
        raise ValueError("curve needs at least 2 points")
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        raise ValueError("curve x values must be strictly increasing")

    n = len(points)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]

    m = [0.0] * n
    m[0] = d[0]
    m[n - 1] = d[n - 2]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

    lut: list[int] = []
    seg = 0
    for x in range(256):
        if x <= xs[0]:
            y = ys[0]
        elif x >= xs[-1]:
            y = ys[-1]
        else:
            while xs[seg + 1] < x:
                seg += 1
            t = (x - xs[seg]) / h[seg]
            t2 = t * t
            t3 = t2 * t
            y = (
                (2 * t3 - 3 * t2 + 1) * ys[seg]
                + (t3 - 2 * t2 + t) * h[seg] * m[seg]
                + (-2 * t3 + 3 * t2) * ys[seg + 1]
                + (t3 - t2) * h[seg] * m[seg + 1]
            )
        lut.append(max(0, min(255, int(y + 0.5))))
    return lut


def gray_balance_gammas(sample: tuple[int, int, int]) -> tuple[float, float, float]:
    """Per-channel gammas that map a sampled near-gray pixel to neutral.

    Target is the sample mean. From levels_lut, output (v/255)**(1/gamma)
    equals m/255 when gamma = log(v/255) / log(m/255). Channels at 0/255 (or
    an extreme mean) cannot be gamma-balanced and fall back to 1.0.
    """
    m = sum(sample) / 3.0
    if m <= 0.0 or m >= 255.0:
        return (1.0, 1.0, 1.0)
    gammas: list[float] = []
    for v in sample:
        if v <= 0 or v >= 255:
            gammas.append(1.0)
        else:
            g = math.log(v / 255.0) / math.log(m / 255.0)
            gammas.append(min(10.0, max(0.1, round(g, 2))))
    return (gammas[0], gammas[1], gammas[2])


def equalize_curve(hist_lum: list[int], n_points: int = 9) -> CurvePoints:
    """Histogram-equalization master curve: the CDF sampled at even inputs.

    Returns ordinary, editable control points — equalization stays
    non-destructive and tweakable (beyond xv). Empty histogram -> identity.
    """
    total = sum(hist_lum)
    if total == 0:
        return IDENTITY_CURVE
    cdf: list[float] = []
    acc = 0
    for count in hist_lum:
        acc += count
        cdf.append(acc / total)
    points: list[tuple[int, int]] = []
    for k in range(n_points):
        x = round(k * 255 / (n_points - 1))
        points.append((x, round(255 * cdf[x])))
    return tuple(points)
