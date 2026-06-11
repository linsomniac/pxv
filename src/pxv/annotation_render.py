"""Pure-PIL rasterization of annotation shapes onto an RGBA overlay.

AIDEV-NOTE: NO Tk in this module. render_overlay is the ONE rasterizer used by
both the zoomed display preview and the full-resolution bake (2026-06-10
annotations design): target_size is honored EXACTLY and `scale` only
transforms image-space coordinates/widths into target space — the preview
passes the actual display image's .size with the zoom, the bake passes
working_image.size with 1.0. Never render full-res and downscale.
"""

from __future__ import annotations

import math

from PIL import ImageFont

# Highlighter: a round-joint stroke 4x the nominal width at 0.4x opacity.
HIGHLIGHT_WIDTH_FACTOR = 4.0
HIGHLIGHT_ALPHA_FACTOR = 0.4


def arrow_head(
    p0: tuple[float, float], p1: tuple[float, float], width_px: float
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Filled triangular head at p1: (tip, base_left, base_right), image coords.

    Length max(3.0 * width_px, 8.0) image px, oriented along p0 -> p1; the
    base is as wide as the head is long. Pure geometry, unit-testable.
    base_left/base_right follow y-up math convention (visually flipped in
    y-down image coords — harmless for a filled polygon).
    """
    length = max(3.0 * width_px, 8.0)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    norm = math.hypot(dx, dy)
    if norm == 0.0:
        ux, uy = 1.0, 0.0  # degenerate zero-length arrow: point right
    else:
        ux, uy = dx / norm, dy / norm
    bx, by = p1[0] - ux * length, p1[1] - uy * length  # base midpoint
    half = length / 2.0
    return (
        (p1[0], p1[1]),
        (bx - uy * half, by + ux * half),
        (bx + uy * half, by - ux * half),
    )


def scalable_font_available() -> bool:
    """True when Pillow's embedded scalable font loads (FreeType present).

    AIDEV-NOTE: ImageFont.load_default(size=...) (Pillow 10.1+, the pyproject
    floor) needs the FreeType extension; without it Pillow raises ImportError
    and _font() silently falls back to the fixed-size bitmap default. This
    module stays pure/silent about the fallback — the palette consults this
    predicate and shows a one-time title-bar hint (Phase 4).
    """
    try:
        ImageFont.load_default(size=12.0)
    except (ImportError, OSError):
        return False
    return True
