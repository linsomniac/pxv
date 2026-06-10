"""Tests for the pure crop-coordinate math extracted from CanvasView."""

from __future__ import annotations

from pxv.canvas_view import canvas_point_to_image_xy, selection_to_image_box


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
