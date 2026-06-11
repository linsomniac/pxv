"""Tests for the pure-PIL annotation rasterizer (no Tk, no display)."""

from __future__ import annotations

import math

import pytest

from pxv.annotation_render import arrow_head, scalable_font_available


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
