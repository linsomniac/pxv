"""DISPLAY-gated tests for the histogram panel and tabbed enhancement dialog.

AIDEV-NOTE: Real Tk widgets — skipped headlessly like test_dialog_focus.py.
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


def test_histogram_panel_update_and_blank() -> None:
    from pxv.histogram_panel import HistogramPanel

    root = tk.Tk()
    try:
        panel = HistogramPanel(root)
        panel.update_from_image(Image.new("RGB", (16, 16), (200, 30, 30)))
        assert panel._photo is not None
        assert panel._clip_label.cget("text") != ""
        panel.update_from_image(None)
        assert panel._photo is None
        assert panel._clip_label.cget("text") == ""
    finally:
        root.destroy()


def test_histogram_panel_toggles_reach_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    import pxv.histogram_panel as hp

    calls: list[tuple[set[str], bool]] = []
    real_render = hp.render_histogram

    def recording_render(
        lum: list[int],
        rgb: list[int],
        channels: set[str],
        log_scale: bool,
        size: tuple[int, int] = hp.HIST_SIZE,
    ) -> "Image.Image":
        calls.append((channels, log_scale))
        return real_render(lum, rgb, channels, log_scale, size)

    monkeypatch.setattr(hp, "render_histogram", recording_render)
    root = tk.Tk()
    try:
        panel = hp.HistogramPanel(root)
        panel.update_from_image(Image.new("RGB", (16, 16), (255, 0, 0)))
        panel._channel_vars["r"].set(True)
        panel._log_var.set(True)
        panel._redraw()
        assert calls[0] == ({"lum"}, False)
        assert calls[-1] == ({"lum", "r"}, True)
    finally:
        root.destroy()


def _make_app() -> tuple[types.SimpleNamespace, "tk.Tk"]:
    """Lightweight PxvApp double around real Tk widgets (see test_dialog_focus)."""
    from pxv.app import PxvApp
    from pxv.canvas_view import CanvasView
    from pxv.enhancements import EnhancementParams

    root = tk.Tk()
    canvas_view = CanvasView(root)
    root.update_idletasks()
    app = types.SimpleNamespace(
        root=root,
        canvas_view=canvas_view,
        info_dialog=None,
        enhancement_dialog=None,
        enhancement_params=EnhancementParams(),
        image_model=types.SimpleNamespace(
            keep_metadata=False,
            metadata=None,
            working_image=Image.new("RGB", (8, 8), (120, 90, 200)),
        ),
        refresh_calls=[],
    )
    app.refresh_display = lambda: app.refresh_calls.append(True)
    app.restore_main_focus = types.MethodType(PxvApp.restore_main_focus, app)
    return app, root


def test_dialog_has_histogram_panel_and_sliders_tab() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        tabs = [dlg._notebook.tab(tab_id, "text") for tab_id in dlg._notebook.tabs()]
        assert "Sliders" in tabs
        # Sliders still build and sync inside the tab.
        app.enhancement_params.brightness = 1.5
        dlg.sync_sliders_from_params()
        assert dlg._slider_vars["brightness"].get() == 1.5
        dlg._on_close()
    finally:
        root.destroy()


def test_dialog_update_histogram_delegates_to_panel() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg.update_histogram(Image.new("RGB", (8, 8), (0, 255, 0)))
        assert dlg.histogram_panel._photo is not None
        dlg.update_histogram(None)
        assert dlg.histogram_panel._photo is None
        dlg._on_close()
    finally:
        root.destroy()


def test_cmd_enhancement_dialog_seeds_histogram_via_refresh() -> None:
    from pxv import commands

    app, root = _make_app()
    try:
        app.refresh_display = lambda: app.refresh_calls.append(app.enhancement_dialog is not None)
        commands.cmd_enhancement_dialog(app)
        assert app.enhancement_dialog is not None
        assert app.refresh_calls == [True]
        app.enhancement_dialog._on_close()
    finally:
        root.destroy()


def _make_levels_tab(
    root: "tk.Tk",
) -> tuple[object, dict[str, object], list[bool]]:
    """LevelsTab wired to a dict-backed store — no app or dialog needed."""
    from pxv.histogram_panel import compute_histograms
    from pxv.levels_tab import LevelsTab
    from pxv.tone import LevelsChannel

    store: dict[str, LevelsChannel] = {key: LevelsChannel() for key in ("master", "r", "g", "b")}
    changes: list[bool] = []
    hists = compute_histograms(Image.new("RGB", (16, 16), (10, 200, 60)))
    tab = LevelsTab(
        root,
        get_levels=store.__getitem__,
        set_levels=store.__setitem__,
        get_input_histograms=lambda: hists,
        on_change=lambda: changes.append(True),
    )
    return tab, store, changes


def test_levels_tab_builds_with_histogram_strip() -> None:
    root = tk.Tk()
    try:
        tab, _store, _changes = _make_levels_tab(root)
        assert tab._hist_photo is not None
        assert tab._spins["in_black"].get() == "0"
        assert tab._spins["gamma"].get() == "1.00"
    finally:
        root.destroy()


def test_levels_tab_marker_drag_updates_store() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, changes = _make_levels_tab(root)
        tab._on_in_press(types.SimpleNamespace(x=2))  # nearest = black marker
        tab._on_in_drag(types.SimpleNamespace(x=50))
        tab._on_release(types.SimpleNamespace())
        assert store["master"].in_black == 50
        assert changes  # debounce hook fired
        # Black can never cross white-1.
        store["master"] = LevelsChannel(in_black=0, in_white=60)
        tab.sync_from_params()
        tab._on_in_press(types.SimpleNamespace(x=2))
        tab._on_in_drag(types.SimpleNamespace(x=200))
        assert store["master"].in_black == 59
    finally:
        root.destroy()


def test_levels_tab_channel_switch_shows_channel_values() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, _changes = _make_levels_tab(root)
        store["r"] = LevelsChannel(in_black=42)
        tab._channel.set("r")
        tab.sync_from_params()
        assert tab._spins["in_black"].get() == "42"
    finally:
        root.destroy()


def test_levels_tab_spinbox_edit_updates_store() -> None:
    root = tk.Tk()
    try:
        tab, store, changes = _make_levels_tab(root)
        tab._spins["in_black"].delete(0, tk.END)
        tab._spins["in_black"].insert(0, "30")
        tab._on_spin_change()
        assert store["master"].in_black == 30
        assert changes
    finally:
        root.destroy()


def test_levels_tab_auto_sets_per_channel() -> None:
    root = tk.Tk()
    try:
        tab, store, changes = _make_levels_tab(root)
        tab._on_auto()
        # Solid color (10, 200, 60): every channel collapses to one bin ->
        # auto_levels degenerate fallback -> identity per channel; the point
        # here is that Auto ran per-channel and fired the change hook.
        assert changes
        assert store["master"].is_identity()  # Auto never touches master
    finally:
        root.destroy()


def test_levels_tab_gamma_marker_drag_roundtrips() -> None:
    root = tk.Tk()
    try:
        tab, store, _changes = _make_levels_tab(root)
        tab._on_in_press(types.SimpleNamespace(x=127))  # nearest = mid marker
        tab._on_in_drag(types.SimpleNamespace(x=64))  # t=0.25 -> gamma ~2
        tab._on_release(types.SimpleNamespace())
        assert 1.9 <= store["master"].gamma <= 2.1
        assert tab._spins["gamma"].get() == f"{store['master'].gamma:.2f}"
    finally:
        root.destroy()


def test_levels_tab_output_markers_cannot_cross_by_drag() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, _changes = _make_levels_tab(root)
        store["master"] = LevelsChannel(out_black=0, out_white=60)
        tab.sync_from_params()
        tab._on_out_press(types.SimpleNamespace(x=2))  # nearest = out_black
        tab._on_out_drag(types.SimpleNamespace(x=240))
        tab._on_release(types.SimpleNamespace())
        assert store["master"].out_black == 60  # clamped: markers may meet, never cross
    finally:
        root.destroy()


def test_dialog_has_levels_tab_wired_to_params() -> None:
    from pxv.enhancement_dialog import EnhancementDialog
    from pxv.tone import LevelsChannel

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        tabs = [dlg._notebook.tab(tab_id, "text") for tab_id in dlg._notebook.tabs()]
        assert tabs[:2] == ["Sliders", "Levels"]
        # Widget edits land in the app params...
        dlg.levels_tab._put(in_black=12)
        assert app.enhancement_params.levels_master.in_black == 12
        # ...and external param changes flow back on sync (undo path).
        app.enhancement_params.levels_master = LevelsChannel(in_black=33)
        dlg.sync_sliders_from_params()
        assert dlg.levels_tab._spins["in_black"].get() == "33"
        dlg._on_close()
    finally:
        root.destroy()


def test_dialog_levels_edit_schedules_debounced_refresh() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg.levels_tab._put(in_black=20)
        assert app.refresh_calls == []  # not synchronous — debounced
        assert dlg._refresh_after_id is not None  # 30ms timer armed
        dlg._do_refresh()  # fire deterministically (avoids Xvfb timing flake)
        assert app.refresh_calls == [True]
        dlg._on_close()
    finally:
        root.destroy()


def test_update_histogram_resyncs_levels_strip_on_image_change() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg._input_histograms()  # populate the cache for the current image
        strip_before = dlg.levels_tab._hist_photo
        # Geometry op replaces working_image, then refresh feeds the dialog:
        app.image_model.working_image = Image.new("RGB", (8, 8), (5, 5, 5))
        dlg.update_histogram(Image.new("RGB", (8, 8), (5, 5, 5)))
        assert dlg.levels_tab._hist_photo is not strip_before  # strip re-rendered
        # And a feed with an UNCHANGED working image must not re-render the strip:
        strip_after = dlg.levels_tab._hist_photo
        dlg.update_histogram(Image.new("RGB", (8, 8), (5, 5, 5)))
        assert dlg.levels_tab._hist_photo is strip_after
        dlg._on_close()
    finally:
        root.destroy()


def test_tab_changed_to_levels_resyncs_strip() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg._notebook.select(dlg.levels_tab)
        root.update()  # deliver <<NotebookTabChanged>>
        strip_before = dlg.levels_tab._hist_photo
        app.image_model.working_image = Image.new("RGB", (8, 8), (250, 1, 1))
        dlg._notebook.select(0)  # to Sliders
        root.update()
        dlg._notebook.select(dlg.levels_tab)  # back to Levels
        root.update()
        assert dlg.levels_tab._hist_photo is not strip_before
        dlg._on_close()
    finally:
        root.destroy()


def test_dialog_input_histogram_cache_keyed_on_working_image() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        first = dlg._input_histograms()
        assert first is not None
        assert dlg._input_histograms() is first  # cached: same object back
        app.image_model.working_image = Image.new("RGB", (8, 8), (1, 2, 3))
        second = dlg._input_histograms()
        assert second is not None and second is not first  # cache invalidated
        app.image_model.working_image = None
        assert dlg._input_histograms() is None
        dlg._on_close()
    finally:
        root.destroy()


def _make_curve_editor(
    root: "tk.Tk",
) -> tuple[object, dict[str, object], list[bool]]:
    """CurveEditor wired to a dict-backed store — no app or dialog needed."""
    from pxv.curve_editor import CurveEditor
    from pxv.histogram_panel import compute_histograms
    from pxv.tone import IDENTITY_CURVE

    store: dict[str, tuple[tuple[int, int], ...]] = {
        key: IDENTITY_CURVE for key in ("master", "r", "g", "b")
    }
    changes: list[bool] = []
    hists = compute_histograms(Image.new("RGB", (16, 16), (10, 200, 60)))
    editor = CurveEditor(
        root,
        get_curve=store.__getitem__,
        set_curve=store.__setitem__,
        get_input_histograms=lambda: hists,
        on_change=lambda: changes.append(True),
    )
    return editor, store, changes


def test_curve_editor_builds_with_backdrop_and_identity() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        assert editor._hist_photo is not None
        assert store["master"] == ((0, 0), (255, 255))
    finally:
        root.destroy()


def test_curve_editor_click_adds_point_and_drag_moves_it() -> None:
    root = tk.Tk()
    try:
        editor, store, changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=64))  # empty area -> add
        assert len(store["master"]) == 3
        assert (128, 191) in store["master"]  # canvas y=64 -> value 255-64
        editor._on_drag(types.SimpleNamespace(x=140, y=55))
        assert (140, 200) in store["master"]
        editor._on_release(types.SimpleNamespace())
        assert changes
    finally:
        root.destroy()


def test_curve_editor_drag_clamps_x_between_neighbors_and_pins_endpoints() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=128))  # add mid point
        editor._on_drag(types.SimpleNamespace(x=300, y=128))  # past right endpoint
        xs = [p[0] for p in store["master"]]
        assert xs == sorted(xs) and xs[-1] == 255 and xs[1] == 254  # clamped
        editor._on_release(types.SimpleNamespace())
        # Endpoint: x pinned, y free.
        editor._on_press(types.SimpleNamespace(x=0, y=255))  # grab (0, 0)
        editor._on_drag(types.SimpleNamespace(x=80, y=200))
        assert store["master"][0] == (0, 55)  # x stayed 0, y moved
        editor._on_release(types.SimpleNamespace())
    finally:
        root.destroy()


def test_curve_editor_right_click_deletes_only_interior_points() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=128))
        editor._on_release(types.SimpleNamespace())
        assert len(store["master"]) == 3
        editor._on_right_click(types.SimpleNamespace(x=128, y=128))
        assert len(store["master"]) == 2
        editor._on_right_click(types.SimpleNamespace(x=0, y=255))  # endpoint
        assert len(store["master"]) == 2  # endpoints undeletable
    finally:
        root.destroy()


def test_curve_editor_buttons() -> None:
    root = tk.Tk()
    try:
        editor, store, changes = _make_curve_editor(root)
        editor._on_invert()
        assert store["master"] == ((0, 255), (255, 0))
        editor._on_reset_curve()
        assert store["master"] == ((0, 0), (255, 255))
        editor._on_equalize()
        assert store["master"] != ((0, 0), (255, 255))  # CDF of the test image
        assert len(changes) >= 3
    finally:
        root.destroy()


def test_dialog_has_curves_tab_wired_to_params() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        tabs = [dlg._notebook.tab(tab_id, "text") for tab_id in dlg._notebook.tabs()]
        assert tabs == ["Sliders", "Levels", "Curves"]
        dlg.curve_editor._put([(0, 0), (100, 180), (255, 255)])
        assert app.enhancement_params.curve_master == ((0, 0), (100, 180), (255, 255))
        # Sync back (undo path):
        app.enhancement_params.curve_master = ((0, 10), (255, 245))
        dlg.sync_sliders_from_params()  # must not raise; editor redraws
        assert dlg.curve_editor._points() == [(0, 10), (255, 245)]
        dlg._on_close()
    finally:
        root.destroy()


def test_levels_auto_preserves_user_gamma_and_output() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, _changes = _make_levels_tab(root)
        store["r"] = LevelsChannel(gamma=2.0, out_black=10)
        tab._on_auto()
        assert store["r"].gamma == 2.0  # Auto only touches black/white points
        assert store["r"].out_black == 10
    finally:
        root.destroy()


def test_curve_editor_external_resync_cancels_drag() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=128))  # adds + grabs idx 1
        store["master"] = ((0, 0), (255, 255))  # external change (undo path)
        editor.sync_from_params()
        editor._on_drag(types.SimpleNamespace(x=200, y=50))  # must be a no-op, not IndexError
        assert store["master"] == ((0, 0), (255, 255))
    finally:
        root.destroy()


def test_canvas_pick_mode_consumes_click_and_disarms() -> None:
    from pxv.canvas_view import CanvasView

    root = tk.Tk()
    try:
        view = CanvasView(root)
        view.canvas.config(width=300, height=300)
        root.update()  # full update: an unmapped canvas reports winfo_width()==1
        view._display_width = 100
        view._display_height = 100
        view.zoom = 1.0
        picks: list[tuple[int, int] | None] = []
        view.set_pick_callback(picks.append, (100, 100))
        assert "tcross" in view.canvas.cget("cursor")
        view._on_press(types.SimpleNamespace(x=150, y=150))
        assert picks == [(50, 50)]
        assert view._rb_start is None  # no rubber band started
        assert view._pick_callback is None  # one-shot: disarmed
        assert view.canvas.cget("cursor") == "crosshair"
        # Next click is a normal rubber-band press again.
        view._on_press(types.SimpleNamespace(x=10, y=10))
        assert view._rb_start is not None
    finally:
        root.destroy()


def test_canvas_pick_outside_image_delivers_none() -> None:
    from pxv.canvas_view import CanvasView

    root = tk.Tk()
    try:
        view = CanvasView(root)
        view.canvas.config(width=300, height=300)
        root.update()  # full update: an unmapped canvas reports winfo_width()==1
        view._display_width = 100
        view._display_height = 100
        view.zoom = 1.0
        picks: list[tuple[int, int] | None] = []
        view.set_pick_callback(picks.append, (100, 100))
        view._on_press(types.SimpleNamespace(x=5, y=5))
        assert picks == [None]
    finally:
        root.destroy()
