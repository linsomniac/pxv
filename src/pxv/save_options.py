"""Per-format encoding options for Save As.

AIDEV-NOTE: Pure module (no Tk) so build_save_kwargs is unit-testable. The dialog
in dialogs.py edits a SaveOptions; commands.cmd_save_as turns it into Pillow
encoder kwargs. EXIF/metadata is handled separately via commands._exif_for_save.
"""

from __future__ import annotations

from dataclasses import dataclass

# Formats that have tunable encoding options (and therefore trigger the dialog).
FORMATS_WITH_OPTIONS = {"JPEG", "PNG", "WEBP", "TIFF"}

# UI label -> Pillow `compression` value. "None" maps to omitting the kwarg.
_TIFF_COMPRESSION = {"LZW": "tiff_lzw", "Deflate": "tiff_deflate"}

# Ordered choices for the TIFF compression dropdown.
TIFF_COMPRESSION_CHOICES = ["None", "LZW", "Deflate"]


@dataclass
class SaveOptions:
    """Session-remembered encoding parameters, one set shared across saves."""

    jpeg_quality: int = 95
    png_compress_level: int = 6
    webp_lossless: bool = False
    webp_quality: int = 80
    tiff_compression: str = "None"  # one of TIFF_COMPRESSION_CHOICES


def clamp_options(opts: SaveOptions) -> SaveOptions:
    """Return a copy with all fields bounded to valid encoder ranges.

    Guards against out-of-range values a user may type into the dialog spinboxes.
    """

    def _bound(value: int, low: int, high: int) -> int:
        return max(low, min(high, value))

    compression = opts.tiff_compression
    if compression not in TIFF_COMPRESSION_CHOICES:
        compression = "None"
    return SaveOptions(
        jpeg_quality=_bound(opts.jpeg_quality, 1, 100),
        png_compress_level=_bound(opts.png_compress_level, 0, 9),
        webp_lossless=opts.webp_lossless,
        webp_quality=_bound(opts.webp_quality, 1, 100),
        tiff_compression=compression,
    )


def build_save_kwargs(fmt: str, opts: SaveOptions) -> dict[str, object]:
    """Return Pillow encoder kwargs for `fmt` (excluding `exif`).

    Unknown / option-less formats (GIF, BMP, PPM, ...) return an empty dict.
    """
    if fmt == "JPEG":
        return {"quality": opts.jpeg_quality}
    if fmt == "PNG":
        return {"compress_level": opts.png_compress_level}
    if fmt == "WEBP":
        return {"lossless": opts.webp_lossless, "quality": opts.webp_quality}
    if fmt == "TIFF":
        mapped = _TIFF_COMPRESSION.get(opts.tiff_compression)
        return {"compression": mapped} if mapped is not None else {}
    return {}
