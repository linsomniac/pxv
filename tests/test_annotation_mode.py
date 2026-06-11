"""DISPLAY-gated tests for draw mode: canvas plumbing, palette, gating, prompts.

AIDEV-NOTE: Real Tk widgets — skipped headlessly like test_enhancement_dialog_ui.
Run under Xvfb: `Xvfb :99 &` then `DISPLAY=:99 uv run pytest <this file>`.
"""

from __future__ import annotations

import os
import types

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requires an X display (Tk widget test)"
)


class _RecordingSession:
    """Minimal stand-in satisfying the canvas-facing AnnotationSession protocol."""

    def __init__(self) -> None:
        self.events: list[tuple[str, tuple[float, float]]] = []
        self.dragging = False

    @property
    def is_dragging(self) -> bool:
        return self.dragging

    def on_press(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("press", image_xy))

    def on_drag(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("drag", image_xy))

    def on_release(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("release", image_xy))


def _canvas_view(root):  # noqa: ANN001, ANN202 - Tk fixture helper
    """A bare 300x300 CanvasView pretending to show a 100x100 image at zoom 1."""
    from pxv.canvas_view import CanvasView

    view = CanvasView(root)
    view.canvas.config(width=300, height=300)
    root.update()  # an unmapped canvas reports winfo_width() == 1
    view._display_width = 100
    view._display_height = 100
    view.zoom = 1.0
    return view


def test_session_armed_forwards_events_and_suppresses_rubber_band() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        session = _RecordingSession()
        view.set_annotation_session(session)
        assert view.canvas.cget("cursor") == "pencil"
        view._on_press(types.SimpleNamespace(x=150, y=150))
        view._on_drag(types.SimpleNamespace(x=180, y=160))
        view._on_release(types.SimpleNamespace(x=180, y=160))
        # 300x300 canvas, 100x100 display at zoom 1 -> centering offset 100.
        assert session.events == [
            ("press", (50.0, 50.0)),
            ("drag", (80.0, 60.0)),
            ("release", (80.0, 60.0)),
        ]
        assert view._rb_start is None and not view.has_selection()
    finally:
        root.destroy()


def test_session_entry_clears_selection_and_exit_restores_cursor() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view._selection = (10, 10, 50, 50)
        view.set_annotation_session(_RecordingSession())
        assert not view.has_selection()  # stale canvas coords never survive entry
        view.set_annotation_session(None)
        assert view.canvas.cget("cursor") == "crosshair"
        # Disarmed: events run the normal rubber-band path again.
        view._on_press(types.SimpleNamespace(x=10, y=10))
        assert view._rb_start is not None
    finally:
        root.destroy()


def test_preview_shape_converts_image_space_and_is_single_item() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_preview_shape("line", [(0.0, 0.0), (50.0, 50.0)], "#ff0000", 2.0)
        assert view._preview_id is not None
        # Image (0,0)/(50,50) -> canvas (100,100)/(150,150) via the centering offset.
        assert view.canvas.coords(view._preview_id) == [100.0, 100.0, 150.0, 150.0]
        first_id = view._preview_id
        view.set_preview_shape("rect", [(0.0, 0.0), (10.0, 10.0)], "#00ff00", 2.0)
        assert view._preview_id != first_id
        assert len(view.canvas.find_withtag("all")) == 1  # ONE item: old one deleted
        view.clear_preview()
        assert view._preview_id is None
        assert len(view.canvas.find_withtag("all")) == 0
    finally:
        root.destroy()


def test_wheel_ignored_while_session_drag_in_flight() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        session = _RecordingSession()
        view.set_annotation_session(session)
        scrolls: list[tuple[int, str]] = []
        view.canvas.yview_scroll = lambda n, what: scrolls.append((n, what))  # type: ignore[method-assign]
        session.dragging = True
        assert view._on_mouse_wheel(types.SimpleNamespace(num=4, delta=0, state=0)) == "break"
        assert scrolls == []  # the wheel is pxv's only pan input: dead mid-drag
        session.dragging = False
        view._on_mouse_wheel(types.SimpleNamespace(num=4, delta=0, state=0))
        assert scrolls == [(-1, "units")]
    finally:
        root.destroy()


def test_event_image_xy_accounts_for_scroll_offset() -> None:
    """_event_image_xy converts canvas coords using canvasx/canvasy (scroll-aware)."""
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        # Set up a scrollregion larger than the canvas so scrolling is possible.
        view.canvas.config(scrollregion=(0, 0, 600, 600))
        root.update()
        # Scroll 100 px to the right (xview_scroll uses "units"; configure xscrollincrement).
        view.canvas.config(xscrollincrement=1)
        view.canvas.xview_scroll(100, "units")
        root.update()
        # An event at widget-relative (150, 150) now refers to canvas x=250 because of scroll.
        # image_xy = (canvas_xy - centering_offset) / zoom = (250 - 100, 150 - 100) / 1.0
        event = types.SimpleNamespace(x=150, y=150)
        ix, iy = view._event_image_xy(event)
        assert ix == pytest.approx(150.0)  # 250 - 100
        assert iy == pytest.approx(50.0)  # 150 - 100
    finally:
        root.destroy()


def test_disarm_mid_drag_race_no_exception_no_rubber_band() -> None:
    """Disarming session mid-drag: subsequent drag/release events are safely no-ops."""
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        session = _RecordingSession()
        view.set_annotation_session(session)
        # Start a drag.
        view._on_press(types.SimpleNamespace(x=150, y=150))
        view._on_drag(types.SimpleNamespace(x=180, y=160))
        # Disarm: simulates set_annotation_session(None) being called (e.g. palette close).
        view.set_annotation_session(None)
        # Residual events after disarm must not raise or create a rubber band.
        view._on_drag(types.SimpleNamespace(x=200, y=200))
        view._on_release(types.SimpleNamespace(x=200, y=200))
        assert view._rb_start is None
        assert view._preview_id is None
    finally:
        root.destroy()


def test_preview_kinds_coverage() -> None:
    """set_preview_shape creates exactly one item for each kind; coords length matches."""
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        # polyline: 3 points -> 6 coords (3 x,y pairs)
        view.set_preview_shape("polyline", [(0.0, 0.0), (25.0, 25.0), (50.0, 0.0)], "#ff0000", 2.0)
        assert view._preview_id is not None
        assert len(view.canvas.coords(view._preview_id)) == 6
        view.clear_preview()
        # arrow: 2 points -> 4 coords
        view.set_preview_shape("arrow", [(0.0, 0.0), (50.0, 50.0)], "#00ff00", 2.0)
        assert view._preview_id is not None
        assert len(view.canvas.coords(view._preview_id)) == 4
        view.clear_preview()
        # ellipse: 2 points -> 4 coords
        view.set_preview_shape("ellipse", [(0.0, 0.0), (50.0, 50.0)], "#0000ff", 2.0)
        assert view._preview_id is not None
        assert len(view.canvas.coords(view._preview_id)) == 4
        view.clear_preview()
        # single-point dot branch: 1 point doubled -> 4 coords
        view.set_preview_shape("line", [(25.0, 25.0)], "#ffffff", 2.0)
        assert view._preview_id is not None
        assert len(view.canvas.coords(view._preview_id)) == 4
        view.clear_preview()
    finally:
        root.destroy()
