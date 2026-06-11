"""Tests for the pure annotation model (shapes, layer undo/redo, hit-testing, presets)."""

from __future__ import annotations

import dataclasses

import pytest

from pxv.annotations import Shape


def _line(x0: float, y0: float, x1: float, y1: float) -> Shape:
    return Shape(tool="line", points=((x0, y0), (x1, y1)), color="#ff0000", width_px=2.0)


def test_shape_translated_moves_points_only() -> None:
    s = _line(1.0, 2.0, 3.0, 4.0)
    t = s.translated(10.0, -2.0)
    assert t.points == ((11.0, 0.0), (13.0, 2.0))
    assert (t.tool, t.color, t.width_px) == (s.tool, s.color, s.width_px)
    assert s.points == ((1.0, 2.0), (3.0, 4.0))  # original untouched (frozen)


def test_shape_bbox_from_points() -> None:
    s = Shape(
        tool="freehand",
        points=((5.0, 9.0), (1.0, 2.0), (8.0, 4.0)),
        color="#00ff00",
        width_px=1.0,
    )
    assert s.bbox() == (1.0, 2.0, 8.0, 9.0)


def test_shape_bbox_text_heuristic() -> None:
    s = Shape(
        tool="text",
        points=((10.0, 20.0),),
        color="#000000",
        width_px=2.0,
        text="hi",
        font_px=10.0,
    )
    # width = 0.6 * font_px * len(text), height = 1.2 * font_px, top-left anchored.
    assert s.bbox() == (10.0, 20.0, 22.0, 32.0)


def test_shape_is_frozen() -> None:
    s = _line(0.0, 0.0, 1.0, 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.color = "#0000ff"  # type: ignore[misc]
