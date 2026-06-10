"""DISPLAY-gated tests for the histogram panel and tabbed enhancement dialog.

AIDEV-NOTE: Real Tk widgets — skipped headlessly like test_dialog_focus.py.
Run under Xvfb: `Xvfb :99 &` then `DISPLAY=:99 uv run pytest <this file>`.
"""

from __future__ import annotations

import os

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
        lum: list[int], rgb: list[int], channels: set[str], log_scale: bool
    ) -> "Image.Image":
        calls.append((channels, log_scale))
        return real_render(lum, rgb, channels, log_scale)

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
