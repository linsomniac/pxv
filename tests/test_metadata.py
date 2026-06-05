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


def test_gps_to_decimal_north() -> None:
    dec = metadata._gps_to_decimal(((37, 1), (46, 1), (2964, 100)), "N")
    assert dec is not None and abs(dec - 37.7749) < 1e-3


def test_gps_to_decimal_west_is_negative() -> None:
    dec = metadata._gps_to_decimal(((122, 1), (25, 1), (960, 100)), "W")
    assert dec is not None and dec < 0 and abs(dec + 122.4193) < 1e-3


def test_decode_gps_pair() -> None:
    gps = {
        1: "N",
        2: ((37, 1), (46, 1), (2964, 100)),
        3: "W",
        4: ((122, 1), (25, 1), (960, 100)),
    }
    coords = metadata.decode_gps(gps)
    assert coords is not None
    lat, lon = coords
    assert lat > 0 and lon < 0


def test_decode_gps_missing_returns_none() -> None:
    assert metadata.decode_gps({}) is None


from pathlib import Path  # noqa: E402  (grouped with new metadata tests)

from PIL import Image  # noqa: E402


def test_read_metadata_basic(exif_jpeg) -> None:
    p = exif_jpeg()
    raw = Image.open(p)
    raw.load()
    meta = metadata.read_metadata(raw, p)
    assert meta.path == p
    assert meta.file_format == "JPEG"
    assert meta.mode == "RGB"
    assert meta.size == (8, 6)
    assert meta.file_size == p.stat().st_size
    assert meta.exif.get(0x010E) == "orig desc"


def test_read_metadata_no_exif(tmp_path: Path) -> None:
    p = tmp_path / "plain.png"
    Image.new("RGB", (4, 4)).save(p)
    raw = Image.open(p)
    raw.load()
    meta = metadata.read_metadata(raw, p)
    assert meta.has_exif() is False


def test_metadata_restore_reverts_edits(exif_jpeg) -> None:
    p = exif_jpeg()
    raw = Image.open(p)
    raw.load()
    meta = metadata.read_metadata(raw, p)
    meta.exif[0x010E] = "changed"
    meta.restore()
    assert meta.exif.get(0x010E) == "orig desc"
