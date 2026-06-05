# pxv Test Suite + CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure-logic `pytest` suite that locks in pxv's display-independent behavior, plus a CI workflow that runs ruff, mypy, and pytest on every push and PR.

**Architecture:** Example-based pytest with synthetic Pillow-generated fixtures (no committed binaries). One test module per source module. One behavior-preserving refactor extracts the crop-coordinate math from `CanvasView` into a pure, testable helper. A GitHub Actions `ci.yml` runs lint/type-check once and tests across Python 3.10–3.13.

**Tech Stack:** Python 3.10+, pytest, Pillow, ruff, mypy, uv, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-06-05-test-suite-and-ci-design.md`

**Branch:** `add-test-suite-and-ci` (already created; spec already committed).

> **Note on TDD here:** Most of this suite is *characterization* testing of existing, already-correct code, so those tests are expected to **PASS** the first time they run (they lock in current behavior; a failure means either a bad test or a real regression). Only Task 5 (the `selection_to_image_box` refactor) is classic red→green TDD: its test fails first because the function does not exist yet.

---

## Task 1: pytest tooling + shared fixtures + file_list tests

**Files:**
- Modify: `pyproject.toml` (add `pytest` dev dependency + pytest config)
- Create: `tests/conftest.py`
- Create: `tests/test_file_list.py`

- [ ] **Step 1: Add pytest to the dev dependency group**

Run:
```bash
uv add --dev pytest
```
Expected: `pyproject.toml` gains `pytest` under `[dependency-groups].dev` and `uv.lock` is updated.

- [ ] **Step 2: Add pytest configuration to `pyproject.toml`**

Append this section to `pyproject.toml` (e.g. after the `[tool.mypy]` blocks):
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create `tests/conftest.py` with shared synthetic-image fixtures**

```python
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
```

- [ ] **Step 4: Create `tests/test_file_list.py`**

```python
"""Tests for the file list and CLI path expansion (file_list.py)."""

from __future__ import annotations

from pathlib import Path

from pxv.file_list import FileList, expand_paths


def test_navigation_wraps() -> None:
    fl = FileList([Path("a"), Path("b"), Path("c")])
    assert fl.current() == Path("a")
    assert fl.next() == Path("b")
    assert fl.next() == Path("c")
    assert fl.next() == Path("a")  # wrap forward
    assert fl.prev() == Path("c")  # wrap backward


def test_position_str_and_count() -> None:
    fl = FileList([Path("a"), Path("b")])
    assert fl.position_str() == "1/2"
    fl.next()
    assert fl.position_str() == "2/2"
    assert fl.count() == 2


def test_empty_list_is_safe() -> None:
    fl = FileList([])
    assert fl.current() is None
    assert fl.next() is None
    assert fl.prev() is None
    assert fl.position_str() == "0/0"
    assert fl.count() == 0


def test_index_setter_wraps() -> None:
    fl = FileList([Path("a"), Path("b"), Path("c")])
    fl.index = 5
    assert fl.index == 2
    fl.index = -1
    assert fl.index == 2


def test_add_deduplicates_by_resolved_path(tmp_path: Path) -> None:
    f1 = tmp_path / "a.png"
    f1.write_bytes(b"")
    f2 = tmp_path / "b.png"
    f2.write_bytes(b"")
    fl = FileList([])
    fl.add(f1)
    fl.add(f1)  # duplicate -> selects existing, no new entry
    assert fl.count() == 1
    fl.add(f2)
    assert fl.count() == 2
    assert fl.index == 1  # newly added becomes current


def test_expand_paths_directory_sorted_and_filtered(tmp_path: Path) -> None:
    (tmp_path / "b.png").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")  # non-image, must be filtered out
    result = expand_paths([str(tmp_path)])
    assert [p.name for p in result] == ["a.jpg", "b.png"]


def test_expand_paths_dedups_first_wins(tmp_path: Path) -> None:
    f = tmp_path / "a.png"
    f.write_bytes(b"")
    result = expand_paths([str(f), str(f)])
    assert len(result) == 1


