"""Tests for the pure annotation model (shapes, layer undo/redo, hit-testing, presets)."""

from __future__ import annotations

import dataclasses
import math

import pytest

from pxv.annotations import AnnotationLayer, Shape, hit_test, hit_tolerance, size_presets


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


def test_hit_test_topmost_wins() -> None:
    bottom = Shape(
        tool="rect", points=((0.0, 0.0), (10.0, 10.0)), color="#ff0000", width_px=2.0, fill=True
    )
    top = Shape(
        tool="rect", points=((5.0, 5.0), (15.0, 15.0)), color="#00ff00", width_px=2.0, fill=True
    )
    shapes = (bottom, top)
    assert hit_test(shapes, (7.0, 7.0), 1.0) == 1  # overlap -> topmost (later) wins
    assert hit_test(shapes, (2.0, 2.0), 1.0) == 0  # bottom only
    assert hit_test(shapes, (30.0, 30.0), 1.0) is None
    assert hit_test((), (0.0, 0.0), 5.0) is None  # empty layer


def test_hit_test_polyline_tolerance() -> None:
    line = _line(0.0, 0.0, 100.0, 0.0)
    assert hit_test((line,), (50.0, 3.0), 4.0) == 0  # within tol of the segment
    assert hit_test((line,), (50.0, 5.0), 4.0) is None  # just outside tol
    assert hit_test((line,), (110.0, 0.0), 4.0) is None  # beyond the endpoint


def test_hit_test_freehand_middle_segment() -> None:
    s = Shape(
        tool="freehand",
        points=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)),
        color="#ff0000",
        width_px=2.0,
    )
    assert hit_test((s,), (10.0, 5.0), 1.0) == 0  # on the second segment


def test_hit_test_rect_border_vs_interior() -> None:
    outline = Shape(tool="rect", points=((0.0, 0.0), (20.0, 20.0)), color="#ff0000", width_px=2.0)
    assert hit_test((outline,), (0.5, 10.0), 2.0) == 0  # near the left edge
    assert hit_test((outline,), (10.0, 10.0), 2.0) is None  # hollow interior
    filled = dataclasses.replace(outline, fill=True)
    assert hit_test((filled,), (10.0, 10.0), 2.0) == 0  # interior hits when filled


def test_hit_test_ellipse_border_vs_interior() -> None:
    outline = Shape(
        tool="ellipse", points=((0.0, 0.0), (20.0, 20.0)), color="#ff0000", width_px=2.0
    )
    assert hit_test((outline,), (10.0, 0.5), 2.0) == 0  # on top of the circle
    assert hit_test((outline,), (10.0, 10.0), 2.0) is None  # hollow center
    assert hit_test((outline,), (1.0, 1.0), 2.0) is None  # bbox corner, off the curve
    filled = dataclasses.replace(outline, fill=True)
    assert hit_test((filled,), (10.0, 10.0), 2.0) == 0


def test_hit_test_text_uses_heuristic_bbox() -> None:
    s = Shape(
        tool="text",
        points=((10.0, 20.0),),
        color="#000000",
        width_px=2.0,
        text="hi",
        font_px=10.0,
    )
    assert hit_test((s,), (15.0, 25.0), 1.0) == 0  # inside the (10,20)-(22,32) bbox
    assert hit_test((s,), (25.0, 25.0), 1.0) is None


def test_size_presets_formulas() -> None:
    p = size_presets(4000)
    assert p.widths == (5.0, 10.0, 20.0)  # medium = 4000/400, thin = /2, thick = *2
    assert p.fonts == (100.0 / 1.5, 100.0, 150.0)  # medium = 4000/40


def test_size_presets_minimums() -> None:
    p = size_presets(100)
    assert p.widths == (1.0, 2.0, 4.0)  # medium floor 2.0, thin floor 1.0
    assert p.fonts == (8.0, 12.0, 18.0)  # medium floor 12.0


