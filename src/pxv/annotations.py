"""Pure annotation data model: shapes, layer state, hit-testing, size presets.

AIDEV-NOTE: NO Tk and NO PIL in this module — everything is display-free and
unit-tested headlessly (rasterization lives in annotation_render.py). Geometry
is in IMAGE coordinates as unclamped floats: out-of-image points pass through
and clipping happens at render time (see the 2026-06-10 annotations design).
Shape is FROZEN on purpose: AnnotationLayer's undo stack holds plain
shapes-tuples, which is only alias-safe because shapes can never mutate.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

Tool = Literal["freehand", "line", "arrow", "rect", "ellipse", "highlight", "text"]

# AIDEV-NOTE: Text bbox is a pure heuristic (PIL font metrics are forbidden in
# this module): width 0.6 * font_px per character, height 1.2 * font_px,
# anchored top-left at the click point. Approximate by design — used only for
# hit-testing and the selection marker, never for rendering.
TEXT_WIDTH_FACTOR = 0.6
TEXT_HEIGHT_FACTOR = 1.2


@dataclass(frozen=True)
class Shape:
    """One annotation. points by tool: freehand/highlight many, line/arrow/
    rect/ellipse exactly 2, text exactly 1 (the top-left anchor)."""

    tool: Tool
    points: tuple[tuple[float, float], ...]  # image coords, unclamped floats
    color: str  # "#rrggbb"
    width_px: float  # stroke width in image pixels
    fill: bool = False  # rect/ellipse only
    opacity: float = 1.0  # 0.0-1.0
    text: str = ""  # text tool only
    font_px: float = 0.0  # text tool only

    def translated(self, dx: float, dy: float) -> Shape:
        """A copy moved by (dx, dy) image pixels."""
        return replace(self, points=tuple((x + dx, y + dy) for x, y in self.points))

    def bbox(self) -> tuple[float, float, float, float]:
        """(x0, y0, x1, y1) in image coords; text uses the heuristic above."""
        if self.tool == "text":
            x, y = self.points[0]
            return (
                x,
                y,
                x + TEXT_WIDTH_FACTOR * self.font_px * len(self.text),
                y + TEXT_HEIGHT_FACTOR * self.font_px,
            )
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))


def _segment_distance(
    xy: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance from xy to the closed segment a-b."""
    px, py = xy
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    if den == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _polyline_distance(points: tuple[tuple[float, float], ...], xy: tuple[float, float]) -> float:
    if len(points) == 1:
        return math.hypot(xy[0] - points[0][0], xy[1] - points[0][1])
    return min(_segment_distance(xy, points[i], points[i + 1]) for i in range(len(points) - 1))


def _shape_hit(shape: Shape, xy: tuple[float, float], tol: float) -> bool:
    if shape.tool in ("freehand", "highlight", "line", "arrow"):
        return _polyline_distance(shape.points, xy) <= tol
    if shape.tool == "text":
        x0, y0, x1, y1 = shape.bbox()
        return x0 <= xy[0] <= x1 and y0 <= xy[1] <= y1
    x0, y0, x1, y1 = shape.bbox()  # rect/ellipse: bbox() normalizes the 2 corners
    if shape.tool == "rect":
        if shape.fill:
            return x0 - tol <= xy[0] <= x1 + tol and y0 - tol <= xy[1] <= y1 + tol
        corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))
        return min(_segment_distance(xy, corners[i], corners[i + 1]) for i in range(4)) <= tol
    # AIDEV-NOTE: Ellipse hit via gradient-normalized distance. r is the
    # normalised radius (1.0 = on the curve). True Euclidean distance to the
    # ellipse boundary is approximated as |r - 1| * r / |∇r|, where
    # |∇r| = hypot(x/rx², y/ry²) is the spatial gradient of r at the probe
    # point. This approximation is tight near the curve and handles eccentric
    # ellipses correctly (unlike the old tol/min(rx,ry) band, which was up to
    # rx/ry× too generous along the major axis of a flat ellipse).
    # At the exact centre the gradient is ~0; we guard that by treating the
    # centre as "hit" for filled shapes (distance = min(rx,ry)) and "miss" for
    # outline shapes. Arrows hit-test on the shaft polyline only — the head
    # wings that extend beyond tol do not contribute to selection.
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rx, ry = max((x1 - x0) / 2.0, 1e-6), max((y1 - y0) / 2.0, 1e-6)
    r = math.hypot((xy[0] - cx) / rx, (xy[1] - cy) / ry)
    gx = (xy[0] - cx) / rx**2
    gy = (xy[1] - cy) / ry**2
    grad = math.hypot(gx, gy)
    if grad < 1e-12:
        # Exact centre: treat as interior for fill, miss for outline.
        if shape.fill:
            return True
        return False
    curve_dist = abs(r - 1.0) * r / grad
    if shape.fill:
        return r <= 1.0 or curve_dist <= tol
    return curve_dist <= tol


