"""Tests for the pure-PIL annotation rasterizer (no Tk, no display)."""

from __future__ import annotations

import math

import pytest

from PIL import Image

from pxv.annotation_render import arrow_head, render_overlay, scalable_font_available
from pxv.annotations import Shape


def test_arrow_head_points_along_axis() -> None:
    tip, left, right = arrow_head((0.0, 0.0), (10.0, 0.0), 2.0)
    # length = max(3 * 2, 8.0) = 8 -> base midpoint at x=2, half-width 4.
    assert tip == (10.0, 0.0)
    assert left == pytest.approx((2.0, 4.0))
    assert right == pytest.approx((2.0, -4.0))


def test_arrow_head_length_scales_with_width() -> None:
    _tip, left, _right = arrow_head((0.0, 0.0), (10.0, 0.0), 4.0)
    # length = max(3 * 4, 8.0) = 12 -> base sits at x = -2, half-width 6.
    assert left == pytest.approx((-2.0, 6.0))


def test_arrow_head_minimum_length() -> None:
    # width 1 -> 3 * 1 < 8, so the 8 px minimum wins (same head as width 2).
    _tip, left, _right = arrow_head((0.0, 0.0), (10.0, 0.0), 1.0)
    assert left == pytest.approx((2.0, 4.0))


def test_arrow_head_follows_direction() -> None:
    tip, left, right = arrow_head((0.0, 0.0), (0.0, 10.0), 2.0)  # pointing down
    assert tip == (0.0, 10.0)
    assert left == pytest.approx((-4.0, 2.0))
    assert right == pytest.approx((4.0, 2.0))


def test_arrow_head_degenerate_points_are_finite() -> None:
    for x, y in arrow_head((5.0, 5.0), (5.0, 5.0), 2.0):  # zero-length arrow
        assert math.isfinite(x) and math.isfinite(y)


def test_scalable_font_available_returns_bool() -> None:
    assert scalable_font_available() in (True, False)


def test_arrow_head_oblique_geometry() -> None:
    p0, p1 = (0.0, 0.0), (10.0, 10.0)
    tip, left, right = arrow_head(p0, p1, 4.0)  # length 12
    base_mid = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
    assert math.hypot(tip[0] - base_mid[0], tip[1] - base_mid[1]) == pytest.approx(12.0)
    assert math.hypot(left[0] - right[0], left[1] - right[1]) == pytest.approx(
        12.0
    )  # base == length
    # base is perpendicular to the shaft direction
    ux, uy = (p1[0] - p0[0]) / math.hypot(10, 10), (p1[1] - p0[1]) / math.hypot(10, 10)
    assert (left[0] - right[0]) * ux + (left[1] - right[1]) * uy == pytest.approx(0.0)


def _column_alpha_count(img: Image.Image, x: int) -> int:
    """How many pixels in column x have non-zero alpha (== stroke thickness)."""
    return sum(1 for y in range(img.height) if img.getpixel((x, y))[3] > 0)


def test_overlay_is_exact_target_size_and_transparent() -> None:
    overlay = render_overlay([], (37, 23), 1.7)
    assert overlay.size == (37, 23)  # EXACTLY target_size, never derived
    assert overlay.mode == "RGBA"
    assert overlay.getchannel("A").getextrema() == (0, 0)  # fully transparent


def test_line_draws_color_and_width() -> None:
    s = Shape(tool="line", points=((2.0, 5.0), (18.0, 5.0)), color="#ff0000", width_px=2.0)
    overlay = render_overlay([s], (20, 10), 1.0)
    assert overlay.getpixel((10, 5)) == (255, 0, 0, 255)
    assert _column_alpha_count(overlay, 10) == 2  # width_px * scale = 2 px
    assert overlay.getpixel((10, 0))[3] == 0  # away from the stroke: clear


def test_opacity_becomes_alpha() -> None:
    s = Shape(
        tool="line", points=((2.0, 5.0), (18.0, 5.0)), color="#ff0000", width_px=3.0, opacity=0.5
    )
    overlay = render_overlay([s], (20, 10), 1.0)
    assert overlay.getpixel((10, 5)) == (255, 0, 0, 128)  # round(0.5 * 255)


def test_stroke_width_clamps_to_one_pixel() -> None:
    s = Shape(tool="line", points=((2.0, 5.0), (18.0, 5.0)), color="#ff0000", width_px=2.0)
    overlay = render_overlay([s], (5, 3), 0.25)  # quarter-size display
    # max(1, round(2 * 0.25)) = 1 -> exactly one row painted.
    assert _column_alpha_count(overlay, 2) == 1


def test_highlight_width_and_alpha() -> None:
    s = Shape(tool="highlight", points=((2.0, 10.0), (28.0, 10.0)), color="#ffff00", width_px=2.0)
    overlay = render_overlay([s], (30, 20), 1.0)
    assert overlay.getpixel((15, 10)) == (255, 255, 0, 102)  # round(0.4 * 255)
    assert _column_alpha_count(overlay, 15) == 8  # 4 x width_px


