"""Tests for the pure slideshow-interval helpers in slideshow.py."""

from __future__ import annotations

from pxv.slideshow import (
    DEFAULT_SLIDESHOW_SECONDS,
    MIN_SLIDESHOW_SECONDS,
    adjusted_interval_ms,
    interval_to_ms,
)


def test_default_constant() -> None:
    assert DEFAULT_SLIDESHOW_SECONDS == 4
    assert MIN_SLIDESHOW_SECONDS == 1


def test_interval_to_ms_converts_seconds() -> None:
    assert interval_to_ms(4) == 4000
    assert interval_to_ms(2.5) == 2500


def test_interval_to_ms_clamps_below_minimum() -> None:
    assert interval_to_ms(0) == MIN_SLIDESHOW_SECONDS * 1000
    assert interval_to_ms(-3) == MIN_SLIDESHOW_SECONDS * 1000
    assert interval_to_ms(0.2) == MIN_SLIDESHOW_SECONDS * 1000


def test_adjusted_interval_increments() -> None:
    assert adjusted_interval_ms(4000, 1) == 5000


def test_adjusted_interval_decrements() -> None:
    assert adjusted_interval_ms(4000, -1) == 3000


def test_adjusted_interval_clamps_to_minimum() -> None:
    assert adjusted_interval_ms(1000, -1) == MIN_SLIDESHOW_SECONDS * 1000
    assert adjusted_interval_ms(1000, -5) == MIN_SLIDESHOW_SECONDS * 1000
