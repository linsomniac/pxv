"""Shared synthetic-image fixtures for the pxv test suite.

AIDEV-NOTE: Fixtures build images in-memory with Pillow so the suite needs no
committed binary assets and no display. Factory fixtures (return a callable) let
each test request exactly the image it needs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

BorderedFactory = Callable[..., Image.Image]


@pytest.fixture
def bordered() -> BorderedFactory:
    """Factory: image filled with `border`, with `inner` painted into `box`.

    `box` is (left, top, right, bottom) with exclusive right/bottom.
    """

    def _make(
        size: tuple[int, int],
        border: tuple[int, ...],
        inner: tuple[int, ...],
        box: tuple[int, int, int, int],
        mode: str = "RGB",
    ) -> Image.Image:
        img = Image.new(mode, size, border)
        block = Image.new(mode, (box[2] - box[0], box[3] - box[1]), inner)
        img.paste(block, (box[0], box[1]))
        return img

    return _make


@pytest.fixture
def make_exif() -> Callable[[], Image.Exif]:
    """Factory: a populated PIL Exif (IFD0 + Exif sub-IFD + GPS) with known values.

    AIDEV-NOTE: Built from a throwaway image's getexif() because an empty
    Image.Exif() does not always serialize freshly-added sub-IFDs; getexif() does.
    """

    def _make() -> Image.Exif:
        img = Image.new("RGB", (8, 6), (10, 20, 30))
        ex = img.getexif()
        ex[0x0112] = 6  # Orientation (rotated)
        ex[0x010E] = "orig desc"  # ImageDescription
        ex[0x010F] = "Apple"  # Make
        ex[0x0110] = "iPhone 13 Pro"  # Model
        ex[0x0132] = "2024:08:12 14:33:02"  # DateTime
        sub = ex.get_ifd(0x8769)  # Exif sub-IFD
        sub[0x829A] = (1, 250)  # ExposureTime
        sub[0x829D] = (28, 10)  # FNumber
        sub[0x8827] = 100  # ISO
        sub[0x920A] = (280, 10)  # FocalLength
        sub[0x9204] = (0, 1)  # ExposureBias
        sub[0x9003] = "2024:08:12 14:33:02"  # DateTimeOriginal
        sub[0xA002] = 9999  # ExifImageWidth (stale on purpose)
        sub[0xA003] = 8888  # ExifImageHeight (stale on purpose)
        gps = ex.get_ifd(0x8825)  # GPS sub-IFD
        gps[1] = "N"
        gps[2] = (37.0, 46.0, 29.64)
        gps[3] = "W"
        gps[4] = (122.0, 25.0, 9.6)
        return ex

    return _make


@pytest.fixture
def exif_jpeg(tmp_path: Path, make_exif: Callable[[], Image.Exif]) -> Callable[..., Path]:
    """Factory: write a JPEG carrying the known Exif and return its path."""

    def _write(name: str = "img.jpg") -> Path:
        p = tmp_path / name
        img = Image.new("RGB", (8, 6), (10, 20, 30))
        img.save(p, format="JPEG", exif=make_exif())
        return p

    return _write
