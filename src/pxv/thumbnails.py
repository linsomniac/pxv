"""Thumbnail decoding and grid-layout math for the Visual Schnauzer browser.

AIDEV-NOTE: Pure I/O + pixel math, NO Tk — unit-testable headlessly. The browser
widget (thumbnail_browser.py) wraps the returned PIL images in PhotoImage on the
main thread. Transparency flattening and EXIF orientation mirror image_model.load()
so a tile matches how the viewer renders the same file.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

THUMBNAIL_SIZE = 128  # default square cell size; the single tuning knob for v1
CELL_BG = (30, 30, 30)  # dark neutral for the cell, letterbox bars, and the
# transparency flatten; the single place to theme tiles later.


def fit_thumbnail(img: Image.Image, size: int) -> Image.Image:
    """Return a copy of img scaled to fit within size x size, aspect preserved.

    Image.thumbnail only shrinks, so a smaller-than-size image is returned at its
    native size (and letterboxed by pad_to_square).
    """
    out = img.copy()
    out.thumbnail((size, size), Image.Resampling.LANCZOS)
    return out


def pad_to_square(img: Image.Image, size: int, bg: tuple[int, int, int] = CELL_BG) -> Image.Image:
    """Center an already-fit RGB image on a size x size cell filled with bg.

    Every tile becomes uniform size x size regardless of the source aspect ratio.
    """
    cell = Image.new("RGB", (size, size), bg)
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    cell.paste(img, (x, y))
    return cell
