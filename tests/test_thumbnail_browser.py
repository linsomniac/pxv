"""DISPLAY-gated tests for the Visual Schnauzer browser window.

AIDEV-NOTE: These build real Tk widgets, so they need an X display and are skipped
headlessly (pattern from test_dialog_focus.py). Run under Xvfb, e.g.
`Xvfb :99 & DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requires an X display (Tk browser test)"
)


def _make_app(tmp_path: Path, n: int) -> tuple[object, tk.Tk]:
    """Build a real PxvApp over n synthetic PNGs (no auto-load)."""
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    paths = []
    for i in range(n):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (40, 30), (40 * i % 256, 10, 10)).save(p)
        paths.append(p.resolve())
    root = tk.Tk()
    app = PxvApp(root, FileList(paths))
    root.update_idletasks()
    return app, root


def _drain_loader(browser: object) -> None:
    while browser._load_queue:  # type: ignore[attr-defined]
        browser._pump_loader()  # type: ignore[attr-defined]


def test_app_has_browser_state(tmp_path: Path) -> None:
    from pxv.thumbnails import ThumbnailCache

    app, root = _make_app(tmp_path, 1)
    try:
        assert app.browser is None
        assert isinstance(app.thumbnail_cache, ThumbnailCache)
    finally:
        root.destroy()


def test_open_builds_one_tile_per_file(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is not None
        assert len(app.browser._tiles) == 3
    finally:
        root.destroy()


def test_click_tile_loads_that_image(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        app.browser._activate(2)
        root.update()
        assert app.file_list.index == 2
        assert app.image_model.current_path == app.file_list.paths()[2]
    finally:
        root.destroy()


def test_arrow_navigation_moves_selection_and_index(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        app.browser._nav(1)  # Right
        root.update()
        assert app.file_list.index == 1
        assert app.browser._selected == 1
    finally:
        root.destroy()


def test_main_navigation_updates_grid_highlight(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        commands.cmd_next_image(app)  # index 0 -> 1 in the main window
        root.update()
        assert app.browser._selected == 1
    finally:
        root.destroy()


def test_loader_decodes_and_populates_cache(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        _drain_loader(app.browser)
        assert all(t.loaded for t in app.browser._tiles)
        assert app.file_list.paths()[0] in app.thumbnail_cache
    finally:
        root.destroy()


def test_broken_file_does_not_stall_loader(tmp_path: Path) -> None:
    from pxv import commands
    from pxv.file_list import FileList

    good = tmp_path / "good.png"
    Image.new("RGB", (20, 20), (0, 200, 0)).save(good)
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    root = tk.Tk()
    from pxv.app import PxvApp

    app = PxvApp(root, FileList([good.resolve(), bad.resolve()]))
    root.update_idletasks()
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        _drain_loader(app.browser)
        # Both tiles resolve to a terminal state; the bad one is marked, not hung.
        assert all(t.loaded for t in app.browser._tiles)
        assert app.browser._tiles[1].image_label.cget("text") == "broken"
    finally:
        root.destroy()


def test_toggle_opens_then_closes(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is not None
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is None
    finally:
        root.destroy()


def test_close_restores_canvas_focus(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        app.browser.focus_force()
        root.update()
        app.browser._on_close()
        root.update()
        assert app.browser is None
        assert root.focus_get() is app.canvas_view.canvas
    finally:
        root.destroy()


def test_empty_file_list_shows_no_images_state(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 0)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser._tiles == []
        assert app.browser._empty_label is not None
    finally:
        root.destroy()


def test_rebuild_picks_up_a_newly_added_file(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert len(app.browser._tiles) == 2

        new_path = tmp_path / "added.png"
        Image.new("RGB", (20, 20), (0, 0, 200)).save(new_path)
        app.file_list.add(new_path.resolve())
        app.browser.rebuild()
        root.update()
        assert len(app.browser._tiles) == 3
    finally:
        root.destroy()


def test_failed_load_rolls_back_grid_highlight(tmp_path: Path, monkeypatch) -> None:
    from pxv import commands
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    # load_current() shows a modal error dialog on failure; silence it.
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *a, **k: None)

    good = tmp_path / "g0.png"
    Image.new("RGB", (30, 30), (0, 100, 0)).save(good)
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    root = tk.Tk()
    app = PxvApp(root, FileList([good.resolve(), bad.resolve()]))
    root.update_idletasks()
    try:
        app.load_current()  # display the good image at index 0
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser._selected == 0

        commands.cmd_show_index(app, 1)  # bad image -> load fails -> rollback
        root.update()
        assert app.file_list.index == 0  # index rolled back
        assert app.browser._selected == 0  # highlight snapped back to the shown image
    finally:
        root.destroy()


def test_quit_with_browser_open_closes_it(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is not None
        commands.cmd_quit(app)  # must close the browser (cancel its timers) before destroy
        assert app.browser is None
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_browser_binds_wheel_events(tmp_path: Path) -> None:
    # AIDEV-NOTE: The Toplevel is in every descendant's bindtags, so a single binding here
    # catches the wheel over the tiles too. <MouseWheel> is a mouse wheel (and the trackpad
    # on Tk 8.6); <TouchpadScroll> is the trackpad on Tk 8.7+/9.0 (bound only where it
    # exists). Pin both.
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser.bind("<MouseWheel>")  # non-empty bound script
        assert app.browser.bind("<Button-4>")
        if root.call("info", "commands", "tk::PreciseScrollDeltas"):
            assert app.browser.bind("<TouchpadScroll>")  # bound on Tk 8.7+
    finally:
        root.destroy()


def test_wheel_handler_scrolls_the_canvas(tmp_path: Path) -> None:
    # The wheel handler bound on the Toplevel must move the canvas view. With many images
    # the grid is taller than the viewport, so a downward notch advances the top off 0.
    # (We invoke _on_wheel directly: event_generate does not populate num/delta reliably
    # in a headless Tk, but _on_wheel is exactly the callback the Toplevel is bound to.)
    from pxv import commands

    app, root = _make_app(tmp_path, 40)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        root.update_idletasks()
        canvas = app.browser._canvas
        assert canvas.yview()[0] == 0.0

        down = tk.Event()
        down.num = 5  # X11 wheel-down
        down.delta = 0
        app.browser._on_wheel(down)
        root.update_idletasks()
        assert canvas.yview()[0] > 0.0  # scrolled down

        up = tk.Event()
        up.num = 4  # X11 wheel-up
        up.delta = 0
        app.browser._on_wheel(up)
        root.update_idletasks()
        assert canvas.yview()[0] == 0.0  # scrolled back to the top
    finally:
        root.destroy()


def test_touchpad_scroll_moves_the_canvas(tmp_path: Path) -> None:
    # Tk 8.7+/9.0 deliver trackpad gestures as <TouchpadScroll>; _on_touchpad_scroll
    # decodes the packed delta via tk::PreciseScrollDeltas and scrolls. Skipped on older
    # Tk that lacks that helper (there the <MouseWheel> path covers the trackpad).
    from pxv import commands

    app, root = _make_app(tmp_path, 60)
    try:
        if not root.call("info", "commands", "tk::PreciseScrollDeltas"):
            pytest.skip("Tk < 8.7 has no <TouchpadScroll>")
        commands.cmd_toggle_browser(app)
        root.update()
        root.update_idletasks()
        canvas = app.browser._canvas
        top = canvas.yview()[0]

        # delta low word 0xFFFD -> deltaY = -3 -> scroll down. serial % 5 == 0 to pass the
        # throttle. (event_generate won't populate serial/delta headlessly, so call direct.)
        down = tk.Event()
        down.serial = 5
        down.delta = 65533
        app.browser._on_touchpad_scroll(down)
        root.update_idletasks()
        assert canvas.yview()[0] > top  # scrolled down
    finally:
        root.destroy()