def test_expand_paths_reports_missing(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "nope.png"
    result = expand_paths([str(missing)])
    assert result == []
    assert "skipping nonexistent" in capsys.readouterr().err
```

- [ ] **Step 5: Run the tests (expected PASS — locks in current behavior)**

Run: `uv run pytest tests/test_file_list.py -v`
Expected: all tests PASS (8 passed).

- [ ] **Step 6: Lint & format-check the new files**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format tests/
```
Expected: ruff check clean; `ruff format` normalizes the new test files (re-run `ruff format --check src/ tests/` to confirm "All done").

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock tests/conftest.py tests/test_file_list.py
git commit -m "test: add pytest tooling, fixtures, and file_list tests"
```

---

## Task 2: save-helper tests

**Files:**
- Create: `tests/test_save_helpers.py`

Targets the pure save helpers in `commands.py`: `_resolve_save_format` and `_rgba_to_gif`.

- [ ] **Step 1: Create `tests/test_save_helpers.py`**

```python
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
```

- [ ] **Step 2: Run the tests (expected PASS)**

Run: `uv run pytest tests/test_save_helpers.py -v`
Expected: all tests PASS (12 passed).

- [ ] **Step 3: Lint & format**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format tests/
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_save_helpers.py
git commit -m "test: add save-format helper tests"
```

---

## Task 3: enhancements tests

**Files:**
- Create: `tests/test_enhancements.py`

- [ ] **Step 1: Create `tests/test_enhancements.py`**

```python
"""Tests for the enhancement params and pipeline (enhancements.py)."""

from __future__ import annotations

from PIL import Image

from pxv.enhancements import (
    EnhancementParams,
    _apply_hue_rotation,
    _build_lut,
    apply_enhancements,
)


def test_is_identity_default() -> None:
    assert EnhancementParams().is_identity() is True


def test_is_identity_false_when_changed() -> None:
    p = EnhancementParams()
    p.brightness = 1.5
    assert p.is_identity() is False


def test_reset_returns_to_identity() -> None:
    p = EnhancementParams()
    p.brightness = 2.0
    p.blur = 3.0
    p.hue_offset = 90
    p.reset()
    assert p.is_identity() is True


def test_build_lut_identity() -> None:
    lut = _build_lut(1.0, 1.0, 1.0, 1.0, 1.0)
    assert len(lut) == 768
    assert lut == list(range(256)) * 3


def test_build_lut_brightness_doubles_and_clamps() -> None:
    lut = _build_lut(2.0, 1.0, 1.0, 1.0, 1.0)
    assert lut[50] == 100
    assert lut[200] == 255  # clamped at 255


def test_build_lut_per_channel_balance() -> None:
    lut = _build_lut(1.0, 1.0, 0.5, 1.0, 1.0)
    assert lut[100] == 50  # red channel halved
    assert lut[256 + 100] == 100  # green channel unchanged


def test_build_lut_gamma_brightens_midtones() -> None:
    lut = _build_lut(1.0, 2.0, 1.0, 1.0, 1.0)
    assert lut[0] == 0
    assert lut[255] == 255
    assert lut[64] > 64  # gamma > 1 lifts midtones


def test_hue_rotation_zero_is_noop() -> None:
    img = Image.new("RGB", (2, 2), (255, 0, 0))
    assert _apply_hue_rotation(img, 0) is img


def test_hue_rotation_shifts_red_toward_cyan() -> None:
    img = Image.new("RGB", (2, 2), (255, 0, 0))
    out = _apply_hue_rotation(img, 180)
    r, g, b = out.getpixel((0, 0))
    assert r < g and r < b  # red is no longer the dominant channel


def test_apply_enhancements_identity_returns_equal_copy() -> None:
    img = Image.new("RGB", (4, 4), (90, 120, 150))
    out = apply_enhancements(img, EnhancementParams())
    assert out is not img
    assert list(out.getdata()) == list(img.getdata())


def test_apply_enhancements_brightness_raises_values() -> None:
    img = Image.new("RGB", (4, 4), (100, 100, 100))
    p = EnhancementParams()
    p.brightness = 1.5
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0))[0] > 100


def test_blur_applied_even_at_low_zoom() -> None:
    # Regression (1.0.1): blur must gate on the slider value, not the zoom-scaled
    # radius, so a nonzero blur still applies when zoom < 1.
    img = Image.new("RGB", (10, 10), (0, 0, 0))
    img.paste(Image.new("RGB", (5, 10), (255, 255, 255)), (5, 0))  # sharp vertical edge
    sharp = apply_enhancements(img, EnhancementParams(), zoom=0.5)
    p = EnhancementParams()
    p.blur = 2.0
    blurred = apply_enhancements(img, p, zoom=0.5)
    assert list(blurred.getdata()) != list(sharp.getdata())
```

- [ ] **Step 2: Run the tests (expected PASS)**

Run: `uv run pytest tests/test_enhancements.py -v`
Expected: all tests PASS (12 passed).

- [ ] **Step 3: Lint & format**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format tests/
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_enhancements.py
git commit -m "test: add enhancement pipeline tests"
```

---

## Task 4: image_model tests

**Files:**
- Create: `tests/test_image_model.py`

Uses the `bordered` fixture from `conftest.py`.

- [ ] **Step 1: Create `tests/test_image_model.py`**

```python
"""Tests for the three-tier image state model (image_model.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pxv.enhancements import EnhancementParams
from pxv.image_model import ImageModel

from conftest import BorderedFactory


# --- _has_transparency -------------------------------------------------------


@pytest.mark.parametrize("mode", ["RGBA", "LA", "PA"])
def test_has_transparency_alpha_modes(mode: str) -> None:
    assert ImageModel._has_transparency(Image.new(mode, (1, 1))) is True


def test_has_transparency_palette_with_info() -> None:
    img = Image.new("P", (1, 1))
    img.info["transparency"] = 0
    assert ImageModel._has_transparency(img) is True


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_has_transparency_opaque_modes(mode: str) -> None:
    assert ImageModel._has_transparency(Image.new(mode, (1, 1))) is False


def test_has_transparency_palette_without_info() -> None:
    assert ImageModel._has_transparency(Image.new("P", (1, 1))) is False


# --- _to_rgb_working (transparent pixels composite onto white) ----------------


def test_to_rgb_working_rgba_composites_onto_white() -> None:
    img = Image.new("RGBA", (2, 1))
    img.putpixel((0, 0), (255, 0, 0, 0))  # transparent over red
    img.putpixel((1, 0), (0, 255, 0, 255))  # opaque green
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)  # no red leak
    assert out.getpixel((1, 0)) == (0, 255, 0)


def test_to_rgb_working_la_composites_onto_white() -> None:
    img = Image.new("LA", (2, 1))
    img.putpixel((0, 0), (100, 0))  # transparent
    img.putpixel((1, 0), (100, 255))  # opaque
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)
    assert out.getpixel((1, 0)) == (100, 100, 100)


def test_to_rgb_working_palette_transparency_composites_onto_white() -> None:
    img = Image.new("P", (2, 1))
    img.putpalette([255, 0, 0, 0, 255, 0])  # index 0 red, index 1 green
    img.putpixel((0, 0), 0)
    img.putpixel((1, 0), 1)
    img.info["transparency"] = 0
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)  # red index was transparent -> white
    assert out.getpixel((1, 0)) == (0, 255, 0)


def test_to_rgb_working_opaque_rgb_returns_copy() -> None:
    img = Image.new("RGB", (2, 1), (1, 2, 3))
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (1, 2, 3)
    assert out is not img


# --- load --------------------------------------------------------------------


def test_load_rgba_sets_save_buffer(tmp_path: Path) -> None:
    p = tmp_path / "t.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(p)
    model = ImageModel()
    model.load(p)
    assert model.working_image is not None
    assert model.working_image.mode == "RGB"
    assert model._save_rgba is not None
    assert model._save_rgba.mode == "RGBA"
    assert model.current_path == p


def test_load_opaque_jpeg_has_no_save_buffer(tmp_path: Path) -> None:
    p = tmp_path / "t.jpg"
    Image.new("RGB", (4, 4), (10, 20, 30)).save(p)
    model = ImageModel()
    model.load(p)
    assert model._save_rgba is None
    assert model.working_image is not None
    assert model.working_image.mode == "RGB"


# --- crop / uncrop -----------------------------------------------------------


def test_crop_then_uncrop_restores_one_level() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    model.crop((2, 2, 8, 8))
    assert model.get_working_size() == (6, 6)
    assert model.uncrop() is True
    assert model.get_working_size() == (10, 10)
    assert model.uncrop() is False  # only one level of undo


def test_crop_applies_to_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    model._save_rgba = Image.new("RGBA", (10, 10), (10, 20, 30, 255))
    model.crop((1, 1, 6, 6))
    assert model.get_working_size() == (5, 5)
    assert model._save_rgba is not None
    assert model._save_rgba.size == (5, 5)
    model.uncrop()
    assert model._save_rgba is not None
    assert model._save_rgba.size == (10, 10)


# --- autocrop ----------------------------------------------------------------


def test_autocrop_rgb_trims_uniform_border(bordered: BorderedFactory) -> None:
    model = ImageModel()
    model.working_image = bordered((20, 20), (255, 255, 255), (255, 0, 0), (5, 5, 15, 15))
    assert model.autocrop() is True
    assert model.get_working_size() == (10, 10)


def test_autocrop_solid_image_returns_false() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (50, 60, 70))
    assert model.autocrop() is False
    assert model.get_working_size() == (10, 10)


def test_autocrop_alpha_trims_transparent_border() -> None:
    model = ImageModel()
    rgba = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    rgba.paste(Image.new("RGBA", (10, 10), (0, 255, 0, 255)), (5, 5))
    model._save_rgba = rgba
    model.working_image = ImageModel._to_rgb_working(rgba)
    assert model.autocrop() is True
    assert model.get_working_size() == (10, 10)
    assert model._save_rgba is not None
    assert model._save_rgba.size == (10, 10)


# --- rotate / flip / resize keep both buffers in lockstep --------------------


def test_geometry_ops_keep_buffers_in_lockstep() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 2), (10, 20, 30))
    model._save_rgba = Image.new("RGBA", (4, 2), (10, 20, 30, 255))
    model.rotate(90)
    assert model.working_image is not None and model._save_rgba is not None
    assert model.working_image.size == (2, 4)
    assert model._save_rgba.size == (2, 4)
    model.flip_horizontal()
    assert model.working_image.size == (2, 4)
    assert model._save_rgba.size == (2, 4)
    model.resize((8, 8))
    assert model.working_image.size == (8, 8)
    assert model._save_rgba.size == (8, 8)


# --- reset -------------------------------------------------------------------


def test_reset_restores_original_working() -> None:
    model = ImageModel()
    original = Image.new("RGB", (10, 10), (5, 6, 7))
    model.original_image = original
    model.working_image = original.crop((0, 0, 4, 4))
    model.reset()
    assert model.get_working_size() == (10, 10)
    assert model.working_image is not None
    assert model.working_image.getpixel((0, 0)) == (5, 6, 7)


# --- get_save_image (preserve_alpha avoids white fringing) -------------------


def test_get_save_image_preserve_alpha_no_white_fringe() -> None:
    model = ImageModel()
    rgba = Image.new("RGBA", (1, 1), (255, 0, 0, 128))
    model._save_rgba = rgba
    model.working_image = ImageModel._to_rgb_working(rgba)  # ~ (255, 127, 127)
    out = model.get_save_image(EnhancementParams(), preserve_alpha=True)
    assert out is not None
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0)) == (255, 0, 0, 128)  # true RGB preserved, not fringed


def test_get_save_image_opaque_returns_rgb() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (2, 2), (10, 20, 30))
    out = model.get_save_image(EnhancementParams())
    assert out is not None
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (10, 20, 30)


# --- get_display_image -------------------------------------------------------


def test_get_display_image_scales_by_zoom() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    out = model.get_display_image(zoom=0.5, params=EnhancementParams())
    assert out is not None
    assert out.size == (5, 5)


def test_get_display_image_dark_background_recomposites() -> None:
    model = ImageModel()
    rgba = Image.new("RGBA", (1, 1), (0, 0, 0, 0))  # fully transparent
    model._save_rgba = rgba
    model.working_image = ImageModel._to_rgb_working(rgba)  # white
    out = model.get_display_image(zoom=1.0, params=EnhancementParams(), bg_color=(0, 0, 0))
    assert out is not None
    assert out.getpixel((0, 0)) == (0, 0, 0)  # transparent shown on black background
```

- [ ] **Step 2: Run the tests (expected PASS)**

Run: `uv run pytest tests/test_image_model.py -v`
Expected: all tests PASS (~22 passed).

> If `from conftest import BorderedFactory` fails to import, it means pytest's
> rootdir/import mode isn't placing `tests/` on `sys.path`. Fix by confirming
> `testpaths = ["tests"]` is set (Task 1, Step 2) and that there is **no**
> `tests/__init__.py` (prepend import mode adds the test dir to `sys.path`).

- [ ] **Step 3: Lint & format**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format tests/
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_image_model.py
git commit -m "test: add image_model state/transform tests"
```

---

## Task 5: canvas-geometry refactor + tests (classic TDD)

**Files:**
- Modify: `src/pxv/canvas_view.py` (add `selection_to_image_box`; delegate from the method) — replaces the body of `get_selection_image_coords` at `canvas_view.py:130-170`
- Create: `tests/test_canvas_geometry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canvas_geometry.py`:
```python
"""Tests for the pure crop-coordinate math extracted from CanvasView."""

from __future__ import annotations

from pxv.canvas_view import selection_to_image_box


def test_box_accounts_for_centering_offset() -> None:
    # 100x100 image shown 1:1 inside a 200x200 canvas -> 50px border each side.
    box = selection_to_image_box(
        selection=(60, 60, 160, 160),
        working_size=(100, 100),
        display_size=(100, 100),
        canvas_size=(200, 200),
        zoom=1.0,
    )
    assert box == (10, 10, 100, 100)


def test_box_divides_by_zoom() -> None:
    box = selection_to_image_box(
        selection=(0, 0, 200, 200),
        working_size=(100, 100),
        display_size=(200, 200),
        canvas_size=(200, 200),
        zoom=2.0,
    )
    assert box == (0, 0, 100, 100)


def test_box_clamps_to_image_bounds() -> None:
    box = selection_to_image_box(
        selection=(-20, -20, 50, 50),
        working_size=(100, 100),
        display_size=(100, 100),
        canvas_size=(100, 100),
        zoom=1.0,
    )
    assert box == (0, 0, 50, 50)


def test_degenerate_selection_returns_none() -> None:
    box = selection_to_image_box(
        selection=(50, 50, 50, 60),
        working_size=(100, 100),
        display_size=(100, 100),
        canvas_size=(100, 100),
        zoom=1.0,
    )
    assert box is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canvas_geometry.py -v`
Expected: FAIL — `ImportError: cannot import name 'selection_to_image_box'`.

- [ ] **Step 3: Add the pure helper function**

In `src/pxv/canvas_view.py`, after the imports and before `class CanvasView`, add:
```python
def selection_to_image_box(
    selection: tuple[int, int, int, int],
    working_size: tuple[int, int],
    display_size: tuple[int, int],
    canvas_size: tuple[int, int],
    zoom: float,
) -> tuple[int, int, int, int] | None:
    """Convert a canvas-space selection rectangle to working-image pixel coords.

    AIDEV-NOTE: Pure geometry extracted from CanvasView.get_selection_image_coords
    so it can be unit-tested without a live Tk display. The image is centered in
    the canvas; we subtract that centering offset, divide by zoom, and clamp to the
    image bounds. Returns None for a degenerate (zero/negative-area) box.
    """
    sx1, sy1, sx2, sy2 = selection
    img_w, img_h = working_size
    disp_w, disp_h = display_size
    canvas_w, canvas_h = canvas_size

    area_w = max(canvas_w, disp_w)
    area_h = max(canvas_h, disp_h)
    img_x0 = (area_w - disp_w) / 2
    img_y0 = (area_h - disp_h) / 2

    ix1 = max(0, min(img_w, int((sx1 - img_x0) / zoom)))
    iy1 = max(0, min(img_h, int((sy1 - img_y0) / zoom)))
    ix2 = max(0, min(img_w, int((sx2 - img_x0) / zoom)))
    iy2 = max(0, min(img_h, int((sy2 - img_y0) / zoom)))

    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return (ix1, iy1, ix2, iy2)
```

- [ ] **Step 4: Replace the method body to delegate to the helper**

In `src/pxv/canvas_view.py`, replace the entire existing `get_selection_image_coords` method (currently `canvas_view.py:130-170`) with:
```python
    def get_selection_image_coords(
        self, working_size: tuple[int, int]
    ) -> tuple[int, int, int, int] | None:
        """Convert the canvas selection rectangle to working_image pixel coordinates.

        AIDEV-NOTE: Reads live widget sizes here and delegates the pure geometry to
        selection_to_image_box() (module level) so the math stays unit-testable.
        """
        if self._selection is None:
            return None
        return selection_to_image_box(
            self._selection,
            working_size,
            (self._display_width, self._display_height),
            (self.canvas.winfo_width(), self.canvas.winfo_height()),
            self.zoom,
        )
```

- [ ] **Step 5: Run the new tests (expected PASS)**

Run: `uv run pytest tests/test_canvas_geometry.py -v`
Expected: all tests PASS (4 passed).

- [ ] **Step 6: Verify the refactor changed no behavior — type-check, lint, full suite**

Run:
```bash
uv run mypy src/pxv/
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pytest
```
Expected: mypy clean, ruff clean, full suite PASS. (The arithmetic in the helper is identical to the original method, so runtime behavior is unchanged.)

- [ ] **Step 7: Commit**

```bash
git add src/pxv/canvas_view.py tests/test_canvas_geometry.py
git commit -m "refactor: extract testable selection_to_image_box; add tests"
```

---

## Task 6: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

# Least privilege: CI only needs to read the repo.
permissions:
  contents: read

jobs:
  lint:
    name: Lint & type-check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync

      - name: Ruff lint
        run: uv run ruff check src/ tests/

      - name: Ruff format check
        run: uv run ruff format --check src/ tests/

      - name: Mypy
        run: uv run mypy src/pxv/

  test:
    name: Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync

      - name: Run tests
        run: uv run pytest
```

- [ ] **Step 2: Sanity-check the commands the workflow runs (locally)**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/pxv/
uv run pytest
```
Expected: all four succeed. (GitHub validates the YAML itself when the workflow first runs; these are the exact commands it executes.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run ruff, mypy, and pytest on push and PR"
```

---

## Task 7: Final verification + push + PR

**Files:** none (verification and integration only).

- [ ] **Step 1: Run the full gate locally**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/pxv/
uv run pytest -v
```
Expected: all clean; full suite PASS (~58 tests).

- [ ] **Step 2: Confirm the working tree is clean and review the diff**

Run:
```bash
git status
git log --oneline main..HEAD
```
Expected: clean tree; commits for tasks 1–6 present on `add-test-suite-and-ci`.

- [ ] **Step 3: Push the branch and open a PR** (confirm with the user first)

AIDEV-NOTE: SSH push fails in this sandbox; push over HTTPS using the gh credential helper.
```bash
git -c credential.helper='!gh auth git-credential' push -u origin add-test-suite-and-ci
gh pr create --fill --base main --head add-test-suite-and-ci
```
Expected: branch pushed; PR opened; CI starts on the PR.

- [ ] **Step 4: Confirm CI is green on the PR**

Run: `gh pr checks --watch`
Expected: both the `lint` job and all `test` matrix jobs pass.

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- pytest tooling/layout → Task 1. Fixtures (synthetic, no binaries) → Task 1 `conftest.py`.
- image_model coverage → Task 4. enhancements → Task 3. file_list → Task 1. save helpers → Task 2. canvas geometry → Task 5.
- Behavior-preserving refactor → Task 5. CI workflow → Task 6. Definition of Done → Task 7.

**Note on the helper signature:** the spec sketched `selection_to_image_box(selection, display_size, canvas_size, zoom)`; the implementation adds `working_size` (needed for the bounds clamp). This is a deliberate, minor refinement of the sketch.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to" — every code step contains complete code and exact commands.

**Type/name consistency:** `selection_to_image_box` keyword names (`selection`, `working_size`, `display_size`, `canvas_size`, `zoom`) are identical in the tests (Task 5 Step 1) and the implementation (Task 5 Step 3). `BorderedFactory` is defined in `conftest.py` (Task 1) and imported in `tests/test_image_model.py` (Task 4). Helper/fixture names match across tasks.
