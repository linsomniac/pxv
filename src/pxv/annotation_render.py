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
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from pxv.annotations import Shape

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


def _rgba(color: str, opacity: float) -> tuple[int, int, int, int]:
    """'#rrggbb' + opacity in [0, 1] -> RGBA tuple with the opacity as alpha."""
    return (
        int(color[1:3], 16),
        int(color[3:5], 16),
        int(color[5:7], 16),
        max(0, min(255, round(opacity * 255))),
    )


def _stroke_width(width_px: float, scale: float) -> int:
    """Image-space width -> target-space pixels; thin strokes clamp to 1 px."""
    return max(1, round(width_px * scale))


def _scaled(points: Sequence[tuple[float, float]], scale: float) -> list[tuple[float, float]]:
    return [(x * scale, y * scale) for x, y in points]


def _font(font_px: float, scale: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Pillow's embedded scalable font at target-space size, or bitmap fallback."""
    try:
        return ImageFont.load_default(size=max(1.0, font_px * scale))
    except (ImportError, OSError):  # FreeType-less/broken Pillow build: bitmap default
        return ImageFont.load_default()


def render_overlay(
    shapes: Sequence[Shape], target_size: tuple[int, int], scale: float
) -> Image.Image:
    """Rasterize shapes into a transparent RGBA image of EXACTLY target_size.

    `scale` only transforms image-space coordinates and widths into target
    space. The display preview passes the actual display image's .size and the
    zoom (never a derived size — get_display_image rounds independently); the
    bake passes working_image.size and 1.0. Same code path both ways, so the
    preview is faithful to the bake. Out-of-bounds geometry clips at the
    overlay edges.

    AIDEV-NOTE: One draw context, default (copy) ink semantics — a translucent
    shape REPLACES earlier shapes' overlay pixels where they overlap instead
    of blending with them (the base image still shows through either way).
    Chosen so per-shape alpha stays exact and strokes never self-darken at
    their own joints; accepted per the 2026-06-10 design.
    """
    overlay = Image.new("RGBA", target_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for shape in shapes:
        _draw_shape(draw, shape, scale)
    return overlay


def _draw_shape(draw: ImageDraw.ImageDraw, shape: Shape, scale: float) -> None:
    pts = _scaled(shape.points, scale)
    if shape.tool in ("freehand", "line"):
        ink = _rgba(shape.color, shape.opacity)
        draw.line(pts, fill=ink, width=_stroke_width(shape.width_px, scale), joint="curve")
    elif shape.tool == "arrow":
        ink = _rgba(shape.color, shape.opacity)
        draw.line(pts, fill=ink, width=_stroke_width(shape.width_px, scale), joint="curve")
        # Head computed in IMAGE space (its length is in image px), then scaled,
        # so preview and bake heads are geometrically equivalent.
        head = arrow_head(shape.points[0], shape.points[-1], shape.width_px)
        draw.polygon(_scaled(head, scale), fill=ink)
    elif shape.tool == "highlight":
        ink = _rgba(shape.color, HIGHLIGHT_ALPHA_FACTOR * shape.opacity)
        width = _stroke_width(HIGHLIGHT_WIDTH_FACTOR * shape.width_px, scale)
        draw.line(pts, fill=ink, width=width, joint="curve")
    elif shape.tool in ("rect", "ellipse"):
        ink = _rgba(shape.color, shape.opacity)
        x0, y0, x1, y1 = shape.bbox()  # normalizes the two drag corners
        box = (x0 * scale, y0 * scale, x1 * scale, y1 * scale)
        if shape.tool == "rect":
            if shape.fill:
                draw.rectangle(box, fill=ink)
            else:
                draw.rectangle(box, outline=ink, width=_stroke_width(shape.width_px, scale))
        else:
            if shape.fill:
                draw.ellipse(box, fill=ink)
            else:
                draw.ellipse(box, outline=ink, width=_stroke_width(shape.width_px, scale))
    elif shape.tool == "text":
        ink = _rgba(shape.color, shape.opacity)
        draw.text(pts[0], shape.text, fill=ink, font=_font(shape.font_px, scale))
