"""App-level undo/redo integration tests.

AIDEV-NOTE: These drive a real PxvApp, so they need an X display and are skipped
headlessly (same convention as test_dialog_focus). Run under Xvfb, e.g.
`DISPLAY=:99 pytest tests/test_undo_redo.py` with an Xvfb on :99.

The undo stack semantics are unit-tested purely in test_history.py; these cover
the app wiring: that destructive commands record, that undo/redo restore the
full document state (pixels AND enhancement sliders), and that reset clears it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requires an X display (real PxvApp)"
)


def _make_real_app() -> tuple[object, tk.Tk]:
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    root = tk.Tk()
    app = PxvApp(root, FileList([]))
    root.update_idletasks()
    return app, root


def test_undo_redo_round_trips_a_rotate() -> None:
    from pxv import commands

    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (4, 2), (10, 20, 30))
        commands.cmd_rotate(app, 90)
        assert app.image_model.get_working_size() == (2, 4)
        assert app.history.can_undo is True

        app.undo()
        assert app.image_model.get_working_size() == (4, 2)
        assert app.history.can_redo is True

        app.redo()
        assert app.image_model.get_working_size() == (2, 4)
    finally:
        root.destroy()


def test_undo_of_apply_restores_pixels_and_sliders() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (3, 3), (100, 100, 100))
        pre = app.image_model.working_image.getpixel((0, 0))
        app.enhancement_params.brightness = 1.5

        dialog = EnhancementDialog(app)
        app.enhancement_dialog = dialog
        dialog._on_apply()

        # Apply baked the brightness into the pixels and reset the slider.
        assert app.image_model.working_image.getpixel((0, 0)) != pre
        assert app.enhancement_params.brightness == 1.0

        # Undo restores BOTH the pre-bake pixels and the slider value.
        app.undo()
        assert app.image_model.working_image.getpixel((0, 0)) == pre
        assert app.enhancement_params.brightness == 1.5
    finally:
        root.destroy()


def test_reset_clears_history() -> None:
    from pxv import commands

    app, root = _make_real_app()
    try:
        app.image_model.original_image = Image.new("RGB", (4, 4), (5, 6, 7))
        app.image_model.working_image = Image.new("RGB", (4, 2), (10, 20, 30))
        commands.cmd_rotate(app, 90)
        assert app.history.can_undo is True

        commands.cmd_reset(app)
        assert app.history.can_undo is False
        assert app.history.can_redo is False
    finally:
        root.destroy()


def test_apply_at_identity_records_no_history() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (3, 3), (100, 100, 100))
        dialog = EnhancementDialog(app)
        app.enhancement_dialog = dialog
        dialog._on_apply()  # params are identity -> nothing to bake
        assert app.history.can_undo is False
    finally:
        root.destroy()


def test_undo_with_empty_history_is_a_safe_noop() -> None:
    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (4, 4), (10, 20, 30))
        app.undo()  # must not raise
        assert app.history.can_undo is False
        assert app.image_model.get_working_size() == (4, 4)
    finally:
        root.destroy()


def test_undo_round_trips_transparent_save_rgba() -> None:
    """A transparent image's true-RGBA buffer must survive an undo round-trip."""
    from pxv import commands
    from pxv.image_model import ImageModel

    app, root = _make_real_app()
    try:
        rgba = Image.new("RGBA", (8, 4), (0, 255, 0, 128))
        app.image_model._save_rgba = rgba
        app.image_model.working_image = ImageModel._to_rgb_working(rgba)

        commands.cmd_rotate(app, 90)
        assert app.image_model._save_rgba is not None
        assert app.image_model._save_rgba.size == (4, 8)

        app.undo()
        assert app.image_model._save_rgba is not None
        assert app.image_model._save_rgba.size == (8, 4)
        assert app.image_model._save_rgba.getpixel((0, 0))[3] == 128  # alpha preserved
    finally:
        root.destroy()


def test_multi_step_undo_redo_chain() -> None:
    from pxv import commands

    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (8, 4), (10, 20, 30))
        commands.cmd_rotate(app, 90)  # (8,4) -> (4,8)
        commands.cmd_flip_horizontal(app)  # (4,8)
        # Drive resize directly — cmd_resize opens a modal dialog that would block.
        app.record_history()
        app.image_model.resize((2, 2))
        app.refresh_display()
        assert app.image_model.get_working_size() == (2, 2)

        app.undo()
        assert app.image_model.get_working_size() == (4, 8)  # back before resize (flip kept dims)
        app.undo()
        assert app.image_model.get_working_size() == (4, 8)  # back before flip
        app.undo()
        assert app.image_model.get_working_size() == (8, 4)  # back before rotate (original)
        assert app.history.can_undo is False

        app.redo()
        assert app.image_model.get_working_size() == (4, 8)  # rotate reapplied
    finally:
        root.destroy()


def test_new_edit_after_undo_clears_redo_at_app_level() -> None:
    from pxv import commands

    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (8, 4), (10, 20, 30))
        commands.cmd_rotate(app, 90)
        app.undo()
        assert app.history.can_redo is True
        commands.cmd_rotate(app, 90)  # a fresh edit must invalidate the redo branch
        assert app.history.can_redo is False
    finally:
        root.destroy()


def test_geometry_undo_rolls_back_uncommitted_slider_then_redo_restores_it() -> None:
    """Whole-state semantics: undo returns to a checkpoint exactly (params included)."""
    from pxv import commands

    app, root = _make_real_app()
    try:
        app.image_model.working_image = Image.new("RGB", (8, 4), (10, 20, 30))
        commands.cmd_rotate(app, 90)  # checkpoint captured params at identity

        app.enhancement_params.brightness = 1.5  # live, uncommitted tweak after the rotate
        app.undo()
        assert app.enhancement_params.brightness == 1.0  # rolled back to the checkpoint
        assert app.image_model.get_working_size() == (8, 4)

        app.redo()
        assert app.enhancement_params.brightness == 1.5  # the tweak rides forward on redo
        assert app.image_model.get_working_size() == (4, 8)
    finally:
        root.destroy()


def test_loading_an_image_clears_history(tmp_path: Path) -> None:
    from pxv import commands
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    p = tmp_path / "t.png"
    Image.new("RGB", (6, 4), (10, 20, 30)).save(p)
    root = tk.Tk()
    app = PxvApp(root, FileList([p]))
    root.update_idletasks()
    try:
        app.load_current()
        commands.cmd_rotate(app, 90)
        assert app.history.can_undo is True
        app.load_current()  # (re)loading an image starts fresh
        assert app.history.can_undo is False
        assert app.history.can_redo is False
    finally:
        root.destroy()
