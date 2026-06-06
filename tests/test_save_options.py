"""Tests for the pure save-options logic in save_options.py."""

from __future__ import annotations

from pxv.save_options import (
    FORMATS_WITH_OPTIONS,
    SaveOptions,
    build_save_kwargs,
    clamp_options,
)


def test_defaults() -> None:
    opts = SaveOptions()
    assert opts.jpeg_quality == 95
    assert opts.png_compress_level == 6
    assert opts.webp_lossless is False
    assert opts.webp_quality == 80
    assert opts.tiff_compression == "None"


def test_formats_with_options() -> None:
    assert FORMATS_WITH_OPTIONS == {"JPEG", "PNG", "WEBP", "TIFF"}


def test_jpeg_uses_quality() -> None:
    opts = SaveOptions(jpeg_quality=70)
    assert build_save_kwargs("JPEG", opts) == {"quality": 70}


def test_png_uses_compress_level() -> None:
    opts = SaveOptions(png_compress_level=9)
    assert build_save_kwargs("PNG", opts) == {"compress_level": 9}


def test_webp_lossy_includes_quality_and_flag() -> None:
    opts = SaveOptions(webp_lossless=False, webp_quality=60)
    assert build_save_kwargs("WEBP", opts) == {"lossless": False, "quality": 60}


def test_webp_lossless_keeps_both_keys() -> None:
    opts = SaveOptions(webp_lossless=True, webp_quality=60)
    assert build_save_kwargs("WEBP", opts) == {"lossless": True, "quality": 60}


def test_tiff_none_omits_compression() -> None:
    opts = SaveOptions(tiff_compression="None")
    assert build_save_kwargs("TIFF", opts) == {}


def test_tiff_lzw_maps_to_pillow_name() -> None:
    opts = SaveOptions(tiff_compression="LZW")
    assert build_save_kwargs("TIFF", opts) == {"compression": "tiff_lzw"}


def test_tiff_deflate_maps_to_pillow_name() -> None:
    opts = SaveOptions(tiff_compression="Deflate")
    assert build_save_kwargs("TIFF", opts) == {"compression": "tiff_deflate"}


def test_clamp_bounds_jpeg_and_webp_quality() -> None:
    assert clamp_options(SaveOptions(jpeg_quality=0)).jpeg_quality == 1
    assert clamp_options(SaveOptions(jpeg_quality=500)).jpeg_quality == 100
    assert clamp_options(SaveOptions(webp_quality=0)).webp_quality == 1
    assert clamp_options(SaveOptions(webp_quality=500)).webp_quality == 100


def test_clamp_bounds_png_compress_level() -> None:
    assert clamp_options(SaveOptions(png_compress_level=-3)).png_compress_level == 0
    assert clamp_options(SaveOptions(png_compress_level=42)).png_compress_level == 9


def test_clamp_resets_unknown_tiff_compression() -> None:
    assert clamp_options(SaveOptions(tiff_compression="bogus")).tiff_compression == "None"
    assert clamp_options(SaveOptions(tiff_compression="LZW")).tiff_compression == "LZW"


def test_clamp_leaves_valid_values_untouched() -> None:
    opts = SaveOptions(jpeg_quality=85, png_compress_level=3, webp_quality=70)
    assert clamp_options(opts) == opts


def test_gif_has_no_options() -> None:
    assert build_save_kwargs("GIF", SaveOptions()) == {}


def test_bmp_has_no_options() -> None:
    assert build_save_kwargs("BMP", SaveOptions()) == {}


def test_unknown_format_has_no_options() -> None:
    assert build_save_kwargs("PPM", SaveOptions()) == {}
