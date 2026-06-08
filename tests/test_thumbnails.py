"""Display-free tests for the pure thumbnail module (no Tk)."""

from __future__ import annotations

from PIL import Image

from pxv.thumbnails import CELL_BG, fit_thumbnail, pad_to_square


def test_fit_thumbnail_landscape_keeps_aspect_within_bounds() -> None:
    out = fit_thumbnail(Image.new("RGB", (200, 100), (255, 0, 0)), 128)
    assert out.size == (128, 64)


def test_fit_thumbnail_portrait_keeps_aspect_within_bounds() -> None:
    out = fit_thumbnail(Image.new("RGB", (100, 200), (255, 0, 0)), 128)
    assert out.size == (64, 128)


def test_fit_thumbnail_does_not_upscale_small_image() -> None:
    out = fit_thumbnail(Image.new("RGB", (50, 50), (255, 0, 0)), 128)
    assert out.size == (50, 50)


def test_pad_to_square_centers_on_background_cell() -> None:
    fitted = fit_thumbnail(Image.new("RGB", (200, 100), (255, 0, 0)), 128)
    out = pad_to_square(fitted, 128, CELL_BG)
    assert out.size == (128, 128)
    assert out.getpixel((0, 0)) == CELL_BG  # corner is letterbox
    assert out.getpixel((64, 64)) == (255, 0, 0)  # center is the image
