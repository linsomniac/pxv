"""Tests for histogram computation, rendering, and app feed (display-free).

AIDEV-NOTE: The compute/render functions are pure (no Tk) by design, mirroring
the canvas_view.py geometry split, so this whole file runs headlessly. The
HistogramPanel widget itself is exercised in test_enhancement_dialog_ui.py
under a real display.
"""

from __future__ import annotations

import types

from PIL import Image

from pxv.histogram_panel import (
    HIST_SIZE,
    clipping_percentages,
    compute_histograms,
    render_histogram,
)


def test_compute_histograms_solid_red() -> None:
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    lum, rgb = compute_histograms(img)
    assert len(lum) == 256 and len(rgb) == 768
    assert rgb[255] == 100  # R: every pixel at 255
    assert rgb[256 + 0] == 100  # G: every pixel at 0
    assert rgb[512 + 0] == 100  # B: every pixel at 0
    assert sum(lum) == 100
    # Pure red luminance lands at ~76 (ITU-R 601 weights).
    assert lum.index(max(lum)) in (75, 76, 77)


def test_compute_histograms_converts_non_rgb() -> None:
    img = Image.new("L", (4, 4), 128)
    lum, rgb = compute_histograms(img)
    assert lum[128] == 16
    assert rgb[128] == 16 and rgb[256 + 128] == 16 and rgb[512 + 128] == 16


def test_clipping_percentages_counts_worst_channel() -> None:
    img = Image.new("RGB", (2, 2), (128, 128, 128))
    img.putpixel((0, 0), (0, 0, 0))
    img.putpixel((1, 1), (255, 255, 255))
    _lum, rgb = compute_histograms(img)
    lo, hi = clipping_percentages(rgb)
    assert lo == 25.0
    assert hi == 25.0


def test_clipping_percentages_empty_histogram() -> None:
    assert clipping_percentages([0] * 768) == (0.0, 0.0)


def test_render_histogram_size_and_mode() -> None:
    img = Image.new("RGB", (8, 8), (10, 200, 60))
    lum, rgb = compute_histograms(img)
    out = render_histogram(lum, rgb, {"lum", "r", "g", "b"}, log_scale=False)
    assert out.size == HIST_SIZE
    assert out.mode == "RGB"


def test_render_histogram_channels_differ() -> None:
    img = Image.new("RGB", (8, 8), (255, 0, 0))
    lum, rgb = compute_histograms(img)
    r_only = render_histogram(lum, rgb, {"r"}, log_scale=False)
    b_only = render_histogram(lum, rgb, {"b"}, log_scale=False)
    assert r_only.tobytes() != b_only.tobytes()


def test_render_histogram_log_scale_runs() -> None:
    img = Image.new("RGB", (8, 8), (128, 128, 128))
    lum, rgb = compute_histograms(img)
    out = render_histogram(lum, rgb, {"lum"}, log_scale=True)
    assert out.size == HIST_SIZE


def test_render_histogram_all_zero_bins() -> None:
    # No division-by-zero: renders the bare background.
    out = render_histogram([0] * 256, [0] * 768, {"lum", "r"}, log_scale=True)
    assert out.size == HIST_SIZE


def test_render_histogram_no_channels_selected() -> None:
    out = render_histogram([1] * 256, [1] * 768, set(), log_scale=False)
    assert out.size == HIST_SIZE


def test_render_histogram_spike_lands_at_its_column() -> None:
    # A single spike at bin 128 must paint column 128 tall and leave col 20 empty.
    lum = [0] * 256
    lum[128] = 1000
    out = render_histogram(lum, [0] * 768, {"lum"}, log_scale=False)
    bg = out.getpixel((20, 50))
    assert bg == (24, 24, 24)
    spike = out.getpixel((128, 50))
    assert spike != bg


def _refresh_double(
    display_img: Image.Image | None,
) -> tuple[types.SimpleNamespace, list[Image.Image | None]]:
    """PxvApp double for refresh_display: stubs everything the method touches."""
    from pxv.enhancements import EnhancementParams

    received: list[Image.Image | None] = []
    received_params: list[object] = []
    app = types.SimpleNamespace(
        image_model=types.SimpleNamespace(
            get_display_image=lambda zoom, params, bg_color: (
                received_params.append(params),
                display_img,
            )[1],
            current_path=None,
        ),
        canvas_view=types.SimpleNamespace(zoom=1.0, display=lambda im: None),
        enhancement_params=EnhancementParams(),
        fullscreen=True,  # skips _resize_window_to_image
        enhancement_dialog=types.SimpleNamespace(update_histogram=received.append),
        _bg_color=lambda: (0, 0, 0),
        _update_title=lambda: None,
        _compare_active=False,
    )
    from pxv.app import PxvApp

    app._active_params = types.MethodType(PxvApp._active_params, app)
    app.received_params = received_params
    return app, received


def test_refresh_display_feeds_open_dialog() -> None:
    from pxv.app import PxvApp

    img = Image.new("RGB", (4, 4), (1, 2, 3))
    app, received = _refresh_double(img)
    PxvApp.refresh_display(app)
    assert received == [img]


def test_refresh_display_feeds_none_when_no_image() -> None:
    from pxv.app import PxvApp

    app, received = _refresh_double(None)
    PxvApp.refresh_display(app)
    assert received == [None]


def test_update_display_feeds_open_dialog() -> None:
    from pxv.app import PxvApp

    img = Image.new("RGB", (4, 4), (9, 9, 9))
    app, received = _refresh_double(img)
    PxvApp._update_display(app)
    assert received == [img]


def test_update_display_feeds_none_when_no_image() -> None:
    from pxv.app import PxvApp

    app, received = _refresh_double(None)
    PxvApp._update_display(app)
    assert received == [None]


def test_refresh_display_with_no_dialog_does_not_crash() -> None:
    from pxv.app import PxvApp

    app, _received = _refresh_double(None)
    app.enhancement_dialog = None
    PxvApp.refresh_display(app)  # must not raise


def test_refresh_display_uses_live_params_normally() -> None:
    from pxv.app import PxvApp

    app, _received = _refresh_double(None)
    PxvApp.refresh_display(app)
    assert app.received_params == [app.enhancement_params]


def test_refresh_display_substitutes_identity_during_compare() -> None:
    from pxv.app import PxvApp
    from pxv.tone import LevelsChannel

    app, _received = _refresh_double(None)
    app.enhancement_params.levels_master = LevelsChannel(in_black=40)
    app._compare_active = True
    PxvApp.refresh_display(app)
    assert len(app.received_params) == 1
    assert app.received_params[0] is not app.enhancement_params
    assert app.received_params[0].is_identity()
