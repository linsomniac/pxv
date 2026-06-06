"""Focus-restoration tests for the non-modal info/enhancement dialogs.

AIDEV-NOTE: These exercise real Tk widgets, so they need an X display and are
skipped headlessly (the rest of the suite is deliberately display-free — see
conftest). Run locally or under Xvfb, e.g. `xvfb-run -a pytest`.

Regression guard for the "Close button locks up the app" bug: all keyboard
shortcuts are bound on the root window, so closing a non-modal transient dialog
MUST hand keyboard focus back to the canvas or every key binding goes dead while
mouse/rubber-band events keep working.
"""

from __future__ import annotations

import os
import types

import pytest

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requires an X display (Tk focus test)"
)


def _make_app() -> tuple[types.SimpleNamespace, tk.Tk]:
    """Build a lightweight PxvApp double around real Tk widgets.

    The dialogs only touch a handful of app attributes; binding the real
    PxvApp.restore_main_focus onto the double keeps the test exercising the
    production focus-restoration code rather than a reimplementation.
    """
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
    )
    app.restore_main_focus = types.MethodType(PxvApp.restore_main_focus, app)
    return app, root


def test_info_dialog_close_restores_canvas_focus() -> None:
    from pxv.info_dialog import InfoDialog

    app, root = _make_app()
    try:
        dialog = InfoDialog(app)
        app.info_dialog = dialog
        # Replicate real use: the dialog holds the input focus when the user
        # closes it, so destroy() clears focus and the reclaim must follow it.
        dialog.focus_force()
        root.update()
        dialog._on_close()
        root.update()
        assert root.focus_get() is app.canvas_view.canvas
        assert app.info_dialog is None
    finally:
        root.destroy()


def test_enhancement_dialog_close_restores_canvas_focus() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dialog = EnhancementDialog(app)
        app.enhancement_dialog = dialog
        # Replicate real use: the dialog holds the input focus when the user
        # closes it, so destroy() clears focus and the reclaim must follow it.
        dialog.focus_force()
        root.update()
        dialog._on_close()
        root.update()
        assert root.focus_get() is app.canvas_view.canvas
        assert app.enhancement_dialog is None
    finally:
        root.destroy()
