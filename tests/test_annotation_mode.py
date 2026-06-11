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
    """Construct the palette directly, bypassing cmd_annotate's gating."""
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


def test_undo_keys_route_to_layer_while_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        app.record_history()  # a fall-through to app history would be visible
        _draw_line(palette, y=10.0)
        palette.on_undo_key()  # the palette key mirrors land here directly
        assert palette.layer.shapes == ()
        palette.on_redo_key()
        assert len(palette.layer.shapes) == 1
        assert len(app.history._undo) == 1  # app history untouched
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tool_keys_select_and_others_inert(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        for char, tool in (
            ("1", "select"),
            ("2", "freehand"),
            ("3", "line"),
            ("4", "arrow"),
            ("5", "rect"),
            ("6", "ellipse"),
            ("7", "highlight"),
        ):
            palette.select_tool_key(char)
            assert palette.tool == tool
            assert palette._tool_var.get() == tool  # button row follows
        palette.select_tool_key("8")  # text lands later in this phase: still inert
        assert palette.tool == "highlight"
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


def test_gated_commands_show_hint_and_do_nothing(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        size_before = app.image_model.get_working_size()
        commands.cmd_rotate(app, 90)  # representative image-mutating command
        assert app.image_model.get_working_size() == size_before
        assert not app.history.can_undo
        assert "close the drawing palette" in root.title()
        commands.cmd_save_as(app)  # consumed before any dialog could open
        commands.cmd_enhancement_dialog(app)  # the e <-> d mutual gate, e side
        assert app.enhancement_dialog is None
        assert app.annotation_palette is not None
        app.annotation_palette._on_done()
    finally:
        root.destroy()


def test_undo_entry_points_route_to_layer_and_consume_when_empty(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        app.record_history()
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)
        commands.cmd_undo(app)  # u / Ctrl-z / context-menu Undo all call this
        assert palette.layer.shapes == ()
        commands.cmd_redo(app)  # Ctrl-y / Ctrl-Shift-Z / context-menu Redo
        assert len(palette.layer.shapes) == 1
        commands.cmd_undo(app)
        commands.cmd_undo(app)  # layer stack empty: CONSUMED, not app history
        assert len(app.history._undo) == 1
        assert "nothing to undo" not in root.title()  # consumed silently
        palette._end_session(bake=False)
        commands.cmd_undo(app)  # closed: routes to app history again
        assert len(app.history._undo) == 0
    finally:
        root.destroy()


def test_zoom_consumed_during_drag_and_escape_never_leaves_mode(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        palette.on_press((10.0, 10.0))
        palette.on_drag((30.0, 30.0))
        zoom_before = app.canvas_view.zoom
        commands.cmd_zoom_increase(app)
        assert app.canvas_view.zoom == zoom_before  # consumed mid-drag
        palette.on_release((30.0, 30.0))
        commands.cmd_zoom_increase(app)
        assert app.canvas_view.zoom != zoom_before  # back to normal after release
        # Escape is consumed entirely by the session — never escape_action:
        app.start_slideshow()  # escape_action would stop it
        commands.cmd_escape(app)
        assert app.slideshow_active is True
        assert app.annotation_palette is palette  # and it never exits the mode
        app.stop_slideshow()
        palette._end_session(bake=False)  # not _on_cancel: one shape committed -> it would prompt
    finally:
        root.destroy()


def test_scale_only_invalidates_overlay_cache(tmp_path) -> None:  # noqa: ANN001
    """Same target_size, different scale -> different overlay object (Step 0)."""
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        o1 = palette.render_display_overlay((100, 80), 1.0)
        assert palette.render_display_overlay((100, 80), 2.0) is not o1
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_navigation_prompts_discard_and_cancels_session(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        _draw_line(palette)
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: False)
        )
        commands.cmd_next_image(app)  # declined: fully consumed
        assert app.file_list.index == 0
        assert app.annotation_palette is palette and palette.winfo_exists()
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: True)
        )
        commands.cmd_next_image(app)  # confirmed: session cancelled, then proceed
        assert app.file_list.index == 1
        assert app.annotation_palette is None
        assert app.annotations_unsaved is False
        assert not app.history.can_undo  # cancelled, never baked
    finally:
        root.destroy()


