"""Tests for the pure crop-coordinate math extracted from CanvasView."""

from __future__ import annotations

import pytest

from pxv.canvas_view import (
    canvas_point_to_image_xy,
    canvas_point_to_image_xy_f,
    image_xy_to_canvas_point,
    selection_to_image_box,
)


def test_box_accounts_for_centering_offset() -> None:
    # 100x100 image shown 1:1 inside a 200x200 canvas -> 50px border each side.
    box = selection_to_image_box(
        selection=(60, 60, 160, 160),
        working_size=(100, 100),
        display_size=(100, 100),
        canvas_size=(200, 200),
        zoom=1.0,
    )
    assert box == (10, 10, 100, 100)


def test_box_divides_by_zoom() -> None:
    box = selection_to_image_box(
        selection=(0, 0, 200, 200),
        working_size=(100, 100),
        display_size=(200, 200),
        canvas_size=(200, 200),
        zoom=2.0,
    )
    assert box == (0, 0, 100, 100)


def test_box_clamps_to_image_bounds() -> None:
    box = selection_to_image_box(
        selection=(-20, -20, 50, 50),
        working_size=(100, 100),
        display_size=(100, 100),
        canvas_size=(100, 100),
        zoom=1.0,
    )
    assert box == (0, 0, 50, 50)


def test_degenerate_selection_returns_none() -> None:
    box = selection_to_image_box(
        selection=(50, 50, 50, 60),
        working_size=(100, 100),
        display_size=(100, 100),
        canvas_size=(100, 100),
        zoom=1.0,
    )
    assert box is None


def test_point_maps_through_centering_offset() -> None:
    # 100x100 image displayed 1:1 on a 300x300 canvas -> offset (100, 100).
    assert canvas_point_to_image_xy((150, 150), (100, 100), (100, 100), (300, 300), 1.0) == (
        50,
        50,
    )


def test_point_maps_through_zoom() -> None:
    # 100x100 image at 2x -> display 200x200 on a 200x200 canvas, no offset.
    assert canvas_point_to_image_xy((100, 100), (100, 100), (200, 200), (200, 200), 2.0) == (
        50,
        50,
    )


def test_point_outside_image_returns_none() -> None:
    assert canvas_point_to_image_xy((10, 10), (100, 100), (100, 100), (300, 300), 1.0) is None
    assert canvas_point_to_image_xy((299, 299), (100, 100), (100, 100), (300, 300), 1.0) is None


def test_point_f_is_float_and_unclamped() -> None:
    # Same geometry as test_point_maps_through_centering_offset, float result.
    assert canvas_point_to_image_xy_f((150.0, 150.0), (100, 100), (300, 300), 1.0) == (50.0, 50.0)
    # Outside the image: NO None case — out-of-image points pass through
    # unclamped (negative coords allowed); clipping happens at render time.
    assert canvas_point_to_image_xy_f((10.0, 10.0), (100, 100), (300, 300), 1.0) == (-90.0, -90.0)


def test_point_f_keeps_subpixel_precision() -> None:
    # 100x100 image at 2x on a 200x200 canvas: canvas (101, 101) -> (50.5, 50.5)
    # where the int helper would truncate to (50, 50).
    assert canvas_point_to_image_xy_f((101.0, 101.0), (200, 200), (200, 200), 2.0) == (50.5, 50.5)


def test_image_xy_to_canvas_point_is_inverse_mapping() -> None:
    # 100x100 image displayed 1:1 on a 300x300 canvas -> offset (100, 100).
    assert image_xy_to_canvas_point((50.0, 50.0), (100, 100), (300, 300), 1.0) == (150.0, 150.0)


def test_point_f_round_trips_with_inverse() -> None:
    for zoom in (0.33, 1.0, 2.5):
        for pt in ((0.0, 0.0), (123.4, 56.7), (-20.0, 310.0)):
            cp = image_xy_to_canvas_point(pt, (160, 90), (400, 300), zoom)
            back = canvas_point_to_image_xy_f(cp, (160, 90), (400, 300), zoom)
            assert back == pytest.approx(pt)
