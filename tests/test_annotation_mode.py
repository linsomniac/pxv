"""DISPLAY-gated tests for draw mode: canvas plumbing, palette, gating, prompts.

AIDEV-NOTE: Real Tk widgets — skipped headlessly like test_enhancement_dialog_ui.
Run under Xvfb: `Xvfb :99 &` then `DISPLAY=:99 uv run pytest <this file>`.
"""

from __future__ import annotations

import os
import types

import pytest
from PIL import Image

from pxv import commands

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


def _make_app(tmp_path, count=1):  # noqa: ANN001, ANN201 - Tk fixture helper
    """Real PxvApp over `count` synthetic 100x80 PNGs, first one loaded (zoom 1)."""
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    colors = [(0, 0, 255), (0, 200, 0), (200, 200, 0)]
    paths = []
    for i in range(count):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (100, 80), colors[i % 3]).save(p)
        paths.append(p)
    root = tk.Tk()
    app = PxvApp(root, FileList(paths))
    root.update()
    app.load_current()
    root.update()
    assert app.canvas_view.zoom == 1.0  # the coordinate math below relies on it
    return app, root, paths


def _open_palette(app):  # noqa: ANN001, ANN202
    """Construct the palette directly (cmd_annotate arrives in a later task)."""
    from pxv.annotation_palette import AnnotationPalette

    palette = AnnotationPalette(app)
    app.annotation_palette = palette
    return palette


def _draw_line(palette, y=10.0):  # noqa: ANN001, ANN202
    """One committed red line (10,y)-(40,y) through the session protocol."""
    palette.select_tool_key("3")
    palette.on_press((10.0, y))
    palette.on_drag((40.0, y))
    palette.on_release((40.0, y))


