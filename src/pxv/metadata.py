"""EXIF/metadata reading, decoding, sanitizing, and redaction — pure logic, no Tk.

AIDEV-NOTE: pxv reads EXIF only for orientation at load (ImageModel.load) and
historically dropped it on save. This module captures and decodes metadata for the
info panel, and produces a sanitized Exif for the optional "keep metadata" save.
Mirrors enhancements.py (pure pipeline) vs enhancement_dialog.py (Tk widget).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import ExifTags, Image
from PIL.ExifTags import GPSTAGS, TAGS

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


def _exif_from_bytes(data: bytes) -> Image.Exif:
    """Reconstruct an Exif object from bytes previously produced by Exif.tobytes()."""
    exif = Image.Exif()
    if data:
        exif.load(data)
    return exif


@dataclass
class Section:
    """A titled group of (label, value) display rows for the info panel."""

    title: str
    rows: list[tuple[str, str]]


@dataclass
class ImageMetadata:
    """Captured file facts plus the (mutable) working EXIF for one loaded image."""

    path: Path
    file_size: int | None
    file_format: str | None
    mode: str
    size: tuple[int, int]
    exif: Image.Exif
    original_exif_bytes: bytes

    def has_exif(self) -> bool:
        return bool(dict(self.exif)) or bool(dict(self.exif.get_ifd(_EXIF_IFD)))

    def restore(self) -> None:
        """Revert all edits/redactions back to the metadata captured at load."""
        self.exif = _exif_from_bytes(self.original_exif_bytes)


def read_metadata(raw: Image.Image, path: Path) -> ImageMetadata:
    """Capture file facts and EXIF from a freshly-opened image.

    AIDEV-NOTE: Must be called on the raw, pre-exif_transpose image (where
    getexif() is reliable). raw.load() must already have run.
    """
    try:
        file_size: int | None = path.stat().st_size
    except OSError:
        file_size = None
    exif = raw.getexif()
    return ImageMetadata(
        path=path,
        file_size=file_size,
        file_format=raw.format,
        mode=raw.mode,
        size=raw.size,
        exif=exif,
        original_exif_bytes=exif.tobytes(),
    )


def _safe_str(value: object, limit: int = 80) -> str:
    """Render an arbitrary EXIF value as a single trimmed display line."""
    try:
        s = value.decode("ascii", "replace") if isinstance(value, bytes) else str(value)
    except Exception:
        s = repr(value)
    s = s.replace("\r", " ").replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def build_sections(meta: ImageMetadata) -> list[Section]:
    """Group decoded metadata into File / Camera / Exposure / Location sections."""
    exif = meta.exif
    sub = exif.get_ifd(_EXIF_IFD)
    gps = exif.get_ifd(_GPS_IFD)
    sections: list[Section] = []

    sections.append(
        Section(
            "File",
            [
                ("Name", meta.path.name),
                ("Path", str(meta.path)),
                ("Size", _format_size(meta.file_size)),
                ("Format/Mode", f"{meta.file_format or '?'} · {meta.mode}"),
                ("Dimensions", f"{meta.size[0]} × {meta.size[1]}"),
            ],
        )
    )

    cam_rows: list[tuple[str, str]] = []
    make = exif.get(_MAKE)
    model = exif.get(_MODEL)
    if make or model:
        cam_rows.append(("Make/Model", " ".join(str(x) for x in (make, model) if x)))
    if _LENS_MODEL in sub:
        cam_rows.append(("Lens", _safe_str(sub[_LENS_MODEL])))
    taken = sub.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
    if taken:
        cam_rows.append(("Taken", _format_datetime(taken)))
    if _SOFTWARE in exif:
        cam_rows.append(("Software", _safe_str(exif[_SOFTWARE])))
    if cam_rows:
        sections.append(Section("Camera", cam_rows))

    parts: list[str] = []
    for fn, tag in (
        (_format_exposure_time, _EXPOSURE_TIME),
        (_format_fnumber, _FNUMBER),
        (_format_iso, _ISO),
        (_format_focal_length, _FOCAL_LENGTH),
        (_format_exposure_bias, _EXPOSURE_BIAS),
    ):
        if tag in sub:
            rendered = fn(sub[tag])
            if rendered:
                parts.append(rendered)
    if parts:
        sections.append(Section("Exposure", [("Settings", " · ".join(parts))]))

    coords = decode_gps(gps)
    if coords:
        sections.append(Section("Location", [("GPS", f"{coords[0]:.6f}, {coords[1]:.6f}")]))

    return sections


def all_tags(meta: ImageMetadata) -> list[tuple[int, str, str]]:
    """Return every decoded tag as (id, name, value), sorted, for the full list view."""
    rows: list[tuple[int, str, str]] = []
    for tag_id, value in meta.exif.items():
        rows.append((tag_id, TAGS.get(tag_id, hex(tag_id)), _safe_str(value)))
    for tag_id, value in meta.exif.get_ifd(_EXIF_IFD).items():
        rows.append((tag_id, TAGS.get(tag_id, hex(tag_id)), _safe_str(value)))
    for tag_id, value in meta.exif.get_ifd(_GPS_IFD).items():
        rows.append((tag_id, f"GPS {GPSTAGS.get(tag_id, hex(tag_id))}", _safe_str(value)))
    return sorted(rows)