def hit_test(shapes: Sequence[Shape], xy: tuple[float, float], tol: float) -> int | None:
    """Topmost shape under xy (z = insertion order), or None.

    Distance-to-polyline for freehand/highlight/line/arrow (arrows hit-test on
    the shaft polyline only — head wings beyond tol do not select); border (or
    interior when filled) for rect/ellipse; heuristic bbox for text. tol is in
    image pixels; callers should use hit_tolerance().
    """
    for i in range(len(shapes) - 1, -1, -1):
        if _shape_hit(shapes[i], xy, tol):
            return i
    return None


@dataclass(frozen=True)
class SizePresets:
    """Auto-scaled stroke widths and font sizes for the palette."""

    widths: tuple[float, float, float]  # thin, medium, thick
    fonts: tuple[float, float, float]  # small, medium, large


def size_presets(image_long_side: int) -> SizePresets:
    """Presets scaled from the image's longest side (2026-06-10 design formula)."""
    medium_w = max(2.0, image_long_side / 400)
    medium_f = max(12.0, image_long_side / 40)
    return SizePresets(
        widths=(max(1.0, medium_w / 2), medium_w, medium_w * 2),
        fonts=(medium_f / 1.5, medium_f, medium_f * 1.5),
    )


def hit_tolerance(zoom: float, width_px: float) -> float:
    """Image-px hit tolerance: max(shape-independent 6.0 / zoom, width_px / 2).

    zoom is clamped to a minimum of 1e-6 so degenerate windows (zoom 0.0 from
    zoom_fit on an empty canvas) never raise ZeroDivisionError.
    """
    zoom = max(zoom, 1e-6)
    return max(6.0 / zoom, width_px / 2)


class AnnotationLayer:
    """Ordered shapes (z = insertion order), selection, in-mode undo/redo.

    AIDEV-NOTE: Mutators push the PRIOR shapes-tuple onto an undo stack (alias-
    safe because Shape is frozen) and bump `revision` — the overlay cache key:
    the app re-rasterizes only when it changes, so every change to RENDERED
    content MUST bump it. Selection is not rendered into the overlay (the
    selection marker is a Tk item), so select_at does not bump. Consecutive
    replace_selected calls on the same index COALESCE into one undo state
    (slider drags / shape moves are one step, not dozens); any other mutation
    or a select_at breaks the run via _coalesce_index.
    """

    def __init__(self) -> None:
        self.shapes: tuple[Shape, ...] = ()
        self.selected: int | None = None
        self.revision: int = 0
        self._undo_stack: list[tuple[Shape, ...]] = []
        self._redo_stack: list[tuple[Shape, ...]] = []
        self._coalesce_index: int | None = None  # target of the active replace run

    def _push_undo(self) -> None:
        """Record the prior state; any new action invalidates the redo branch."""
        self._undo_stack.append(self.shapes)
        self._redo_stack.clear()

    def add(self, shape: Shape) -> None:
        self._push_undo()
        self._coalesce_index = None
        self.shapes = (*self.shapes, shape)
        self.revision += 1

    def delete_selected(self) -> None:
        """Delete the selected shape; no-op without a selection."""
        if self.selected is None:
            return
        self._push_undo()
        self._coalesce_index = None
        i = self.selected
        self.shapes = self.shapes[:i] + self.shapes[i + 1 :]
        self.selected = None
        self.revision += 1

    def replace_selected(self, shape: Shape) -> None:
        """Restyle / move / re-text the selected shape; no-op without a selection.

        Consecutive calls on the same index coalesce into ONE undo state.
        """
        if self.selected is None:
            return
        if self._coalesce_index != self.selected:
            self._push_undo()
            self._coalesce_index = self.selected
        i = self.selected
        self.shapes = self.shapes[:i] + (shape,) + self.shapes[i + 1 :]
        self.revision += 1

    def select_at(self, xy: tuple[float, float], tol: float) -> int | None:
        """Select the topmost shape under xy (None deselects); delegates to hit_test."""
        self.selected = hit_test(self.shapes, xy, tol)
        self._coalesce_index = None  # re-selecting starts a fresh replace run
        return self.selected

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self.shapes)
        self.shapes = self._undo_stack.pop()
        self.selected = None  # the restored tuple may not contain the old index
        self._coalesce_index = None
        self.revision += 1
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self.shapes)
        self.shapes = self._redo_stack.pop()
        self.selected = None
        self._coalesce_index = None
        self.revision += 1
        return True