def test_palette_arms_canvas_and_tears_down_through_end_session(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        assert app.canvas_view._annotation_session is palette
        assert app.canvas_view.canvas.cget("cursor") == "pencil"
        assert palette.layer.shapes == () and palette.tool == "freehand"
        assert palette.protocol("WM_DELETE_WINDOW")  # window close = Done is wired
        palette._end_session(bake=False)
        assert app.canvas_view._annotation_session is None
        assert app.annotation_palette is None
        assert not palette.winfo_exists()
    finally:
        root.destroy()


def test_session_press_drag_release_adds_shape_and_sets_flag(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("3")  # line
        assert app.annotations_unsaved is False
        palette.on_press((10.0, 10.0))
        assert palette.is_dragging
        palette.on_drag((40.0, 30.0))
        assert app.canvas_view._preview_id is not None  # rubber-band preview live
        palette.on_release((40.0, 30.0))
        assert not palette.is_dragging
        assert app.canvas_view._preview_id is None  # swapped for the PIL render
        (shape,) = palette.layer.shapes
        assert shape.tool == "line"
        assert shape.points == ((10.0, 10.0), (40.0, 30.0))
        assert shape.color == palette.color and shape.width_px == palette.width_px
        assert app.annotations_unsaved is True  # set on the first shape
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_freehand_accumulates_points(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)  # default tool is freehand
        palette.on_press((5.0, 5.0))
        palette.on_drag((10.0, 5.0))
        palette.on_drag((15.0, 8.0))
        palette.on_release((20.0, 10.0))
        (shape,) = palette.layer.shapes
        assert shape.tool == "freehand"
        assert shape.points == ((5.0, 5.0), (10.0, 5.0), (15.0, 8.0), (20.0, 10.0))
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tiny_drag_is_discarded(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.on_press((10.0, 10.0))
        palette.on_drag((11.0, 11.0))
        palette.on_release((11.0, 11.0))  # ~1.4 image px * zoom 1.0 < 3 screen px
        assert palette.layer.shapes == ()
        assert app.annotations_unsaved is False
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_escape_cancels_drag_with_latch_until_physical_release(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.on_press((10.0, 10.0))
        palette.on_drag((40.0, 40.0))
        palette.on_escape()
        assert not palette.is_dragging
        assert app.canvas_view._preview_id is None
        palette.on_drag((60.0, 60.0))  # swallowed by the latch
        assert app.canvas_view._preview_id is None
        palette.on_release((60.0, 60.0))  # the physical release: consumed, no shape
        assert palette.layer.shapes == ()
        palette.on_press((10.0, 10.0))  # latch is reset: drawing works again
        palette.on_drag((40.0, 40.0))
        palette.on_release((40.0, 40.0))
        assert len(palette.layer.shapes) == 1
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_done_bakes_exactly_one_history_snapshot(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("5")  # rect (outline)
        palette.on_press((10.0, 10.0))
        palette.on_drag((40.0, 40.0))
        palette.on_release((40.0, 40.0))
        before = app.image_model.working_image
        palette._on_done()
        assert app.annotation_palette is None
        assert len(app.history._undo) == 1  # ONE ordinary snapshot edit
        working = app.image_model.working_image
        assert working is not None and working is not before
        assert working.getpixel((10, 25)) == (255, 0, 0)  # left edge of the rect
        assert working.getpixel((25, 25)) == (0, 0, 255)  # hollow interior untouched
        assert app.annotations_unsaved is True  # set on bake, awaiting a save
    finally:
        root.destroy()


def test_done_with_empty_layer_records_nothing(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        before = app.image_model.working_image
        palette._on_done()
        assert app.annotation_palette is None
        assert not app.history.can_undo  # no snapshot for an empty bake
        assert app.image_model.working_image is before
        assert app.annotations_unsaved is False
    finally:
        root.destroy()


def test_cancel_prompts_then_discards(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        monkeypatch.setattr(
            "pxv.annotation_palette.messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: False),
        )
        palette._on_cancel()  # declined: still open, shape kept
        assert app.annotation_palette is palette and palette.winfo_exists()
        assert len(palette.layer.shapes) == 1
        monkeypatch.setattr(
            "pxv.annotation_palette.messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: True),
        )
        palette._on_cancel()
        assert app.annotation_palette is None
        assert not app.history.can_undo  # Cancel bakes nothing
        assert app.annotations_unsaved is False  # confirmed discard clears the flag
        working = app.image_model.working_image
        assert working is not None and working.getpixel((25, 10)) == (0, 0, 255)
    finally:
        root.destroy()


def test_undo_keys_swallowed_with_hint_while_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        app.record_history()  # a fall-through to app history would be visible
        palette.on_undo_key()
        assert "Select tool" in root.title()
        palette.on_redo_key()
        assert len(app.history._undo) == 1  # untouched
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tool_keys_two_through_six_select_and_others_inert(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        for char, tool in (
            ("2", "freehand"),
            ("3", "line"),
            ("4", "arrow"),
            ("5", "rect"),
            ("6", "ellipse"),
        ):
            palette.select_tool_key(char)
            assert palette.tool == tool
            assert palette._tool_var.get() == tool  # button row follows
        for char in ("1", "7", "8"):  # unshipped phases: stable numbers, inert keys
            palette.select_tool_key(char)
        assert palette.tool == "ellipse"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_color_and_size_controls_style_new_shapes(tmp_path) -> None:  # noqa: ANN001
    from pxv.annotations import size_presets

    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.set_color("#00ff00")
        palette._size_var.set("thick")
        palette._on_size_selected()
        _draw_line(palette)
        (shape,) = palette.layer.shapes
        assert shape.color == "#00ff00"
        assert shape.width_px == size_presets(100).widths[2]  # long side = 100
        assert palette._color_indicator.cget("bg") == "#00ff00"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_overlay_composites_in_both_display_paths(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        shown: list[Image.Image] = []
        monkeypatch.setattr(app.canvas_view, "display", shown.append)
        app.refresh_display()
        assert shown[-1].getpixel((25, 10)) == (255, 0, 0)  # overlay on the preview
        shown.clear()
        app._update_display()  # the window-resize path: same shared hook
        assert shown[-1].getpixel((25, 10)) == (255, 0, 0)
        assert shown[-1].getpixel((25, 40)) == (0, 0, 255)  # base shows elsewhere
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_overlay_cache_keyed_on_revision_and_size(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        o1 = palette.render_display_overlay((100, 80), 1.0)
        assert palette.render_display_overlay((100, 80), 1.0) is o1  # cache hit
        o2 = palette.render_display_overlay((50, 40), 0.5)  # zoom change: new size
        assert o2 is not o1 and o2.size == (50, 40)
        _draw_line(palette, y=30.0)  # layer.revision bump invalidates
        assert palette.render_display_overlay((50, 40), 0.5) is not o2
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_stale_image_guard_cancels_session_at_composite(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        # An unguarded surprise replaces the image under the session:
        app.image_model.working_image = Image.new("RGB", (100, 80), (9, 9, 9))
        app.refresh_display()
        root.update()  # process pending events; the stale teardown already set the title synchronously
        assert app.annotation_palette is None  # guard tore the session down
        assert not palette.winfo_exists()
        assert "image changed" in root.title()
        assert not app.history.can_undo  # and nothing was baked
    finally:
        root.destroy()


def test_stale_image_guard_blocks_bake_at_done(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        app.image_model.working_image = Image.new("RGB", (100, 80), (9, 9, 9))
        palette._on_done()
        assert app.annotation_palette is None
        assert not app.history.can_undo
        working = app.image_model.working_image
        assert working is not None
        assert working.getpixel((25, 10)) == (9, 9, 9)  # never baked the wrong image
        assert "image changed" in root.title()
    finally:
        root.destroy()


def test_cancel_after_bake_preserves_pre_session_dirty_flag(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Regression: confirmed Cancel only discards THIS session — prior baked work survives."""
    app, root, _ = _make_app(tmp_path)
    try:
        # First session: draw and Done (bake sets annotations_unsaved=True)
        palette1 = _open_palette(app)
        _draw_line(palette1)
        palette1._on_done()
        assert app.annotations_unsaved is True
        assert app.annotation_palette is None

        # Second session: draw, then Cancel-confirm
        palette2 = _open_palette(app)
        _draw_line(palette2, y=30.0)
        monkeypatch.setattr(
            "pxv.annotation_palette.messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: True),
        )
        palette2._on_cancel()
        assert app.annotation_palette is None
        # The baked-but-unsaved work from the first session must still be flagged.
        assert app.annotations_unsaved is True
    finally:
        root.destroy()


def test_stale_guard_fires_through_update_display_path(tmp_path) -> None:  # noqa: ANN001
    """Stale guard also trips when the image is replaced and _update_display is called."""
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        # Replace the working image under the session.
        app.image_model.working_image = Image.new("RGB", (100, 80), (9, 9, 9))
        # _update_display is the window-resize path; it calls _composite_annotations.
        app._update_display()
        assert app.annotation_palette is None
        assert not palette.winfo_exists()
    finally:
        root.destroy()


def test_cmd_annotate_opens_then_raises_never_closes(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        assert app.canvas_view._annotation_session is palette
        commands.cmd_annotate(app)  # `d` again: raise + focus, never close or bake
        assert app.annotation_palette is palette and palette.winfo_exists()
        assert not app.history.can_undo
        palette._on_done()
    finally:
        root.destroy()


def test_cmd_annotate_without_image_is_noop() -> None:
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    root = tk.Tk()
    try:
        app = PxvApp(root, FileList([]))
        commands.cmd_annotate(app)
        assert app.annotation_palette is None
    finally:
        root.destroy()


def test_cmd_annotate_gated_while_enhance_dialog_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_enhancement_dialog(app)
        assert app.enhancement_dialog is not None
        commands.cmd_annotate(app)
        assert app.annotation_palette is None  # pick mode and draw mode never coexist
        assert "Enhancements" in root.title()
        app.enhancement_dialog._on_close()
        commands.cmd_annotate(app)
        assert app.annotation_palette is not None
        app.annotation_palette._on_done()
    finally:
        root.destroy()


def test_cmd_annotate_stops_active_slideshow(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        app.start_slideshow()
        assert app.slideshow_active
        commands.cmd_annotate(app)
        assert not app.slideshow_active
        assert app.annotation_palette is not None
        app.annotation_palette._on_done()
    finally:
        root.destroy()


def test_root_tool_keys_route_to_palette_when_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        app._on_tool_key(types.SimpleNamespace(char="4"))  # closed: inert
        commands.cmd_annotate(app)
        app._on_tool_key(types.SimpleNamespace(char="4"))
        assert app.annotation_palette is not None
        assert app.annotation_palette.tool == "arrow"
        app.annotation_palette._on_done()
    finally:
        root.destroy()
