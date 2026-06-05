"""Tests for the pure-logic metadata module."""

from __future__ import annotations

from PIL.TiffImagePlugin import IFDRational

from pxv import metadata


def test_to_float_tuple_rational() -> None:
    assert metadata._to_float((28, 10)) == 2.8


def test_to_float_zero_denominator_returns_none() -> None:
    assert metadata._to_float((5, 0)) is None


def test_to_float_ifdrational() -> None:
    assert metadata._to_float(IFDRational(1, 4)) == 0.25


def test_to_float_bad_type_returns_none() -> None:
    assert metadata._to_float("nope") is None


def test_format_exposure_time_fraction() -> None:
    assert metadata._format_exposure_time((1, 250)) == "1/250 s"


def test_format_exposure_time_long() -> None:
    assert metadata._format_exposure_time((2, 1)) == "2 s"


def test_format_fnumber() -> None:
    assert metadata._format_fnumber((28, 10)) == "f/2.8"


def test_format_focal_length() -> None:
    assert metadata._format_focal_length((280, 10)) == "28 mm"


def test_format_exposure_bias_zero() -> None:
    assert metadata._format_exposure_bias((0, 1)) == "+0.0 EV"


def test_format_iso_int() -> None:
    assert metadata._format_iso(100) == "ISO 100"


def test_format_iso_sequence() -> None:
    assert metadata._format_iso([200, 0]) == "ISO 200"


def test_format_fnumber_zero_denominator_returns_none() -> None:
    assert metadata._format_fnumber((1, 0)) is None


def test_format_size_mb() -> None:
    assert metadata._format_size(3_581_234) == "3.4 MB (3,581,234 bytes)"


def test_format_size_small() -> None:
    assert metadata._format_size(512) == "512 bytes"


def test_format_size_none() -> None:
    assert metadata._format_size(None) == "unknown"


def test_format_datetime() -> None:
    assert metadata._format_datetime("2024:08:12 14:33:02") == "2024-08-12 14:33:02"
