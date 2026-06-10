"""Histogram computation, rendering, and the enhancement dialog's histogram panel.

AIDEV-NOTE: Split like canvas_view.py — compute_histograms/render_histogram/
clipping_percentages are pure (no Tk) so they're unit-testable headlessly; the
HistogramPanel widget is a thin Tk shell that caches the last histograms so
channel/log toggles re-render without needing a new image.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

HIST_SIZE = (256, 100)

# (key, label, overlay color) for the channel toggles, in display order.
CHANNELS: list[tuple[str, str, tuple[int, int, int]]] = [
    ("lum", "Lum", (200, 200, 200)),
    ("r", "R", (235, 80, 80)),
    ("g", "G", (90, 200, 90)),
    ("b", "B", (95, 140, 235)),
]


def compute_histograms(img: Image.Image) -> tuple[list[int], list[int]]:
    """Return (luminance, rgb) histograms: 256 and 768 entries."""
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    return rgb.convert("L").histogram(), rgb.histogram()


def clipping_percentages(rgb_hist: list[int]) -> tuple[float, float]:
    """(% of pixels clipped at 0, % clipped at 255), per the worst single channel.

    AIDEV-NOTE: True "any channel clipped" needs per-pixel data; the worst
    channel's bin count is a close, cheap proxy computable from the histogram.
    """
    total = sum(rgb_hist[:256])
    if total == 0:
        return (0.0, 0.0)
    lo = max(rgb_hist[0], rgb_hist[256], rgb_hist[512])
    hi = max(rgb_hist[255], rgb_hist[511], rgb_hist[767])
    return (100.0 * lo / total, 100.0 * hi / total)


def render_histogram(
    lum: list[int],
    rgb: list[int],
    channels: set[str],
    log_scale: bool,
    size: tuple[int, int] = HIST_SIZE,
) -> Image.Image:
    """Render the enabled channel overlays into an RGB image.

    Each enabled channel is a translucent filled polygon alpha-composited over
    a dark background. Heights are normalized to the tallest bin across all
    enabled channels (log1p-scaled first when log_scale), so relative channel
    heights stay comparable.
    """
    w, h = size
    base = Image.new("RGBA", size, (24, 24, 24, 255))

    series: list[tuple[tuple[int, int, int], list[int]]] = []
    for key, _label, color in CHANNELS:
        if key not in channels:
            continue
        if key == "lum":
            bins = lum
        else:
            offset = {"r": 0, "g": 256, "b": 512}[key]
            bins = rgb[offset : offset + 256]
        series.append((color, bins))

    def scaled(v: int) -> float:
        return math.log1p(v) if log_scale else float(v)

    peak = max((scaled(v) for _color, bins in series for v in bins), default=0.0)
    if peak > 0.0:
        for color, bins in series:
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            points: list[tuple[float, float]] = [(0.0, float(h))]
            for i, v in enumerate(bins):
                x = i * (w - 1) / 255
                y = (h - 1) - (h - 2) * scaled(v) / peak
                points.append((x, y))
            points.append((float(w - 1), float(h)))
            draw.polygon(points, fill=(*color, 110))
            base = Image.alpha_composite(base, layer)
    return base.convert("RGB")
