"""EXIF/metadata reading, decoding, sanitizing, and redaction — pure logic, no Tk.

AIDEV-NOTE: pxv reads EXIF only for orientation at load (ImageModel.load) and
historically dropped it on save. This module captures and decodes metadata for the
info panel, and produces a sanitized Exif for the optional "keep metadata" save.
Mirrors enhancements.py (pure pipeline) vs enhancement_dialog.py (Tk widget).
"""

from __future__ import annotations

from PIL import ExifTags

# Sub-IFD ids (verified on Pillow 12.2.0)
_EXIF_IFD = ExifTags.IFD.Exif  # 0x8769 — exposure/camera detail tags
_GPS_IFD = ExifTags.IFD.GPSInfo  # 0x8825 — GPS location tags

# IFD0 tag ids
_ORIENTATION = 0x0112
_DESCRIPTION = 0x010E
_MAKE = 0x010F
_MODEL = 0x0110
_SOFTWARE = 0x0131
_DATETIME = 0x0132
_ARTIST = 0x013B
_COPYRIGHT = 0x8298

# Exif sub-IFD tag ids
_DATETIME_ORIGINAL = 0x9003
_EXPOSURE_TIME = 0x829A
_FNUMBER = 0x829D
_ISO = 0x8827
_FOCAL_LENGTH = 0x920A
_EXPOSURE_BIAS = 0x9204
_LENS_MODEL = 0xA434
_EXIF_IMAGE_WIDTH = 0xA002
_EXIF_IMAGE_HEIGHT = 0xA003


def _to_float(value: object) -> float | None:
    """Coerce an EXIF rational to a float.

    Handles IFDRational (float()-able), a (numerator, denominator) tuple, or a
    plain number. Returns None on a zero denominator or an uncoercible value so
    callers can skip the field instead of crashing the panel.
    """
    try:
        if isinstance(value, tuple) and len(value) == 2:
            num, den = value
            if not den:
                return None
            return float(num) / float(den)
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _format_exposure_time(value: object) -> str | None:
    f = _to_float(value)
    if f is None or f <= 0:
        return None
    if f >= 1:
        return f"{f:.0f} s"
    return f"1/{round(1 / f)} s"


def _format_fnumber(value: object) -> str | None:
    f = _to_float(value)
    return f"f/{f:g}" if f is not None else None


def _format_focal_length(value: object) -> str | None:
    f = _to_float(value)
    return f"{f:g} mm" if f is not None else None


def _format_exposure_bias(value: object) -> str | None:
    f = _to_float(value)
    return f"{f:+.1f} EV" if f is not None else None


def _format_iso(value: object) -> str | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return f"ISO {value}" if value is not None else None


def _format_size(n: int | None) -> str:
    if n is None:
        return "unknown"
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit} ({n:,} bytes)"
    return f"{n:,} bytes"


def _format_datetime(value: object) -> str:
    """Normalize an EXIF datetime ('YYYY:MM:DD HH:MM:SS') for display."""
    s = str(value).strip()
    date_part, _, time_part = s.partition(" ")
    date_part = date_part.replace(":", "-")
    return f"{date_part} {time_part}".strip()


def _gps_to_decimal(coord: object, ref: object) -> float | None:
    """Convert a (deg, min, sec) rational triple + hemisphere ref to decimal degrees."""
    try:
        d = _to_float(coord[0])  # type: ignore[index]
        m = _to_float(coord[1])  # type: ignore[index]
        s = _to_float(coord[2])  # type: ignore[index]
    except (TypeError, IndexError, KeyError):
        return None
    if d is None or m is None or s is None:
        return None
    dec = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        dec = -dec
    return dec


def decode_gps(gps_ifd: dict[int, object]) -> tuple[float, float] | None:
    """Decode a GPS IFD into a (latitude, longitude) decimal-degree pair, or None."""
    lat = _gps_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
    lon = _gps_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
    if lat is None or lon is None:
        return None
    return (lat, lon)