def test_bake_navigate_confirm_then_navigate_does_not_reprompt(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=3)
    try:
        commands.cmd_annotate(app)
        _draw_line(app.annotation_palette)
        app.annotation_palette._on_done()  # bake sets annotations_unsaved
        prompts: list[bool] = []
        monkeypatch.setattr(
            commands,
            "messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: prompts.append(True) or True),
        )
        commands.cmd_next_image(app)
        assert prompts == [True] and app.file_list.index == 1
        commands.cmd_next_image(app)  # flag cleared on confirm + load_current
        assert prompts == [True] and app.file_list.index == 2  # NO re-prompt
    finally:
        root.destroy()


def test_save_success_clears_flag_but_cancelled_dialog_keeps_it(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        _draw_line(app.annotation_palette)
        app.annotation_palette._on_done()
        assert app.annotations_unsaved is True
        # Cancelled Save As dialog: the flag must survive.
        monkeypatch.setattr(
            commands, "filedialog", types.SimpleNamespace(asksaveasfilename=lambda **k: "")
        )
        assert commands.cmd_save_as(app) is False
        assert app.annotations_unsaved is True
        # Real save (BMP: no options dialog in the way) clears it.
        out = tmp_path / "out.bmp"
        monkeypatch.setattr(
            commands, "filedialog", types.SimpleNamespace(asksaveasfilename=lambda **k: str(out))
        )
        assert commands.cmd_save_as(app) is True
        assert out.exists()
        assert app.annotations_unsaved is False
    finally:
        root.destroy()


def test_quit_prompts_when_annotations_unsaved(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        assert root.protocol("WM_DELETE_WINDOW")  # titlebar close routes via cmd_quit
        commands.cmd_annotate(app)
        _draw_line(app.annotation_palette)
        destroyed: list[bool] = []
        monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(True))
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: False)
        )
        commands.cmd_quit(app)  # declined: still running, session intact
        assert destroyed == [] and app.annotation_palette is not None
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: True)
        )
        commands.cmd_quit(app)
        assert destroyed == [True]
    finally:
        # Undo the destroy monkeypatch FIRST: the stub above swallows destroy,
        # and a leaked Tk root poisons every later Tk test in the session
        # ("pyimage N does not exist" cross-contamination).
        monkeypatch.undo()
        root.destroy()


def test_selection_marker_converts_image_space_dashed_single_item() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_selection_marker((10.0, 20.0, 30.0, 40.0))
        assert view._marker_id is not None
        # Image (10,20)/(30,40) -> canvas (110,120)/(130,140) via the centering
        # offset (100), then padded by 3 canvas px on every side.
        assert view.canvas.coords(view._marker_id) == [107.0, 117.0, 133.0, 143.0]
        assert view.canvas.itemcget(view._marker_id, "dash") != ""  # dashed
        first = view._marker_id
        view.set_selection_marker((0.0, 0.0, 10.0, 10.0))
        assert view._marker_id != first
        assert len(view.canvas.find_withtag("all")) == 1  # ONE item: old deleted
        view.set_selection_marker(None)
        assert view._marker_id is None
        assert len(view.canvas.find_withtag("all")) == 0
    finally:
        root.destroy()


def test_selection_marker_rederived_on_display_and_cleared_on_disarm() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_selection_marker((10.0, 20.0, 30.0, 40.0))
        view.zoom = 2.0
        view.display(Image.new("RGB", (200, 200), (0, 0, 0)))  # re-render, new zoom
        # 200x200 display on a 300x300 canvas -> offset 50; image*2 + 50, pad 3.
        assert view.canvas.coords(view._marker_id) == [67.0, 87.0, 113.0, 133.0]
        view.set_annotation_session(_RecordingSession())
        view.set_annotation_session(None)  # disarm clears the marker
        assert view._marker_id is None
    finally:
        root.destroy()