def test_rect_fill_vs_outline() -> None:
    outline = Shape(tool="rect", points=((2.0, 2.0), (17.0, 17.0)), color="#ff0000", width_px=1.0)
    o = render_overlay([outline], (20, 20), 1.0)
    assert o.getpixel((2, 10))[3] > 0  # left edge drawn
    assert o.getpixel((10, 10))[3] == 0  # hollow interior
    filled = Shape(
        tool="rect", points=((2.0, 2.0), (17.0, 17.0)), color="#ff0000", width_px=1.0, fill=True
    )
    o2 = render_overlay([filled], (20, 20), 1.0)
    assert o2.getpixel((10, 10))[3] > 0


def test_ellipse_fill_vs_outline() -> None:
    outline = Shape(
        tool="ellipse", points=((2.0, 2.0), (18.0, 18.0)), color="#ff0000", width_px=2.0
    )
    o = render_overlay([outline], (21, 21), 1.0)
    assert o.getpixel((10, 2))[3] > 0  # topmost point of the circle
    assert o.getpixel((10, 10))[3] == 0  # hollow center
    filled = Shape(
        tool="ellipse",
        points=((2.0, 2.0), (18.0, 18.0)),
        color="#ff0000",
        width_px=2.0,
        fill=True,
    )
    o2 = render_overlay([filled], (21, 21), 1.0)
    assert o2.getpixel((10, 10))[3] > 0


def test_arrow_renders_filled_head() -> None:
    s = Shape(tool="arrow", points=((2.0, 10.0), (16.0, 10.0)), color="#ff0000", width_px=2.0)
    overlay = render_overlay([s], (20, 20), 1.0)
    # Head triangle is (16,10), (8,14), (8,6): pixel (9,12) is inside the head
    # but well off the 2px shaft, so only a filled head can paint it.
    assert overlay.getpixel((9, 12))[3] > 0
    assert overlay.getpixel((5, 12))[3] == 0  # beside the shaft, before the head


def test_arrow_shaft_stops_at_head_base_so_tip_is_pointed() -> None:
    # width 4 -> head length 12: tip (36,20), base midpoint (24,20). A shaft
    # drawn all the way to the tip squares it off with its 4px butt end cap.
    s = Shape(tool="arrow", points=((4.0, 20.0), (36.0, 20.0)), color="#ff0000", width_px=4.0)
    overlay = render_overlay([s], (40, 40), 1.0)
    # Near the tip only the ~1px-tall head apex may paint, not the 4px shaft.
    assert overlay.getpixel((35, 19))[3] == 0
    assert overlay.getpixel((35, 22))[3] == 0
    assert overlay.getpixel((35, 20))[3] > 0  # the apex itself still reaches x=35
    assert overlay.getpixel((10, 20))[3] > 0  # shaft present along the body
    # No seam where the shaft meets the head base (x=24).
    assert overlay.getpixel((23, 20))[3] > 0
    assert overlay.getpixel((24, 20))[3] > 0
    assert overlay.getpixel((25, 20))[3] > 0


def test_arrow_shorter_than_head_draws_head_only() -> None:
    # Length 2 < head length 12: the shaft would either blunt the tip or point
    # backwards past the base, so it is skipped entirely.
    s = Shape(tool="arrow", points=((24.0, 20.0), (26.0, 20.0)), color="#ff0000", width_px=4.0)
    overlay = render_overlay([s], (40, 40), 1.0)
    assert overlay.getpixel((24, 22))[3] == 0  # old shaft corner below the taper
    assert overlay.getpixel((25, 22))[3] == 0
    assert overlay.getpixel((20, 20))[3] > 0  # head interior still filled
    assert overlay.getpixel((13, 20))[3] == 0  # nothing pokes behind the base


def test_arrow_shaft_threshold_is_image_space_at_any_scale() -> None:
    # Length 20 > head 12 in IMAGE space, but only 10 target px at scale 0.5:
    # the shaft must still draw — the threshold compares image-space lengths,
    # or a zoomed-out preview would diverge from the bake (preview == bake is
    # the module's core invariant).
    s = Shape(tool="arrow", points=((4.0, 20.0), (24.0, 20.0)), color="#ff0000", width_px=4.0)
    half = render_overlay([s], (20, 20), 0.5)
    # Shaft pixel between p0 (2,10) and the head base (6,10); transparent if
    # the comparison is (wrongly) made in target space.
    assert half.getpixel((4, 10))[3] > 0
    # And the head-only branch holds at scale != 1: a length-2 arrow stays
    # head-only at 2x, with no shaft corner beside the taper.
    short = Shape(tool="arrow", points=((24.0, 20.0), (26.0, 20.0)), color="#ff0000", width_px=4.0)
    double = render_overlay([short], (80, 80), 2.0)
    assert double.getpixel((50, 44))[3] == 0  # (25,22) at 2x: old shaft corner
    assert double.getpixel((40, 40))[3] > 0  # head interior
    assert double.getpixel((26, 40))[3] == 0  # nothing behind the base


