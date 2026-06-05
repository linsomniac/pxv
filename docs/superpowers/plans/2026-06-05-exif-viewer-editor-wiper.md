# EXIF Viewer / Light Editor / Wiper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an xv-style image info / EXIF panel (the `i` key) with a small curated metadata editor and a metadata wiper, persisted only on Save As.

**Architecture:** A new pure-logic `metadata.py` module (decode/format, group into display sections, sanitize-for-save, redact GPS, get/set editable fields) mirrors the `enhancements.py` ↔ `enhancement_dialog.py` split. `ImageModel` captures the EXIF at load (currently read for orientation then discarded) and holds a `keep_metadata` flag (default off = today's strip behavior). A thin non-modal `InfoDialog` renders the panel and follows navigation. `cmd_save_as` writes a sanitized EXIF only when keep is on.

**Tech Stack:** Python 3.10+, Pillow ≥10 (verified on 12.2.0), Tkinter/ttk, pytest, ruff, mypy. Use `uv run` for all commands.

**Design spec:** `docs/superpowers/specs/2026-06-05-exif-viewer-editor-wiper-design.md`

**Tooling notes (verified against this repo):** `ruff` line-length is 99 and `ruff format` is run before `ruff check` in every task, so long signatures/strings are auto-wrapped. `mypy` is `strict = true` but scoped to `src/pxv/` only — **tests are not type-checked**, so test functions take bare fixture params (`make_exif`, `exif_jpeg`) and only annotate `-> None`. PIL is configured `ignore_missing_imports`, so all `PIL` types are `Any`; src code must avoid returning `Any` from non-`Any`-typed functions (strict `warn_return_any`) and must not leave unused `# type: ignore` (strict `warn_unused_ignores`).

---

## File Structure

- **Create** `src/pxv/metadata.py` — pure logic: EXIF decode/format, `build_sections`, `all_tags`, `build_save_exif`, `redact_gps`, editable get/set, `ImageMetadata`/`Section` dataclasses, `read_metadata`. No Tkinter.
- **Create** `src/pxv/info_dialog.py` — non-modal `InfoDialog(tk.Toplevel)`, modeled on `enhancement_dialog.py`.
- **Create** `tests/test_metadata.py` — unit tests for all pure logic.
- **Modify** `tests/conftest.py` — add `make_exif` and `exif_jpeg` fixtures.
- **Modify** `src/pxv/image_model.py` — capture metadata at load; `keep_metadata`; reset restores metadata.
- **Modify** `src/pxv/commands.py` — `_EXIF_WRITE_FORMATS`, `_exif_for_save`, `cmd_save_as` wiring, `cmd_info`.
- **Modify** `tests/test_image_model.py` — metadata capture/reset tests.
- **Modify** `src/pxv/app.py` — `info_dialog` attribute, `i` keybinding, refresh hook in `load_current`.
- **Modify** `src/pxv/context_menu.py` — "Info..." entry.
- **Modify** `src/pxv/dialogs.py` — add `i` to the `KEYBINDINGS` help table.
- **Modify** `CHANGELOG.md` and `README.md` — document the feature and shortcut.

**Pillow tag-id reference (verified):** Orientation `0x0112`, ImageDescription `0x010E`, Make `0x010F`, Model `0x0110`, Software `0x0131`, DateTime `0x0132`, Artist `0x013B`, Copyright `0x8298`. Exif sub-IFD `ExifTags.IFD.Exif` (`0x8769`): ExposureTime `0x829A`, FNumber `0x829D`, ISOSpeedRatings `0x8827`, DateTimeOriginal `0x9003`, ExposureBiasValue `0x9204`, FocalLength `0x920A`, ExifImageWidth `0xA002`, ExifImageHeight `0xA003`, LensModel `0xA434`. GPS sub-IFD `ExifTags.IFD.GPSInfo` (`0x8825`): GPSLatitudeRef `1`, GPSLatitude `2`, GPSLongitudeRef `3`, GPSLongitude `4`.

---

## Task 1: metadata.py decoding primitives

**Files:**
- Create: `src/pxv/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Create the module skeleton with constants and decode helpers**

Create `src/pxv/metadata.py`:

```python
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
```

- [ ] **Step 2: Write failing tests for the decode helpers**

Create `tests/test_metadata.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: all PASS (the helpers exist).

- [ ] **Step 4: Lint and type-check**

Run: `uv run ruff format src/pxv/metadata.py tests/test_metadata.py && uv run ruff check src/pxv/metadata.py tests/test_metadata.py && uv run mypy src/pxv/metadata.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/pxv/metadata.py tests/test_metadata.py
git commit -m "feat(metadata): add EXIF value decoding primitives"
```

---

## Task 2: GPS coordinate decoding

**Files:**
- Modify: `src/pxv/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests for GPS decoding**

Append to `tests/test_metadata.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -k gps -v`
Expected: FAIL with `AttributeError: module 'pxv.metadata' has no attribute '_gps_to_decimal'`.

- [ ] **Step 3: Implement GPS decoding**

Append to `src/pxv/metadata.py` (after `_format_datetime`):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -k gps -v`
Expected: all PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/pxv/metadata.py tests/test_metadata.py
uv run ruff check src/pxv/metadata.py tests/test_metadata.py
uv run mypy src/pxv/metadata.py
git add src/pxv/metadata.py tests/test_metadata.py
git commit -m "feat(metadata): decode GPS coordinates to decimal degrees"
```

---

## Task 3: ImageMetadata, read_metadata, restore, and fixtures

**Files:**
- Modify: `src/pxv/metadata.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Add shared EXIF fixtures to conftest**

Append to `tests/conftest.py`:

```python
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
```

Add the imports this needs at the top of `tests/conftest.py` (the file already imports `pytest` and `from PIL import Image`; add `Path` and keep `Callable`):

```python
from pathlib import Path
```

(`from collections.abc import Callable` is already imported in conftest.)

- [ ] **Step 2: Write failing tests for ImageMetadata / read_metadata / restore**

Append to `tests/test_metadata.py`:

```python
from pathlib import Path  # noqa: E402  (grouped with new metadata tests)

from PIL import Image  # noqa: E402


def test_read_metadata_basic(exif_jpeg) -> None:    p = exif_jpeg()
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


def test_metadata_restore_reverts_edits(exif_jpeg) -> None:    p = exif_jpeg()
    raw = Image.open(p)
    raw.load()
    meta = metadata.read_metadata(raw, p)
    meta.exif[0x010E] = "changed"
    meta.restore()
    assert meta.exif.get(0x010E) == "orig desc"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -k "read_metadata or restore" -v`
Expected: FAIL with `AttributeError: module 'pxv.metadata' has no attribute 'read_metadata'`.

- [ ] **Step 4: Implement the dataclasses, read_metadata, and restore**

Append to `src/pxv/metadata.py` (after the GPS functions):

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -k "read_metadata or restore" -v`
Expected: all PASS.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format src/pxv/metadata.py tests/test_metadata.py tests/conftest.py
uv run ruff check src/pxv/metadata.py tests/test_metadata.py tests/conftest.py
uv run mypy src/pxv/metadata.py
git add src/pxv/metadata.py tests/test_metadata.py tests/conftest.py
git commit -m "feat(metadata): add ImageMetadata, read_metadata, and reset/restore"
```

---

## Task 4: build_sections and all_tags

**Files:**
- Modify: `src/pxv/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_metadata.py`:

```python
def _meta(exif, tmp_path: Path) -> "metadata.ImageMetadata":    """Wrap a bare Exif in an ImageMetadata for section/save tests (no file needed)."""
    return metadata.ImageMetadata(
        path=tmp_path / "x.jpg",
        file_size=3_581_234,
        file_format="JPEG",
        mode="RGB",
        size=(8, 6),
        exif=exif,
        original_exif_bytes=exif.tobytes(),
    )


def test_build_sections_groups(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    sections = {s.title: dict(s.rows) for s in metadata.build_sections(meta)}
    assert sections["File"]["Dimensions"] == "8 × 6"
    assert "iPhone 13 Pro" in sections["Camera"]["Make/Model"]
    assert "f/2.8" in sections["Exposure"]["Settings"]
    assert "37.77" in sections["Location"]["GPS"]


def test_build_sections_no_exif(tmp_path: Path) -> None:
    meta = _meta(Image.new("RGB", (4, 4)).getexif(), tmp_path)
    titles = [s.title for s in metadata.build_sections(meta)]
    assert "File" in titles
    assert "Camera" not in titles
    assert "Location" not in titles


def test_all_tags_includes_named_and_gps(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    names = {name for _id, name, _val in metadata.all_tags(meta)}
    assert "ImageDescription" in names
    assert "Make" in names
    assert any(n.startswith("GPS ") for n in names)
```

(Add `from PIL import ExifTags` near the other imports in `tests/test_metadata.py` — used by later tasks too.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -k "sections or all_tags" -v`
Expected: FAIL with `AttributeError: module 'pxv.metadata' has no attribute 'build_sections'`.

- [ ] **Step 3: Implement build_sections and all_tags**

Append to `src/pxv/metadata.py`:

```python
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
        sections.append(
            Section("Location", [("GPS", f"{coords[0]:.6f}, {coords[1]:.6f}")])
        )

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -k "sections or all_tags" -v`
Expected: all PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/pxv/metadata.py tests/test_metadata.py
uv run ruff check src/pxv/metadata.py tests/test_metadata.py
uv run mypy src/pxv/metadata.py
git add src/pxv/metadata.py tests/test_metadata.py
git commit -m "feat(metadata): group decoded tags into display sections + full list"
```

---

## Task 5: build_save_exif, redact_gps, and editable fields

**Files:**
- Modify: `src/pxv/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests (round-trip via in-memory JPEG)**

Append to `tests/test_metadata.py`:

```python
import io  # noqa: E402


def _reload_exif_via_jpeg(exif_obj) -> "Image.Exif":    img = Image.new("RGB", (8, 6))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    return Image.open(buf).getexif()


def test_build_save_exif_resets_orientation_and_drops_dims(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    reloaded = _reload_exif_via_jpeg(metadata.build_save_exif(meta))
    assert reloaded.get(0x0112) == 1
    sub = reloaded.get_ifd(ExifTags.IFD.Exif)
    assert 0xA002 not in sub and 0xA003 not in sub
    assert sub.get(0x829A) == (1, 250)  # ExposureTime survives sanitizing


def test_build_save_exif_does_not_mutate_working(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    metadata.build_save_exif(meta)
    assert meta.exif.get(0x0112) == 6  # working orientation untouched


def test_redact_gps_removes_location(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    metadata.redact_gps(meta.exif)
    assert metadata.decode_gps(meta.exif.get_ifd(ExifTags.IFD.GPSInfo)) is None
    reloaded = _reload_exif_via_jpeg(metadata.build_save_exif(meta))
    assert len(reloaded.get_ifd(ExifTags.IFD.GPSInfo)) == 0


def test_set_and_get_editable_description(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    metadata.set_editable(meta, "description", "hello")
    assert metadata.get_editable(meta, "description") == "hello"
    reloaded = _reload_exif_via_jpeg(metadata.build_save_exif(meta))
    assert reloaded.get(0x010E) == "hello"


def test_set_editable_date_writes_subifd(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    metadata.set_editable(meta, "date", "2030:01:02 03:04:05")
    reloaded = _reload_exif_via_jpeg(metadata.build_save_exif(meta))
    assert reloaded.get_ifd(ExifTags.IFD.Exif).get(0x9003) == "2030:01:02 03:04:05"


def test_set_editable_empty_clears(make_exif, tmp_path: Path) -> None:    meta = _meta(make_exif(), tmp_path)
    metadata.set_editable(meta, "description", "")
    assert metadata.get_editable(meta, "description") == ""


def test_editable_fields_keys() -> None:
    keys = [key for key, _label, _ifd, _tag in metadata.EDITABLE_FIELDS]
    assert keys == ["description", "artist", "copyright", "date"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -k "save_exif or redact or editable" -v`
Expected: FAIL with `AttributeError: ... 'build_save_exif'`.

- [ ] **Step 3: Implement save sanitizing, redaction, and editable fields**

First, add `Any` to the typing imports at the top of `src/pxv/metadata.py` (it is first used here; do not add it earlier or ruff F401 will flag it as unused):

```python
from typing import Any
```

Then append to `src/pxv/metadata.py`:

```python
# Editable fields: (key, label, ifd id or None for IFD0, tag id). Verified writable.
EDITABLE_FIELDS: list[tuple[str, str, int | None, int]] = [
    ("description", "Description", None, _DESCRIPTION),
    ("artist", "Artist", None, _ARTIST),
    ("copyright", "Copyright", None, _COPYRIGHT),
    ("date", "Date", _EXIF_IFD, _DATETIME_ORIGINAL),
]


def _field_container(exif: Image.Exif, ifd: int | None) -> Any:
    # AIDEV-NOTE: returns the Exif (IFD0) or a sub-IFD dict; typed Any because PIL is
    # untyped here and both support the mapping ops set_editable/get_editable use.
    return exif if ifd is None else exif.get_ifd(ifd)


def get_editable(meta: ImageMetadata, key: str) -> str:
    for k, _label, ifd, tag in EDITABLE_FIELDS:
        if k == key:
            value = _field_container(meta.exif, ifd).get(tag, "")
            return str(value) if value else ""
    return ""


def set_editable(meta: ImageMetadata, key: str, value: str) -> None:
    for k, _label, ifd, tag in EDITABLE_FIELDS:
        if k == key:
            container = _field_container(meta.exif, ifd)
            if value:
                container[tag] = value
            else:
                container.pop(tag, None)
            return


def redact_gps(exif: Image.Exif) -> None:
    """Remove GPS location from the working EXIF (in place).

    AIDEV-NOTE: Image.Exif.get_ifd() caches the parsed sub-IFD, so deleting only the
    IFD0 pointer leaves a stale GPS dict that build_sections would still display after
    "Remove GPS". Clear the cached dict (updates the in-memory view immediately) and
    drop the IFD0 pointer (so it is not re-serialized on save). Verified necessary.
    """
    exif.get_ifd(_GPS_IFD).clear()
    if _GPS_IFD in exif:
        del exif[_GPS_IFD]


def build_save_exif(meta: ImageMetadata) -> Image.Exif:
    """Produce a sanitized clone of the working EXIF for writing on save.

    AIDEV-NOTE: Clones via tobytes()/load() so the panel's working EXIF is not
    mutated. Sanitizes unconditionally — orientation is reset to 1 (already baked
    into the saved pixels by exif_transpose at load) and the stale embedded
    pixel-dimension tags are dropped — so preserved EXIF can never contradict the
    saved image. The embedded thumbnail (IFD1) is dropped inherently by tobytes().
    """
    clone = _exif_from_bytes(meta.exif.tobytes())
    clone[_ORIENTATION] = 1
    sub = clone.get_ifd(_EXIF_IFD)
    sub.pop(_EXIF_IMAGE_WIDTH, None)
    sub.pop(_EXIF_IMAGE_HEIGHT, None)
    return clone
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: all PASS (whole metadata suite green).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/pxv/metadata.py tests/test_metadata.py
uv run ruff check src/pxv/metadata.py tests/test_metadata.py
uv run mypy src/pxv/metadata.py
git add src/pxv/metadata.py tests/test_metadata.py
git commit -m "feat(metadata): sanitize-for-save, GPS redaction, editable fields"
```

---

## Task 6: ImageModel integration

**Files:**
- Modify: `src/pxv/image_model.py` (imports; `__init__` lines 22-30; `load` after line 67; `reset` lines 272-278)
- Test: `tests/test_image_model.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_image_model.py`:

```python
def test_load_captures_metadata(exif_jpeg) -> None:    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())
    assert model.metadata is not None
    assert model.metadata.exif.get(0x010E) == "orig desc"
    assert model.keep_metadata is False


def test_reset_restores_metadata_and_keep_flag(exif_jpeg) -> None:    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())
    assert model.metadata is not None
    model.metadata.exif[0x010E] = "edited"
    model.keep_metadata = True
    model.reset()
    assert model.metadata.exif.get(0x010E) == "orig desc"
    assert model.keep_metadata is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_image_model.py -k "metadata or keep_flag" -v`
Expected: FAIL with `AttributeError: 'ImageModel' object has no attribute 'metadata'`.

- [ ] **Step 3: Add the metadata import**

In `src/pxv/image_model.py`, the existing import block is:

```python
from pxv.enhancements import EnhancementParams, apply_enhancements
```

Add directly below it:

```python
from pxv import metadata
```

- [ ] **Step 4: Add the new attributes in `__init__`**

In `ImageModel.__init__`, after the existing `self._pre_crop_rgba` line (currently `image_model.py:30`):

```python
        # AIDEV-NOTE: EXIF/metadata captured at load. keep_metadata gates whether it
        # is written on Save As; default False preserves pxv's historical strip-on-save.
        self.metadata: metadata.ImageMetadata | None = None
        self.keep_metadata: bool = False
```

- [ ] **Step 5: Capture metadata in `load`**

In `ImageModel.load`, immediately after `raw.load()` (currently `image_model.py:67`) and before the `exif_transpose` call:

```python
        # AIDEV-NOTE: Capture metadata from the raw, pre-transpose image where
        # getexif() is reliable. exif_transpose below would normalize orientation.
        self.metadata = metadata.read_metadata(raw, path)
        self.keep_metadata = False
```

- [ ] **Step 6: Restore metadata in `reset`**

In `ImageModel.reset`, after the existing body that restores `working_image` and `_save_rgba` (currently ends at `image_model.py:278`), add at the end of the method:

```python
        if self.metadata is not None:
            self.metadata.restore()
        self.keep_metadata = False
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_image_model.py -v`
Expected: all PASS (including the pre-existing image_model tests).

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff format src/pxv/image_model.py tests/test_image_model.py
uv run ruff check src/pxv/image_model.py tests/test_image_model.py
uv run mypy src/pxv/
git add src/pxv/image_model.py tests/test_image_model.py
git commit -m "feat(image_model): capture EXIF at load, keep_metadata flag, reset"
```

---

## Task 7: commands.py — save wiring and cmd_info

**Files:**
- Modify: `src/pxv/commands.py` (constants near line 42; `cmd_save_as` lines 96-138; new `cmd_info`)
- Test: `tests/test_save_helpers.py`

- [ ] **Step 1: Write failing tests for the save-exif decision and round-trip**

Append to `tests/test_save_helpers.py`:

```python
def test_exif_for_save_keep_jpeg(exif_jpeg) -> None:    from pxv import commands
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())
    model.keep_metadata = True
    assert commands._exif_for_save(model, "JPEG") is not None


def test_exif_for_save_strip_by_default(exif_jpeg) -> None:    from pxv import commands
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())  # keep_metadata defaults to False
    assert commands._exif_for_save(model, "JPEG") is None


def test_exif_for_save_unsupported_format(exif_jpeg) -> None:    from pxv import commands
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())
    model.keep_metadata = True
    assert commands._exif_for_save(model, "GIF") is None


def test_keep_metadata_roundtrip_on_disk(exif_jpeg, tmp_path) -> None:    from PIL import Image

    from pxv import commands
    from pxv.enhancements import EnhancementParams
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())
    model.keep_metadata = True
    save_img = model.get_save_image(EnhancementParams())
    assert save_img is not None
    out = tmp_path / "out.jpg"
    save_img.save(out, format="JPEG", exif=commands._exif_for_save(model, "JPEG"))

    reloaded = Image.open(out).getexif()
    assert reloaded.get(0x010E) == "orig desc"
    assert reloaded.get(0x0112) == 1  # sanitized orientation


def test_strip_default_roundtrip_has_no_exif(exif_jpeg, tmp_path) -> None:    from PIL import Image

    from pxv import commands
    from pxv.enhancements import EnhancementParams
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())  # default: strip
    save_img = model.get_save_image(EnhancementParams())
    assert save_img is not None
    out = tmp_path / "out.jpg"
    exif_bytes = commands._exif_for_save(model, "JPEG")
    kwargs = {"exif": exif_bytes} if exif_bytes is not None else {}
    save_img.save(out, format="JPEG", **kwargs)

    assert not Image.open(out).getexif()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_save_helpers.py -k exif -v`
Expected: FAIL with `AttributeError: module 'pxv.commands' has no attribute '_exif_for_save'`.

- [ ] **Step 3: Add the metadata import and write-format set**

In `src/pxv/commands.py`, add to the imports (the file already has `from PIL import Image`):

```python
from pxv import metadata
```

After the existing `_ALPHA_FORMATS = {"PNG", "WEBP", "TIFF"}` line (currently `commands.py:42`):

```python
# Formats Pillow can write an exif= block to. GIF/BMP/PPM/ICO cannot.
_EXIF_WRITE_FORMATS = {"JPEG", "TIFF", "WEBP", "PNG"}
```

- [ ] **Step 4: Add the `_exif_for_save` helper**

Add this module-level function in `src/pxv/commands.py` (place it just above `cmd_save_as`):

```python
def _exif_for_save(model: "ImageModel", fmt: str) -> bytes | None:
    """Return sanitized EXIF bytes to write, or None to strip (today's default).

    AIDEV-NOTE: Pure decision helper (no UI) so it is unit-testable without Tk.
    """
    meta = model.metadata
    if model.keep_metadata and meta is not None and fmt in _EXIF_WRITE_FORMATS:
        # AIDEV-NOTE: bind through a typed local — Exif.tobytes() is Any (PIL untyped),
        # and returning Any from a -> bytes | None function trips mypy warn_return_any.
        data: bytes = metadata.build_save_exif(meta).tobytes()
        return data
    return None
```

Add the `ImageModel` type import for the annotation under the existing `TYPE_CHECKING` block (currently imports `PxvApp`):

```python
if TYPE_CHECKING:
    from pxv.app import PxvApp
    from pxv.image_model import ImageModel
```

- [ ] **Step 5: Wire it into `cmd_save_as`**

In `cmd_save_as`, the current block (around `commands.py:116-119`) is:

```python
    fmt, path = _resolve_save_format(path)
    save_kwargs: dict[str, object] = {}
    if fmt == "JPEG":
        save_kwargs["quality"] = 95
```

Append immediately after it:

```python
    exif_bytes = _exif_for_save(app.image_model, fmt)
    if exif_bytes is not None:
        save_kwargs["exif"] = exif_bytes
    elif app.image_model.keep_metadata and fmt not in _EXIF_WRITE_FORMATS:
        app.show_temp_title(f"pxv: metadata not saved for {fmt}")
```

- [ ] **Step 6: Add `cmd_info`**

Add to `src/pxv/commands.py` (place it just above `cmd_enhancement_dialog`, currently `commands.py:332`):

```python
def cmd_info(app: PxvApp) -> None:
    """Open or raise the image info / EXIF dialog."""
    from pxv.info_dialog import InfoDialog

    if app.info_dialog is not None:
        try:
            app.info_dialog.deiconify()
            app.info_dialog.lift()
            app.info_dialog.refresh()
            return
        except Exception:
            app.info_dialog = None

    if app.image_model.metadata is None:
        return
    app.info_dialog = InfoDialog(app)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_save_helpers.py -v`
Expected: all PASS.

(Note: `cmd_info` references `app.info_dialog` and `InfoDialog`, added in Tasks 8 and 9. It is not exercised by these tests; mypy is run after Task 8 adds the attribute.)

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format src/pxv/commands.py tests/test_save_helpers.py
uv run ruff check src/pxv/commands.py tests/test_save_helpers.py
git add src/pxv/commands.py tests/test_save_helpers.py
git commit -m "feat(commands): write sanitized EXIF when keep enabled; add cmd_info"
```

---

## Task 8: app.py wiring + context menu + help table

**Files:**
- Modify: `src/pxv/app.py` (TYPE_CHECKING; `__init__` line 84; `_bind_keys` line 151; `load_current` line 196)
- Modify: `src/pxv/context_menu.py` (after line 47)
- Modify: `src/pxv/dialogs.py` (`KEYBINDINGS`, after line 18)

- [ ] **Step 1: Add the InfoDialog type import in app.py**

In `src/pxv/app.py`, the existing `TYPE_CHECKING` block (lines 22-23) is:

```python
if TYPE_CHECKING:
    from pxv.enhancement_dialog import EnhancementDialog
```

Change it to:

```python
if TYPE_CHECKING:
    from pxv.enhancement_dialog import EnhancementDialog
    from pxv.info_dialog import InfoDialog
```

- [ ] **Step 2: Add the `info_dialog` attribute**

In `PxvApp.__init__`, after the `self.enhancement_dialog` line (currently `app.py:84`):

```python
        # Will be set if the info / EXIF dialog is open
        self.info_dialog: InfoDialog | None = None
```

- [ ] **Step 3: Bind the `i` key**

In `_bind_keys`, after the `<question>` help binding (currently the last line, `app.py:151`):

```python
        self.root.bind("<Key-i>", lambda _: commands.cmd_info(self))
```

- [ ] **Step 4: Refresh the info dialog on load**

In `load_current`, after the enhancement-dialog sync (currently `app.py:195-196`):

```python
        if self.info_dialog is not None:
            self.info_dialog.refresh()
```

- [ ] **Step 5: Add the context-menu entry**

In `src/pxv/context_menu.py`, after the Print separator (currently `context_menu.py:47`, the `self.menu.add_separator()` following the Grab/Print group) and before the Enhancements command:

```python
        self.menu.add_command(label="Info...", command=lambda: commands.cmd_info(app))
        self.menu.add_separator()
```

- [ ] **Step 6: Add the help-table entry**

In `src/pxv/dialogs.py`, in the `KEYBINDINGS` list after the `("e", "Open enhancements dialog")` entry (currently `dialogs.py:18`):

```python
    ("i", "Show image info / EXIF"),
```

- [ ] **Step 7: Run the full test suite (no regressions)**

Run: `uv run pytest -q`
Expected: all PASS.

> **Do not run `uv run mypy src/pxv/` yet.** `app.py` and `commands.cmd_info` now reference `pxv.info_dialog`, which is not created until Task 9, so mypy would report a missing module. mypy is validated at the end of Task 9, once both sides of the app ↔ info_dialog reference exist.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format src/pxv/app.py src/pxv/context_menu.py src/pxv/dialogs.py
uv run ruff check src/pxv/app.py src/pxv/context_menu.py src/pxv/dialogs.py
git add src/pxv/app.py src/pxv/context_menu.py src/pxv/dialogs.py
git commit -m "feat(app): bind 'i' to info dialog, add context-menu + help entries"
```

---

## Task 9: info_dialog.py — the InfoDialog widget

**Files:**
- Create: `src/pxv/info_dialog.py`

(No automated tests — Tkinter widgets need a display and are out of scope for the pure-logic suite, consistent with `enhancement_dialog.py`. Verified manually in Step 3.)

- [ ] **Step 1: Create the dialog**

Create `src/pxv/info_dialog.py`:

```python
"""Image info / EXIF dialog — a non-modal Toplevel that follows navigation.

AIDEV-NOTE: All decode/sanitize/redact logic lives in metadata.py (pure, tested).
This widget only renders sections, hosts the curated edit fields, and exposes the
keep/strip and GPS-redaction actions. Edits/wipes are written on Save As only.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

from pxv import metadata

if TYPE_CHECKING:
    from pxv.app import PxvApp


class InfoDialog(tk.Toplevel):
    """Non-modal info panel showing file facts, EXIF, edit fields, and wipe actions."""

    def __init__(self, app: PxvApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("pxv: Image Info")
        self.resizable(False, False)
        self.transient(app.root)

        self._keep_var = tk.BooleanVar(value=app.image_model.keep_metadata)
        self._edit_vars: dict[str, tk.StringVar] = {}
        self._tags_shown = False

        self._body = ttk.Frame(self, padding=10)
        self._body.pack(fill=tk.BOTH, expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _: self._on_close())

        self.refresh()

        # Position beside the parent window (matches EnhancementDialog).
        self.update_idletasks()
        px = app.root.winfo_x() + app.root.winfo_width() + 10
        py = app.root.winfo_y()
        self.geometry(f"+{px}+{py}")

    # --- rendering -------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the panel from the currently-loaded image's metadata."""
        for child in self._body.winfo_children():
            child.destroy()
        self._edit_vars.clear()
        self._tags_shown = False

        meta = self.app.image_model.metadata
        if meta is None:
            ttk.Label(self._body, text="No image loaded.").pack(anchor=tk.W)
            return

        self._keep_var.set(self.app.image_model.keep_metadata)
        self._build_sections(meta)
        self._build_editor(meta)
        self._build_alltags(meta)
        self._build_footer(meta)

    def _build_sections(self, meta: metadata.ImageMetadata) -> None:
        for section in metadata.build_sections(meta):
            frame = ttk.LabelFrame(self._body, text=section.title, padding=6)
            frame.pack(fill=tk.X, pady=(0, 6))
            for row, (label, value) in enumerate(section.rows):
                ttk.Label(frame, text=label, anchor=tk.E, width=12).grid(
                    row=row, column=0, sticky=tk.E, padx=(0, 6), pady=1
                )
                ttk.Label(frame, text=value).grid(row=row, column=1, sticky=tk.W, pady=1)
            if section.title == "Location":
                ttk.Button(frame, text="Remove GPS", command=self._on_remove_gps).grid(
                    row=0, column=2, padx=(8, 0)
                )

    def _build_editor(self, meta: metadata.ImageMetadata) -> None:
        frame = ttk.LabelFrame(
            self._body, text='Edit (written only if "keep" is checked)', padding=6
        )
        frame.pack(fill=tk.X, pady=(0, 6))
        for row, (key, label, _ifd, _tag) in enumerate(metadata.EDITABLE_FIELDS):
            var = tk.StringVar(value=metadata.get_editable(meta, key))
            var.trace_add("write", self._make_edit_callback(key, var))
            self._edit_vars[key] = var
            ttk.Label(frame, text=label, anchor=tk.E, width=12).grid(
                row=row, column=0, sticky=tk.E, padx=(0, 6), pady=1
            )
            ttk.Entry(frame, textvariable=var, width=32).grid(
                row=row, column=1, sticky=tk.W, pady=1
            )

    def _build_alltags(self, meta: metadata.ImageMetadata) -> None:
        rows = metadata.all_tags(meta)
        frame = ttk.Frame(self._body)
        frame.pack(fill=tk.X, pady=(0, 6))
        toggle = ttk.Button(frame, text=f"Show all tags ({len(rows)})")
        toggle.pack(anchor=tk.W)
        # AIDEV-NOTE: the tags list is parented to this section frame (not _body) so
        # the expansion appears in place, above the footer, instead of below it.
        self._tags_frame = ttk.Frame(frame)
        toggle.configure(command=lambda: self._toggle_tags(toggle, rows))

    def _toggle_tags(
        self, toggle: ttk.Button, rows: list[tuple[int, str, str]]
    ) -> None:
        if self._tags_shown:
            self._tags_frame.pack_forget()
            for child in self._tags_frame.winfo_children():
                child.destroy()
            toggle.configure(text=f"Show all tags ({len(rows)})")
            self._tags_shown = False
            return
        tree = ttk.Treeview(
            self._tags_frame, columns=("name", "value"), show="headings", height=8
        )
        tree.heading("name", text="Tag")
        tree.heading("value", text="Value")
        tree.column("name", width=160, anchor=tk.W)
        tree.column("value", width=260, anchor=tk.W)
        for tag_id, name, value in rows:
            tree.insert("", tk.END, values=(name, value))
        scroll = ttk.Scrollbar(self._tags_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tags_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        toggle.configure(text="Hide all tags")
        self._tags_shown = True

    def _build_footer(self, meta: metadata.ImageMetadata) -> None:
        frame = ttk.Frame(self._body)
        frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Checkbutton(
            frame,
            text="Keep metadata on save",
            variable=self._keep_var,
            command=self._on_keep_toggle,
        ).pack(side=tk.LEFT)
        ttk.Button(frame, text="Strip all", command=self._on_strip_all, width=10).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(frame, text="Close", command=self._on_close, width=8).pack(
            side=tk.RIGHT, padx=4
        )

    # --- actions ---------------------------------------------------------

    def _make_edit_callback(
        self, key: str, var: tk.StringVar
    ) -> Callable[..., None]:
        def _callback(*_args: object) -> None:
            meta = self.app.image_model.metadata
            if meta is not None:
                metadata.set_editable(meta, key, var.get())

        return _callback

    def _on_keep_toggle(self) -> None:
        self.app.image_model.keep_metadata = self._keep_var.get()

    def _on_strip_all(self) -> None:
        self._keep_var.set(False)
        self.app.image_model.keep_metadata = False

    def _on_remove_gps(self) -> None:
        meta = self.app.image_model.metadata
        if meta is not None:
            metadata.redact_gps(meta.exif)
            self.refresh()

    def _on_close(self) -> None:
        self.app.info_dialog = None
        self.destroy()
```

- [ ] **Step 2: Type-check and lint**

Run: `uv run ruff format src/pxv/info_dialog.py && uv run ruff check src/pxv/info_dialog.py && uv run mypy src/pxv/`
Expected: clean. This is the first point where the whole `src/pxv/` type-checks, because `app.py`/`commands.py` reference `pxv.info_dialog` (created here) and this module references `app.info_dialog` (added in Task 8) — the two tasks form one type-checking unit.

- [ ] **Step 3: Manual smoke test (requires a display)**

Run: `uv run pxv <path-to-a-photo-with-exif.jpg>`
Then:
1. Press `i` — the info panel opens beside the window showing File/Camera/Exposure/Location.
2. Toggle "Show all tags" — a scrollable tag list appears and hides.
3. Type into Description; check "Keep metadata on save"; `Ctrl+S` to a new `.jpg`; reopen it and press `i` — Description persists, orientation normal.
4. Re-save with keep unchecked — reopened file shows "No EXIF metadata" in the EXIF sections.
5. Click "Remove GPS" on a geotagged photo, keep enabled, save — Location is gone on reload.
6. Press Space to navigate — the panel follows to the next image.

Expected: all behaviors as described; no tracebacks in the terminal.

- [ ] **Step 4: Commit**

```bash
git add src/pxv/info_dialog.py
git commit -m "feat(info_dialog): non-modal EXIF info/edit/wipe panel"
```

---

## Task 10: Documentation and final verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Update the changelog**

Add an entry under the unreleased/top section of `CHANGELOG.md` (match the existing style):

```markdown
### Added
- Image info / EXIF panel (`i` or right-click → Info): view file facts and decoded
  camera, exposure, capture-date, and GPS metadata; edit Description / Artist /
  Copyright / Date; remove GPS; and opt in to "keep metadata on save". Saving still
  strips metadata by default.
```

- [ ] **Step 2: Update the README shortcut list**

`README.md` has a `## Keyboard Shortcuts` table (`| Key | Action |`). Immediately after the enhancements row (currently `README.md:62`):

```markdown
| `e` | Enhancement dialog |
```

add a new row:

```markdown
| `i` | Show image info / EXIF |
```

- [ ] **Step 3: Full verification — tests, lint, types**

Run each and confirm clean output:

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/pxv/
```

Expected: pytest all green; ruff check clean; ruff format reports nothing to reformat; mypy clean.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: document EXIF info/edit/wipe feature and 'i' shortcut"
```

---

## Definition of Done

- `uv run pytest -q` passes, including the new `tests/test_metadata.py`, the metadata
  capture/reset tests in `tests/test_image_model.py`, and the save round-trip tests in
  `tests/test_save_helpers.py`.
- `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, and
  `uv run mypy src/pxv/` are all clean.
- Pressing `i` (or right-click → Info) opens the panel; it follows navigation.
- Default Save As still strips metadata (unchanged); "Keep metadata on save" writes a
  sanitized EXIF (orientation normalized, stale dims/thumbnail dropped) for
  JPEG/TIFF/WebP/PNG; "Remove GPS" and "Strip all" behave as specified.
- No binary fixtures committed; no new runtime dependencies.
