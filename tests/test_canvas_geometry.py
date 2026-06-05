"""Tests for the pure crop-coordinate math extracted from CanvasView."""

from __future__ import annotations

from pxv.canvas_view import selection_to_image_box


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