def test_hit_tolerance_formula() -> None:
    assert hit_tolerance(2.0, 2.0) == 3.0  # 6/zoom wins
    assert hit_tolerance(1.0, 20.0) == 10.0  # width/2 wins


def test_layer_add_bumps_revision_monotonically() -> None:
    layer = AnnotationLayer()
    assert not layer.shapes and layer.selected is None and layer.revision == 0
    layer.add(_line(0.0, 0.0, 1.0, 1.0))
    assert len(layer.shapes) == 1 and layer.revision > 0
    r1 = layer.revision
    layer.add(_line(1.0, 1.0, 2.0, 2.0))
    assert len(layer.shapes) == 2 and layer.revision > r1


def test_layer_delete_selected() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 10.0, 0.0))
    layer.add(_line(0.0, 5.0, 10.0, 5.0))
    layer.selected = 0
    r = layer.revision
    layer.delete_selected()
    assert len(layer.shapes) == 1
    assert layer.shapes[0].points[0] == (0.0, 5.0)  # the OTHER shape survived
    assert layer.selected is None and layer.revision > r


def test_layer_delete_without_selection_is_noop() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 1.0, 1.0))
    r = layer.revision
    layer.delete_selected()
    assert len(layer.shapes) == 1 and layer.revision == r


def test_layer_select_at_delegates_to_hit_test() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 100.0, 0.0))
    r = layer.revision
    assert layer.select_at((50.0, 1.0), 4.0) == 0
    assert layer.selected == 0
    assert layer.select_at((50.0, 50.0), 4.0) is None  # empty space deselects
    assert layer.selected is None
    assert layer.revision == r  # selection isn't rendered -> no overlay re-render


def test_layer_undo_redo_roundtrip() -> None:
    layer = AnnotationLayer()
    a, b = _line(0.0, 0.0, 1.0, 1.0), _line(2.0, 2.0, 3.0, 3.0)
    layer.add(a)
    layer.add(b)
    assert layer.undo() is True
    assert tuple(layer.shapes) == (a,)
    assert layer.undo() is True
    assert not layer.shapes
    assert layer.undo() is False  # stack exhausted -> caller consumes the key
    assert layer.redo() is True
    assert tuple(layer.shapes) == (a,)
    assert layer.redo() is True
    assert tuple(layer.shapes) == (a, b)
    assert layer.redo() is False


def test_layer_undo_redo_bump_revision() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 1.0, 1.0))
    r = layer.revision
    layer.undo()
    assert layer.revision > r
    r = layer.revision
    layer.redo()
    assert layer.revision > r


def test_layer_redo_cleared_by_new_action() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 1.0, 1.0))
    layer.undo()
    layer.add(_line(2.0, 2.0, 3.0, 3.0))
    assert not layer._redo_stack
    assert layer.redo() is False


def test_layer_replace_selected_coalesces() -> None:
    layer = AnnotationLayer()
    original = _line(0.0, 0.0, 10.0, 0.0)
    layer.add(original)
    layer.selected = 0
    r = layer.revision
    layer.replace_selected(original.translated(1.0, 0.0))
    r1 = layer.revision
    assert r1 > r  # every change re-renders the overlay (strictly increasing)
    layer.replace_selected(original.translated(2.0, 0.0))
    r2 = layer.revision
    assert r2 > r1
    layer.replace_selected(original.translated(3.0, 0.0))
    assert layer.revision > r2
    assert layer.shapes[0].points[0] == (3.0, 0.0)
    assert layer.undo() is True  # the whole run is ONE undo step
    assert tuple(layer.shapes) == (original,)
    assert layer.undo() is True
    assert not layer.shapes


