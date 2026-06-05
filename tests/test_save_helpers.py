"""Tests for the pure save-format helpers in commands.py."""

from __future__ import annotations

import pytest
from PIL import Image

from pxv.commands import _resolve_save_format, _rgba_to_gif


@pytest.mark.parametrize(
    ("path", "expected_fmt", "expected_path"),
    [
        ("photo.jpg", "JPEG", "photo.jpg"),
        ("photo.jpeg", "JPEG", "photo.jpeg"),
        ("image.png", "PNG", "image.png"),
        ("pic.PNG", "PNG", "pic.PNG"),  # case-insensitive ext, path preserved
        ("scan.tif", "TIFF", "scan.tif"),
        ("scan.tiff", "TIFF", "scan.tiff"),
        ("anim.gif", "GIF", "anim.gif"),
        ("bits.bmp", "BMP", "bits.bmp"),
        ("photo.webp", "WEBP", "photo.webp"),
    ],
)
def test_resolve_known_extensions(path: str, expected_fmt: str, expected_path: str) -> None:
    assert _resolve_save_format(path) == (expected_fmt, expected_path)


def test_resolve_unknown_extension_defaults_to_png() -> None:
    assert _resolve_save_format("file.xyz") == ("PNG", "file.png")


def test_resolve_missing_extension_defaults_to_png() -> None:
    assert _resolve_save_format("noext") == ("PNG", "noext.png")


def test_rgba_to_gif_reserves_transparent_index() -> None:
    img = Image.new("RGBA", (2, 1))
    img.putpixel((0, 0), (10, 20, 30, 0))  # fully transparent
    img.putpixel((1, 0), (200, 100, 50, 255))  # opaque
    palette_img, kwargs = _rgba_to_gif(img)
    assert palette_img.mode == "P"
    assert kwargs == {"transparency": 255, "optimize": True}
    assert palette_img.getpixel((0, 0)) == 255  # transparent pixel -> reserved index 255
