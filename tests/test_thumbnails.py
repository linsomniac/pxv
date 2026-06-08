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


from pathlib import Path

import pytest

from pxv.thumbnails import load_thumbnail


def test_load_thumbnail_flattens_transparency_onto_cell_bg(tmp_path: Path) -> None:
    p = tmp_path / "clear.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(p)  # fully transparent
    out = load_thumbnail(p, 128, CELL_BG)
    assert out.size == (128, 128)
    assert out.mode == "RGB"
    assert out.getpixel((64, 64)) == CELL_BG  # transparent pixels -> cell bg


def test_load_thumbnail_honors_exif_orientation(tmp_path: Path) -> None:
    # 100x50 landscape tagged orientation=6 becomes 50x100 portrait after transpose.
    # fit_thumbnail never upscales, so the 50x100 image pads with y-offset
    # (128-100)//2 = 14, putting content at y in [14, 114). Pixel (64, 20) is red only
    # when orientation was applied; an un-oriented 100x50 landscape pads with y-offset
    # 39, leaving (64, 20) in the letterbox.
    img = Image.new("RGB", (100, 50), (255, 0, 0))
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    p = tmp_path / "rot.jpg"
    img.save(p, exif=exif)

    out = load_thumbnail(p, 128, CELL_BG)
    assert out.size == (128, 128)
    r, g, b = out.getpixel((64, 20))
    assert r > 200 and g < 60 and b < 60  # content (red), proving portrait orientation
    assert out.getpixel((2, 64)) == CELL_BG  # left letterbox bar


def test_load_thumbnail_raises_on_non_image(tmp_path: Path) -> None:
    p = tmp_path / "notes.txt"
    p.write_text("this is not an image")
    with pytest.raises(Exception):
        load_thumbnail(p, 128, CELL_BG)


from pxv.thumbnails import columns_for_width


def test_columns_for_width_basic_counts() -> None:
    # cell=134, gap=10, pad=10 (the browser's geometry constants)
    assert columns_for_width(600, 134, 10, 10) == 4
    assert columns_for_width(1000, 134, 10, 10) == 6


def test_columns_for_width_never_below_one() -> None:
    assert columns_for_width(140, 134, 10, 10) == 1  # usable < one cell
    assert columns_for_width(0, 134, 10, 10) == 1
    assert columns_for_width(200, 134, 10, 10) == 1  # exactly one cell fits
