"""Tests for histogram computation, rendering, and app feed (display-free).

AIDEV-NOTE: The compute/render functions are pure (no Tk) by design, mirroring
the canvas_view.py geometry split, so this whole file runs headlessly. The
HistogramPanel widget itself is exercised in test_enhancement_dialog_ui.py
under a real display.
"""

from __future__ import annotations

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
    spike = out.getpixel((128, 50))
    assert spike != bg
