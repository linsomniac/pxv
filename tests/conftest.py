"""Shared synthetic-image fixtures for the pxv test suite.

AIDEV-NOTE: Fixtures build images in-memory with Pillow so the suite needs no
committed binary assets and no display. Factory fixtures (return a callable) let
each test request exactly the image it needs.
"""

from __future__ import annotations

from collections.abc import Callable

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