def test_annotation_cursor_switches_arrow_for_select() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_annotation_cursor(True)  # disarmed: a no-op
        assert view.canvas.cget("cursor") == "crosshair"
        view.set_annotation_session(_RecordingSession())
        view.set_annotation_cursor(True)
        assert view.canvas.cget("cursor") == ""  # the default arrow
        view.set_annotation_cursor(False)
        assert view.canvas.cget("cursor") == "pencil"
    finally:
        root.destroy()


def test_key_1_selects_select_tool_with_arrow_cursor(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        assert app.canvas_view.canvas.cget("cursor") == "pencil"
        palette.select_tool_key("1")
        assert palette.tool == "select"
        assert app.canvas_view.canvas.cget("cursor") == ""  # the default arrow
        palette.select_tool_key("3")
        assert app.canvas_view.canvas.cget("cursor") == "pencil"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_select_click_picks_topmost_and_shows_marker(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # shape 0
        _draw_line(palette, y=10.0)  # shape 1, right on top of it
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 1  # topmost (later) wins
        assert app.canvas_view._marker_id is not None
        palette.on_press((25.0, 60.0))  # empty canvas area
        palette.on_release((25.0, 60.0))
        assert palette.layer.selected is None  # click-empty deselects
        assert app.canvas_view._marker_id is None
        palette.on_press((25.0, 10.0))
        palette.select_tool_key("3")  # mid-press: inert, never orphans the drag
        assert palette.tool == "select"
        palette.on_release((25.0, 10.0))
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_select_drag_moves_shape_in_one_undo_step(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # (10,10)-(40,10)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        assert palette.is_dragging  # the whole press-to-release is a drag
        palette.on_drag((30.0, 15.0))  # +5,+5 from the press point
        palette.on_drag((35.0, 30.0))  # +10,+20 ABSOLUTE from the press point
        palette.on_release((35.0, 30.0))
        assert not palette.is_dragging
        (shape,) = palette.layer.shapes
        assert shape.points == ((20.0, 30.0), (50.0, 30.0))
        assert palette.layer.selected == 0  # still selected after the move
        assert palette.layer.undo() is True  # the whole move: ONE undo step
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))
        assert palette.layer.undo() is True  # the add itself
        assert palette.layer.shapes == ()
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tiny_select_drag_is_a_click_not_a_move(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_drag((26.0, 11.0))  # ~1.4 image px * zoom 1.0 < 3 screen px
        palette.on_release((26.0, 11.0))
        (shape,) = palette.layer.shapes
        assert shape.points == ((10.0, 10.0), (40.0, 10.0))  # unmoved
        assert palette.layer.selected == 0  # but selected
        assert palette.layer.undo() is True
        assert palette.layer.shapes == ()  # only the add was on the stack
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_escape_cancels_move_with_latch_and_rolls_back(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_drag((45.0, 40.0))  # +20,+30: mid-move
        assert palette.layer.shapes[0].points == ((30.0, 40.0), (60.0, 40.0))
        palette.on_escape()
        # The move was ONE coalesced undo state: rolled back exactly.
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))
        assert palette.layer.selected is None  # layer.undo() clears selection
        assert app.canvas_view._marker_id is None
        assert not palette.is_dragging
        palette.on_drag((60.0, 60.0))  # latched: swallowed
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))
        palette.on_release((60.0, 60.0))  # the physical release re-arms us
        palette.select_tool_key("3")
        palette.on_press((10.0, 50.0))
        palette.on_drag((40.0, 50.0))
        palette.on_release((40.0, 50.0))
        assert len(palette.layer.shapes) == 2  # drawing works again
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_escape_deselects_before_doing_nothing(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        app.annotation_palette = palette  # cmd_escape routes through the app attr
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 0
        commands.cmd_escape(app)  # the root Escape entry point
        assert palette.layer.selected is None  # deselect step
        assert app.canvas_view._marker_id is None
        assert len(palette.layer.shapes) == 1  # nothing deleted or undone
        commands.cmd_escape(app)  # nothing selected: consumed, no-op
        assert app.annotation_palette is palette  # never exits the mode
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_two_consecutive_moves_on_same_shape_are_two_undo_steps(tmp_path) -> None:  # noqa: ANN001
    """Two separate select+move runs on the SAME shape are TWO undo steps.

    Step 0 test: pins that a future 'skip select_at when re-pressing the
    already-selected shape' optimisation would not silently merge them.
    """
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # (10,10)-(40,10)
        palette.select_tool_key("1")

        # First select+move: press, move +0,+20, release.
        palette.on_press((25.0, 10.0))
        palette.on_drag((25.0, 30.0))
        palette.on_release((25.0, 30.0))
        pos_after_first = palette.layer.shapes[0].points

        # Second press on the same shape (select_at breaks the coalesce run), move +0,+20.
        palette.on_press((25.0, 30.0))
        palette.on_drag((25.0, 50.0))
        palette.on_release((25.0, 50.0))
        pos_after_second = palette.layer.shapes[0].points

        assert pos_after_second != pos_after_first  # actually moved

        # Walk back through both undo steps independently.
        assert palette.layer.undo() is True  # rolls back the second move
        assert palette.layer.shapes[0].points == pos_after_first
        assert palette.layer.undo() is True  # rolls back the first move
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))

        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_styling_controls_restyle_live_selection_coalesced(tmp_path) -> None:  # noqa: ANN001
    from pxv.annotations import size_presets

    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # red, medium (width 2.0 at long side 100)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        palette.set_color("#00ff00")
        palette.set_color("#0000ff")  # same coalesced run
        palette._size_var.set("thick")
        palette._on_size_selected()  # still the same run
        (shape,) = palette.layer.shapes
        assert shape.color == "#0000ff"
        assert shape.width_px == size_presets(100).widths[2]
        assert palette.color == "#0000ff"  # defaults for NEW shapes follow too
        assert palette.layer.undo() is True  # ONE step: the whole restyle run
        (shape,) = palette.layer.shapes
        assert shape.color == "#ff0000" and shape.width_px == 2.0
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_undo_clears_selection_and_marker(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert app.canvas_view._marker_id is not None
        palette.on_undo_key()  # pops the add: shape gone, selection cleared
        assert palette.layer.shapes == () and palette.layer.selected is None
        assert app.canvas_view._marker_id is None
        palette.on_redo_key()  # restored WITHOUT a selection (layer semantics)
        assert len(palette.layer.shapes) == 1 and palette.layer.selected is None
        assert app.canvas_view._marker_id is None
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_delete_key_and_backspace_delete_selection(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)
        _draw_line(palette, y=30.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        commands.cmd_delete(app)  # the root <Delete> chokepoint
        assert len(palette.layer.shapes) == 1
        assert palette.layer.shapes[0].points[0] == (10.0, 30.0)  # other survived
        assert palette.layer.selected is None
        assert app.canvas_view._marker_id is None  # marker cleared with it
        palette.on_press((25.0, 30.0))
        palette.on_release((25.0, 30.0))
        commands.cmd_backspace(app)  # BackSpace WITH a selection deletes
        assert palette.layer.shapes == ()
        assert app.file_list.index == 0  # and did NOT navigate
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_backspace_without_selection_navigates_through_the_gate(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)  # unsaved work, nothing selected
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: True)
        )
        commands.cmd_backspace(app)  # no selection: the navigate gate runs
        assert app.file_list.index == 1  # wrapped to the previous image
        assert app.annotation_palette is None  # confirmed prompt ended the session
        assert app.annotations_unsaved is False
    finally:
        root.destroy()


