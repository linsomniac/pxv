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
        image_model=types.SimpleNamespace(keep_metadata=False, metadata=None),
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
        assert tabs == ["Sliders"]
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