def test_layer_coalescing_breaks_on_reselect() -> None:
    layer = AnnotationLayer()
    original = _line(0.0, 0.0, 10.0, 0.0)
    layer.add(original)
    layer.select_at((5.0, 0.0), 2.0)
    layer.replace_selected(original.translated(1.0, 0.0))
    layer.select_at((5.0, 1.0), 2.0)  # re-select the same shape
    layer.replace_selected(original.translated(2.0, 0.0))
    layer.undo()
    assert layer.shapes[0].points[0] == (1.0, 0.0)  # only the second run undone
    layer.undo()
    assert tuple(layer.shapes) == (original,)


def test_layer_replace_without_selection_is_noop() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 1.0, 1.0))
    r = layer.revision
    layer.replace_selected(_line(5.0, 5.0, 6.0, 6.0))
    assert layer.shapes[0].points[0] == (0.0, 0.0) and layer.revision == r


def test_layer_undo_clears_selection() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 1.0, 1.0))
    layer.selected = 0
    layer.undo()
    assert layer.selected is None


# --- Finding 1: eccentric-ellipse hit-test regression ---


def test_hit_test_eccentric_ellipse_not_overgenerous() -> None:
    """The old tol/min(rx,ry) band was up to rx/ry× too generous along the major
    axis of a flat ellipse. The gradient-normalized formula must reject probes
    that are clearly inside the curve and only accept ones near the boundary."""
    flat = Shape(tool="ellipse", points=((0.0, 0.0), (200.0, 10.0)), color="#ff0000", width_px=2.0)
    # A point roughly 40 px inside the right side of a 200×10 ellipse must miss.
    assert hit_test((flat,), (160.0, 5.0), 3.0) is None
    # A point very close to the right tip of the curve must hit.
    assert hit_test((flat,), (199.0, 5.0), 3.0) == 0
    # Filled interior must hit.
    filled = dataclasses.replace(flat, fill=True)
    assert hit_test((filled,), (160.0, 5.0), 3.0) == 0
    # A point well outside the ellipse (right of the tip) must miss even when filled.
    assert hit_test((filled,), (220.0, 5.0), 3.0) is None


# --- Finding 2: degenerate geometry tests ---


def test_hit_test_single_point_freehand() -> None:
    """A single-point freehand (click without drag) is treated as a polyline of
    one vertex; it should be hit within tol and miss outside."""
    dot = Shape(tool="freehand", points=((50.0, 50.0),), color="#ff0000", width_px=2.0)
    assert hit_test((dot,), (51.0, 50.0), 3.0) == 0  # within tol
    assert hit_test((dot,), (60.0, 50.0), 3.0) is None  # outside tol


def test_hit_test_zero_length_line() -> None:
    """A zero-length line (both endpoints equal) behaves like a single point."""
    zerolen = Shape(
        tool="line", points=((30.0, 30.0), (30.0, 30.0)), color="#ff0000", width_px=2.0
    )
    assert hit_test((zerolen,), (31.0, 30.0), 3.0) == 0  # within tol
    assert hit_test((zerolen,), (40.0, 30.0), 3.0) is None  # outside tol


def test_translated_text_shape_bbox_follows_move() -> None:
    """translated() on a text shape must move its bbox anchor."""
    s = Shape(
        tool="text",
        points=((10.0, 20.0),),
        color="#000000",
        width_px=2.0,
        text="hi",
        font_px=10.0,
    )
    moved = s.translated(5.0, -10.0)
    x0, y0, x1, y1 = moved.bbox()
    assert x0 == pytest.approx(15.0)
    assert y0 == pytest.approx(10.0)
    # width and height are unchanged
    orig_bbox = s.bbox()
    assert (x1 - x0) == pytest.approx(orig_bbox[2] - orig_bbox[0])
    assert (y1 - y0) == pytest.approx(orig_bbox[3] - orig_bbox[1])


def test_hit_tolerance_zero_zoom_guard() -> None:
    """zoom=0 must not raise ZeroDivisionError; it is clamped to a minimum."""
    result = hit_tolerance(0.0, 2.0)
    assert math.isfinite(result) and result > 0