def test_delete_key_inert_without_draw_mode(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        assert root.bind("<Delete>")  # the root binding exists
        commands.cmd_delete(app)  # no palette: nothing to do, must not raise
        assert app.annotation_palette is None
    finally:
        root.destroy()


def test_highlight_tool_accumulates_and_bakes_translucent(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("7")
        assert palette.tool == "highlight"
        palette.on_press((10.0, 40.0))
        palette.on_drag((30.0, 40.0))
        # Outline-only Tk polyline preview (per-item alpha is impossible in Tk).
        assert app.canvas_view._preview_id is not None
        palette.on_drag((50.0, 40.0))
        palette.on_release((70.0, 40.0))
        (shape,) = palette.layer.shapes
        assert shape.tool == "highlight"
        assert shape.points == ((10.0, 40.0), (30.0, 40.0), (50.0, 40.0), (70.0, 40.0))
        palette._on_done()
        working = app.image_model.working_image
        assert working is not None
        # The TRUE translucent render: 0.4-alpha red over the blue base
        # -> (102, 0, 153); the stroke is 4 x width_px = 8 px tall around y=40.
        r, g, b = working.getpixel((40, 40))
        assert 100 <= r <= 104 and g == 0 and 151 <= b <= 155
    finally:
        root.destroy()


def test_opacity_slider_styles_new_shapes_and_restyles_selection(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette._opacity_var.set(50.0)
        palette._on_opacity_changed("50.0")  # the tk.Scale command callback
        assert palette.opacity == 0.5
        _draw_line(palette, y=10.0)
        (shape,) = palette.layer.shapes
        assert shape.opacity == 0.5
        # With a live selection the slider restyles it — coalesced, so a whole
        # slider walk is ONE undo step (2026-06-10 design).
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 0
        for v in (40.0, 30.0, 20.0):
            palette._opacity_var.set(v)
            palette._on_opacity_changed(str(v))
        assert palette.layer.shapes[0].opacity == 0.2
        assert palette.layer.undo() is True
        assert palette.layer.shapes[0].opacity == 0.5  # one step back past the walk
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_fill_toggle_styles_new_rects_and_restyles_only_rect_ellipse(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette._fill_var.set(True)
        palette._on_fill_toggled()
        assert palette.fill is True
        palette.select_tool_key("5")  # rect
        palette.on_press((10.0, 10.0))
        palette.on_drag((40.0, 40.0))
        palette.on_release((40.0, 40.0))
        assert palette.layer.shapes[0].fill is True
        _draw_line(palette, y=60.0)
        assert palette.layer.shapes[1].fill is False  # fill is rect/ellipse-only
        # A selected LINE ignores the toggle (no junk undo step)...
        palette.select_tool_key("1")
        palette.on_press((25.0, 60.0))
        palette.on_release((25.0, 60.0))
        assert palette.layer.selected == 1
        palette._fill_var.set(False)
        palette._on_fill_toggled()
        assert palette.layer.shapes[1].fill is False
        # No junk undo step: the toggle on a line interposed nothing, so one
        # undo removes the line-add itself (a no-change replace would not).
        assert palette.layer.undo() is True
        assert len(palette.layer.shapes) == 1
        assert palette.layer.redo() is True  # restore the line for the rect part
        assert len(palette.layer.shapes) == 2
        # ...but a selected rect restyles live (picked by its filled interior;
        # undo/redo cleared the selection, so this re-picks from scratch).
        palette.on_press((25.0, 25.0))
        palette.on_release((25.0, 25.0))
        assert palette.layer.selected == 0
        palette._fill_var.set(False)
        palette._on_fill_toggled()
        assert palette.layer.shapes[0].fill is False
        palette._end_session(bake=False)
    finally:
        root.destroy()