def test_text_renders_pixels() -> None:
    s = Shape(
        tool="text",
        points=((2.0, 2.0),),
        color="#000000",
        width_px=1.0,
        text="Hi",
        font_px=16.0,
    )
    overlay = render_overlay([s], (64, 32), 1.0)
    assert overlay.getchannel("A").getbbox() is not None  # something was drawn


def test_out_of_bounds_shapes_clip_cleanly() -> None:
    s = Shape(tool="line", points=((-10.0, 5.0), (30.0, 5.0)), color="#0000ff", width_px=3.0)
    overlay = render_overlay([s], (20, 10), 1.0)
    assert overlay.size == (20, 10)
    assert overlay.getpixel((0, 5))[3] > 0  # in-bounds portion drawn edge-to-edge
    assert overlay.getpixel((19, 5))[3] > 0


def test_scale_equivalence_by_iou() -> None:
    # Same shapes at (N, scale=1.0) vs (2N, scale=2.0): geometry must be
    # equivalent across scales. Widths >= 4 px so the 1-px clamp can't skew it.
    shapes = [
        Shape(
            tool="rect",
            points=((4.0, 4.0), (36.0, 30.0)),
            color="#ff0000",
            width_px=4.0,
            fill=True,
        ),
        Shape(
            tool="ellipse",
            points=((8.0, 12.0), (32.0, 38.0)),
            color="#00ff00",
            width_px=4.0,
            fill=True,
        ),
        Shape(tool="line", points=((5.0, 35.0), (35.0, 5.0)), color="#0000ff", width_px=4.0),
        Shape(tool="arrow", points=((10.0, 20.0), (30.0, 20.0)), color="#ffffff", width_px=4.0),
    ]
    small = render_overlay(shapes, (40, 40), 1.0)
    big = render_overlay(shapes, (80, 80), 2.0)
    upscaled = small.resize((80, 80), Image.Resampling.NEAREST)
    a = upscaled.getchannel("A").tobytes()
    b = big.getchannel("A").tobytes()
    inter = sum(1 for x, y in zip(a, b) if x and y)
    union = sum(1 for x, y in zip(a, b) if x or y)
    assert union > 0
    assert inter / union > 0.8  # measured ~0.97 on Pillow 12; threshold is slack


def test_freehand_multipoint_with_duplicate_renders() -> None:
    s = Shape(
        tool="freehand",
        points=((2.0, 2.0), (10.0, 18.0), (10.0, 18.0), (20.0, 4.0)),
        color="#ff0000",
        width_px=4.0,
    )
    overlay = render_overlay([s], (24, 24), 1.0)
    assert overlay.getchannel("A").getbbox() is not None
    # The stroke reaches the last point (20, 4); PIL may land 1 px off the
    # exact tip due to rounding, so check the nearest reliably-hit pixel.
    assert overlay.getpixel((19, 4))[3] > 0  # reaches the last point


def test_text_scales_with_scale_factor() -> None:
    if not scalable_font_available():
        pytest.skip("bitmap fallback ignores size")
    s = Shape(
        tool="text", points=((2.0, 2.0),), color="#000000", width_px=1.0, text="Hi", font_px=16.0
    )
    small = render_overlay([s], (64, 32), 1.0).getchannel("A").getbbox()
    big = render_overlay([s], (128, 64), 2.0).getchannel("A").getbbox()
    assert small is not None and big is not None
    assert (big[2] - big[0]) > (small[2] - small[0])  # wider at scale 2


def test_highlight_alpha_composes_with_opacity() -> None:
    s = Shape(
        tool="highlight",
        points=((2.0, 10.0), (28.0, 10.0)),
        color="#ffff00",
        width_px=2.0,
        opacity=0.5,
    )
    overlay = render_overlay([s], (30, 20), 1.0)
    # alpha = round(0.4 * 0.5 * 255) = 51; the width stays 4 x width_px.
    assert overlay.getpixel((15, 10)) == (255, 255, 0, 51)
    assert _column_alpha_count(overlay, 15) == 8


def test_filled_rect_respects_opacity() -> None:
    s = Shape(
        tool="rect",
        points=((2.0, 2.0), (17.0, 17.0)),
        color="#ff0000",
        width_px=1.0,
        fill=True,
        opacity=0.25,
    )
    overlay = render_overlay([s], (20, 20), 1.0)
    assert overlay.getpixel((10, 10)) == (255, 0, 0, 64)  # round(0.25 * 255)


def test_text_scales_with_render_scale() -> None:
    s = Shape(
        tool="text",
        points=((2.0, 2.0),),
        color="#000000",
        width_px=1.0,
        text="Hello",
        font_px=16.0,
    )
    small = render_overlay([s], (120, 60), 1.0).getchannel("A").getbbox()
    big = render_overlay([s], (240, 120), 2.0).getchannel("A").getbbox()
    assert small is not None and big is not None
    if scalable_font_available():
        # The glyph footprint roughly doubles with the scale (scalable font).
        assert (big[2] - big[0]) > 1.5 * (small[2] - small[0])
        assert (big[3] - big[1]) > 1.5 * (small[3] - small[1])
