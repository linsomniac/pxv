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
    """Center img on a size x size cell filled with bg.

    img should already fit within size x size (see fit_thumbnail); an oversized
    image is center-clipped rather than scaled. Every tile becomes uniform
    size x size regardless of the source aspect ratio.
    """
    cell = Image.new("RGB", (size, size), bg)
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    cell.paste(img, (x, y))
    return cell


def _flatten(img: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """Composite any transparent image onto bg; convert opaque non-RGB to RGB.

    AIDEV-NOTE: Mirrors ImageModel._to_rgb_working but flattens onto the cell color
    (not white) so a tile matches the viewer's transparency rendering on the grid.
    """
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img if img.mode == "RGBA" else img.convert("RGBA")
        base = Image.new("RGB", img.size, bg)
        base.paste(rgba, mask=rgba.split()[3])
        return base
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def load_thumbnail(path: Path, size: int, bg: tuple[int, int, int] = CELL_BG) -> Image.Image:
    """Decode path into a size x size RGB thumbnail tile.

    Applies EXIF orientation and flattens transparency onto bg so the tile matches
    the viewer. Raises (OSError / PIL.UnidentifiedImageError) on an unreadable or
    non-image file — the caller maps that to a 'broken' tile.
    """
    raw = Image.open(path)
    raw.load()  # force full decode so the file handle is released
    img: Image.Image = ImageOps.exif_transpose(raw)
    img = _flatten(img, bg)
    return pad_to_square(fit_thumbnail(img, size), size, bg)


def columns_for_width(width: int, cell: int, gap: int, pad: int) -> int:
    """Number of cell-wide columns that fit in a viewport `width` px wide.

    `pad` is the grid's left+right inset; `gap` separates adjacent columns. Solves
    n*cell + (n-1)*gap <= usable for the largest n, and never returns less than 1 so
    a too-narrow window still shows a single column.
    """
    usable = width - 2 * pad
    if usable < cell or cell + gap <= 0:
        return 1
    return max(1, (usable + gap) // (cell + gap))


class ThumbnailCache:
    """Maps a resolved Path to its decoded PIL thumbnail. Survives browser toggles.

    AIDEV-NOTE: Stores PIL images, NOT Tk PhotoImage — PhotoImage is main-thread and
    bound to a live interpreter, while these survive window close/reopen. The browser
    rewraps cache hits in PhotoImage with no disk I/O. Keyed by resolved path so the
    same file reached via different relative paths hits the same entry.
    """

    def __init__(self) -> None:
        self._items: dict[Path, Image.Image] = {}

    def __contains__(self, path: Path) -> bool:
        return path.resolve() in self._items

    def get(self, path: Path) -> Image.Image | None:
        return self._items.get(path.resolve())

    def put(self, path: Path, img: Image.Image) -> None:
        self._items[path.resolve()] = img

    def clear(self) -> None:
        self._items.clear()
