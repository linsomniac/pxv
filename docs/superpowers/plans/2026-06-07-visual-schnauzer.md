# Visual Schnauzer (Thumbnail Browser) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add xv's signature "Visual Schnauzer" — a standalone, scrollable grid of cached thumbnails over the existing `FileList` that lets you see every image and jump the viewer to any of them.

**Architecture:** A new pure module `thumbnails.py` (PIL I/O + grid math, no Tk) plus a new `thumbnail_browser.py` hosting a non-modal `tk.Toplevel` (`BrowserWindow`, modeled on `info_dialog.InfoDialog`). Picking a tile delegates to `commands.cmd_show_index`, whose `load_current()` calls back into `BrowserWindow.sync_selection` so the grid highlight and the viewer track each other in both directions without recursion. Thumbnails decode incrementally on the main thread (Tk `PhotoImage` constraint) via a self-rescheduling `after()` loop, cached per resolved path on the app.

**Tech Stack:** Python 3, Tkinter (`tk.Toplevel`, `tk.Canvas` + `ttk.Scrollbar` scrollable-frame), Pillow (`Image.thumbnail`, `ImageOps.exif_transpose`, `ImageTk.PhotoImage`), `uv` for env/test, `ruff format`, `mypy --strict`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-06-07-visual-schnauzer-design.md`

---

## Test environment

Most tasks add **display-free** unit tests that run with the normal suite:

```bash
uv run pytest
```

Tasks 8–9 add **`DISPLAY`-gated** Tk tests (pattern from `tests/test_dialog_focus.py`). This sandbox has no `xvfb-run`, so start a virtual display once and export it for those runs:

```bash
Xvfb :99 >/dev/null 2>&1 &        # leave running for the session
DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py -v
```

Always finish a task with the project gates:

```bash
uv run ruff format <changed files>
uv run mypy src
uv run pytest                      # full display-free suite
```

---

## File Structure

**New files**

- `src/pxv/thumbnails.py` — pure thumbnail decode + grid math. Responsibilities: `fit_thumbnail`, `pad_to_square`, `load_thumbnail` (EXIF + transparency flatten, raises on bad files), `columns_for_width`, `ThumbnailCache`, and the `THUMBNAIL_SIZE` / `CELL_BG` knobs. No Tk import — unit-testable headlessly.
- `src/pxv/thumbnail_browser.py` — the `BrowserWindow(tk.Toplevel)` widget and its private `_Tile`. Responsibilities: scrollable grid layout, incremental loader, bidirectional selection sync, own key bindings, teardown/focus restore.
- `tests/test_thumbnails.py` — display-free tests for `thumbnails.py`.
- `tests/test_commands.py` — display-free tests for the new pure command logic (`cmd_show_index`).
- `tests/test_thumbnail_browser.py` — `DISPLAY`-gated tests for `BrowserWindow` + app wiring.

**Modified files**

- `src/pxv/file_list.py` — add a read-only `paths()` accessor (so the browser doesn't reach into `_paths`).
- `src/pxv/commands.py` — add `cmd_toggle_browser` and `cmd_show_index`; one new line in `cmd_open`.
- `src/pxv/app.py` — `self.browser` / `self.thumbnail_cache` attrs, `<Key-b>` binding, `load_current()` sync hook, imports.
- `src/pxv/context_menu.py` — a "Browse thumbnails…" menu entry.
- `src/pxv/dialogs.py` — one new row in `KEYBINDINGS`.
- `README.md` — one new row in the Keyboard Shortcuts table.

---

## Task 1: `thumbnails.py` — constants + `fit_thumbnail` + `pad_to_square`

**Files:**
- Create: `src/pxv/thumbnails.py`
- Test: `tests/test_thumbnails.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_thumbnails.py`:

```python
"""Display-free tests for the pure thumbnail module (no Tk)."""

from __future__ import annotations

from PIL import Image

from pxv.thumbnails import CELL_BG, fit_thumbnail, pad_to_square


def test_fit_thumbnail_landscape_keeps_aspect_within_bounds() -> None:
    out = fit_thumbnail(Image.new("RGB", (200, 100), (255, 0, 0)), 128)
    assert out.size == (128, 64)


def test_fit_thumbnail_portrait_keeps_aspect_within_bounds() -> None:
    out = fit_thumbnail(Image.new("RGB", (100, 200), (255, 0, 0)), 128)
    assert out.size == (64, 128)


def test_fit_thumbnail_does_not_upscale_small_image() -> None:
    out = fit_thumbnail(Image.new("RGB", (50, 50), (255, 0, 0)), 128)
    assert out.size == (50, 50)


def test_pad_to_square_centers_on_background_cell() -> None:
    fitted = fit_thumbnail(Image.new("RGB", (200, 100), (255, 0, 0)), 128)
    out = pad_to_square(fitted, 128, CELL_BG)
    assert out.size == (128, 128)
    assert out.getpixel((0, 0)) == CELL_BG          # corner is letterbox
    assert out.getpixel((64, 64)) == (255, 0, 0)    # center is the image
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pxv.thumbnails'`

- [ ] **Step 3: Create `src/pxv/thumbnails.py` with the constants and the two functions**

```python
"""Thumbnail decoding and grid-layout math for the Visual Schnauzer browser.

AIDEV-NOTE: Pure I/O + pixel math, NO Tk — unit-testable headlessly. The browser
widget (thumbnail_browser.py) wraps the returned PIL images in PhotoImage on the
main thread. Transparency flattening and EXIF orientation mirror image_model.load()
so a tile matches how the viewer renders the same file.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

THUMBNAIL_SIZE = 128  # default square cell size; the single tuning knob for v1
CELL_BG = (30, 30, 30)  # dark neutral for the cell, letterbox bars, and the
# transparency flatten; the single place to theme tiles later.


def fit_thumbnail(img: Image.Image, size: int) -> Image.Image:
    """Return a copy of img scaled to fit within size x size, aspect preserved.

    Image.thumbnail only shrinks, so a smaller-than-size image is returned at its
    native size (and letterboxed by pad_to_square).
    """
    out = img.copy()
    out.thumbnail((size, size), Image.Resampling.LANCZOS)
    return out


def pad_to_square(img: Image.Image, size: int, bg: tuple[int, int, int] = CELL_BG) -> Image.Image:
    """Center an already-fit RGB image on a size x size cell filled with bg.

    Every tile becomes uniform size x size regardless of the source aspect ratio.
    """
    cell = Image.new("RGB", (size, size), bg)
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    cell.paste(img, (x, y))
    return cell
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Format, type-check, commit**

```bash
uv run ruff format src/pxv/thumbnails.py tests/test_thumbnails.py
uv run mypy src
git add src/pxv/thumbnails.py tests/test_thumbnails.py
git commit -m "feat(browser): thumbnail fit + pad-to-square helpers"
```

---

## Task 2: `thumbnails.py` — `load_thumbnail` + transparency/EXIF flatten

**Files:**
- Modify: `src/pxv/thumbnails.py`
- Test: `tests/test_thumbnails.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_thumbnails.py`:

```python
from pathlib import Path

import pytest

from pxv.thumbnails import load_thumbnail


def test_load_thumbnail_flattens_transparency_onto_cell_bg(tmp_path: Path) -> None:
    p = tmp_path / "clear.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(p)  # fully transparent
    out = load_thumbnail(p, 128, CELL_BG)
    assert out.size == (128, 128)
    assert out.mode == "RGB"
    assert out.getpixel((64, 64)) == CELL_BG  # transparent pixels -> cell bg


def test_load_thumbnail_honors_exif_orientation(tmp_path: Path) -> None:
    # 100x50 landscape tagged orientation=6 becomes 50x100 portrait after transpose.
    # A portrait thumbnail has content at top-center (64, 5); a landscape would not.
    img = Image.new("RGB", (100, 50), (255, 0, 0))
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    p = tmp_path / "rot.jpg"
    img.save(p, exif=exif)

    out = load_thumbnail(p, 128, CELL_BG)
    assert out.size == (128, 128)
    r, g, b = out.getpixel((64, 5))
    assert r > 200 and g < 60 and b < 60  # content (red), proving portrait orientation
    assert out.getpixel((2, 64)) == CELL_BG  # left letterbox bar


def test_load_thumbnail_raises_on_non_image(tmp_path: Path) -> None:
    p = tmp_path / "notes.txt"
    p.write_text("this is not an image")
    with pytest.raises(Exception):
        load_thumbnail(p, 128, CELL_BG)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_thumbnails.py -k load_thumbnail -v`
Expected: FAIL — `ImportError: cannot import name 'load_thumbnail'`

- [ ] **Step 3: Implement `load_thumbnail` and `_flatten`**

Add to `src/pxv/thumbnails.py` (below `pad_to_square`):

```python
def _flatten(img: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """Composite any transparent image onto bg; convert opaque non-RGB to RGB.

    AIDEV-NOTE: Mirrors ImageModel._to_rgb_working but flattens onto the cell color
    (not white) so a tile matches the viewer's transparency rendering on the grid.
    """
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img if img.mode == "RGBA" else img.convert("RGBA")
        base = Image.new("RGB", img.size, bg)
        base.paste(rgba, mask=rgba.split()[3])
        return base
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def load_thumbnail(path: Path, size: int, bg: tuple[int, int, int] = CELL_BG) -> Image.Image:
    """Decode path into a size x size RGB thumbnail tile.

    Applies EXIF orientation and flattens transparency onto bg so the tile matches
    the viewer. Raises (OSError / PIL.UnidentifiedImageError) on an unreadable or
    non-image file — the caller maps that to a 'broken' tile.
    """
    raw = Image.open(path)
    raw.load()  # force full decode so the file handle is released
    img: Image.Image = ImageOps.exif_transpose(raw)
    img = _flatten(img, bg)
    return pad_to_square(fit_thumbnail(img, size), size, bg)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Format, type-check, commit**

```bash
uv run ruff format src/pxv/thumbnails.py tests/test_thumbnails.py
uv run mypy src
git add src/pxv/thumbnails.py tests/test_thumbnails.py
git commit -m "feat(browser): load_thumbnail with EXIF + transparency flatten"
```

---

## Task 3: `thumbnails.py` — `columns_for_width`

**Files:**
- Modify: `src/pxv/thumbnails.py`
- Test: `tests/test_thumbnails.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_thumbnails.py`:

```python
from pxv.thumbnails import columns_for_width


def test_columns_for_width_basic_counts() -> None:
    # cell=134, gap=10, pad=10 (the browser's geometry constants)
    assert columns_for_width(600, 134, 10, 10) == 4
    assert columns_for_width(1000, 134, 10, 10) == 6


def test_columns_for_width_never_below_one() -> None:
    assert columns_for_width(140, 134, 10, 10) == 1   # usable < one cell
    assert columns_for_width(0, 134, 10, 10) == 1
    assert columns_for_width(200, 134, 10, 10) == 1   # exactly one cell fits
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_thumbnails.py -k columns -v`
Expected: FAIL — `ImportError: cannot import name 'columns_for_width'`

- [ ] **Step 3: Implement `columns_for_width`**

Add to `src/pxv/thumbnails.py`:

```python
def columns_for_width(width: int, cell: int, gap: int, pad: int) -> int:
    """Number of cell-wide columns that fit in a viewport `width` px wide.

    `pad` is the grid's left+right inset; `gap` separates adjacent columns. Solves
    n*cell + (n-1)*gap <= usable for the largest n, and never returns less than 1 so
    a too-narrow window still shows a single column.
    """
    usable = width - 2 * pad
    if usable < cell:
        return 1
    return max(1, (usable + gap) // (cell + gap))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Format, type-check, commit**

```bash
uv run ruff format src/pxv/thumbnails.py tests/test_thumbnails.py
uv run mypy src
git add src/pxv/thumbnails.py tests/test_thumbnails.py
git commit -m "feat(browser): columns_for_width grid math"
```

---

## Task 4: `thumbnails.py` — `ThumbnailCache`

**Files:**
- Modify: `src/pxv/thumbnails.py`
- Test: `tests/test_thumbnails.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_thumbnails.py`:

```python
from pxv.thumbnails import ThumbnailCache


def test_thumbnail_cache_put_get_contains_clear(tmp_path: Path) -> None:
    cache = ThumbnailCache()
    p = tmp_path / "a.png"
    img = Image.new("RGB", (4, 4), (1, 2, 3))

    assert p not in cache
    assert cache.get(p) is None

    cache.put(p, img)
    assert p in cache
    assert cache.get(p) is img

    cache.clear()
    assert p not in cache
    assert cache.get(p) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_thumbnails.py -k cache -v`
Expected: FAIL — `ImportError: cannot import name 'ThumbnailCache'`

- [ ] **Step 3: Implement `ThumbnailCache`**

Add to `src/pxv/thumbnails.py`:

```python
class ThumbnailCache:
    """Maps a resolved Path to its decoded PIL thumbnail. Survives browser toggles.

    AIDEV-NOTE: Stores PIL images, NOT Tk PhotoImage — PhotoImage is main-thread and
    bound to a live interpreter, while these survive window close/reopen. The browser
    rewraps cache hits in PhotoImage with no disk I/O. Keyed by resolved path so the
    same file reached via different relative paths hits the same entry.
    """

    def __init__(self) -> None:
        self._items: dict[Path, Image.Image] = {}

    def __contains__(self, path: Path) -> bool:
        return path.resolve() in self._items

    def get(self, path: Path) -> Image.Image | None:
        return self._items.get(path.resolve())

    def put(self, path: Path, img: Image.Image) -> None:
        self._items[path.resolve()] = img

    def clear(self) -> None:
        self._items.clear()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Format, type-check, commit**

```bash
uv run ruff format src/pxv/thumbnails.py tests/test_thumbnails.py
uv run mypy src
git add src/pxv/thumbnails.py tests/test_thumbnails.py
git commit -m "feat(browser): session ThumbnailCache (resolved-path keyed)"
```

---

## Task 5: `FileList.paths()` accessor

The browser iterates the file list to build tiles. Add a clean read-only accessor so it doesn't reach into `FileList._paths`.

**Files:**
- Modify: `src/pxv/file_list.py` (add method after `add`, around line 86)
- Test: `tests/test_file_list.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_file_list.py`:

```python
def test_paths_returns_independent_snapshot() -> None:
    from pathlib import Path

    from pxv.file_list import FileList

    fl = FileList([Path("a.png"), Path("b.png")])
    assert fl.paths() == [Path("a.png"), Path("b.png")]

    # Mutating the returned list must not affect the FileList.
    fl.paths().append(Path("c.png"))
    assert fl.count() == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_file_list.py -k snapshot -v`
Expected: FAIL — `AttributeError: 'FileList' object has no attribute 'paths'`

- [ ] **Step 3: Add the accessor**

In `src/pxv/file_list.py`, add this method to `FileList` (immediately after `add`):

```python
    def paths(self) -> list[Path]:
        """Return a snapshot copy of the ordered file paths.

        AIDEV-NOTE: A copy so callers (e.g. the thumbnail browser building tiles)
        can iterate without risk of mutating the live list.
        """
        return list(self._paths)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_file_list.py -v`
Expected: PASS (all existing + the new test)

- [ ] **Step 5: Format, type-check, commit**

```bash
uv run ruff format src/pxv/file_list.py tests/test_file_list.py
uv run mypy src
git add src/pxv/file_list.py tests/test_file_list.py
git commit -m "feat(browser): FileList.paths() read-only snapshot accessor"
```

---

## Task 6: `commands.cmd_show_index` + `cmd_toggle_browser`

`cmd_show_index` carries the only non-trivial new logic in `commands.py` (range guard + rollback), so it gets pure unit tests. `cmd_toggle_browser` is thin glue exercised later by the display-gated suite.

**Files:**
- Modify: `src/pxv/commands.py` (add after `cmd_prev_image`, ~line 384)
- Test: `tests/test_commands.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_commands.py`:

```python
"""Display-free tests for pure command logic (no Tk root)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pxv import commands
from pxv.file_list import FileList


def _stub_app(n: int, *, load_ok: bool) -> tuple[SimpleNamespace, list[int]]:
    fl = FileList([Path(f"img{i}.png") for i in range(n)])
    loaded: list[int] = []

    def load_current() -> bool:
        loaded.append(fl.index)
        return load_ok

    app = SimpleNamespace(file_list=fl, browser=None, load_current=load_current)
    return app, loaded


def test_cmd_show_index_jumps_and_loads() -> None:
    app, loaded = _stub_app(3, load_ok=True)
    commands.cmd_show_index(app, 2)
    assert app.file_list.index == 2
    assert loaded == [2]


def test_cmd_show_index_out_of_range_is_noop() -> None:
    app, loaded = _stub_app(2, load_ok=True)
    commands.cmd_show_index(app, 5)
    assert app.file_list.index == 0
    assert loaded == []


def test_cmd_show_index_rolls_back_on_failed_load() -> None:
    app, loaded = _stub_app(3, load_ok=False)
    app.file_list.index = 0
    commands.cmd_show_index(app, 2)
    assert app.file_list.index == 0  # rolled back to the still-displayed image
    assert loaded == [2]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_commands.py -v`
Expected: FAIL — `AttributeError: module 'pxv.commands' has no attribute 'cmd_show_index'`

- [ ] **Step 3: Add the two commands**

In `src/pxv/commands.py`, add immediately after `cmd_prev_image`:

```python
def cmd_toggle_browser(app: PxvApp) -> None:
    """Open the Visual Schnauzer thumbnail browser, or close it if already open."""
    if app.browser is not None:
        app.browser._on_close()
        return
    from pxv.thumbnail_browser import BrowserWindow

    app.browser = BrowserWindow(app)


def cmd_show_index(app: PxvApp, index: int) -> None:
    """Jump the viewer to file-list position `index` (no-op if out of range).

    AIDEV-NOTE: On a failed full-res load, roll the cursor back like cmd_next_image
    and re-sync the grid highlight to the still-displayed image. On success,
    load_current() itself re-syncs the highlight (the grid<-viewer direction), so
    this only re-syncs on the rollback path.
    """
    if not (0 <= index < app.file_list.count()):
        return
    prev_index = app.file_list.index
    app.file_list.index = index
    if not app.load_current():
        app.file_list.index = prev_index
        if app.browser is not None:
            app.browser.sync_selection(app.file_list.index)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_commands.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Format, type-check, commit**

```bash
uv run ruff format src/pxv/commands.py tests/test_commands.py
uv run mypy src
git add src/pxv/commands.py tests/test_commands.py
git commit -m "feat(browser): cmd_show_index (jump+rollback) and cmd_toggle_browser"
```

---

## Task 7: Wire the browser into `app.py`

Add the browser/cache state, the `b` key binding, the imports, and the `load_current()` sync hook. No standalone test here — it's verified by `mypy`, the full suite, and the display-gated tests in Task 8. (`cmd_toggle_browser` is forward-referenced from Task 6; it exists now.)

**Files:**
- Modify: `src/pxv/app.py`

- [ ] **Step 1: Add the runtime + type-checking imports**

In `src/pxv/app.py`, after the existing line `from pxv.slideshow import ...` (line 24), add:

```python
from pxv.thumbnails import ThumbnailCache
```

In the `if TYPE_CHECKING:` block (lines 26–28), add a line so it reads:

```python
if TYPE_CHECKING:
    from pxv.enhancement_dialog import EnhancementDialog
    from pxv.info_dialog import InfoDialog
    from pxv.thumbnail_browser import BrowserWindow
```

- [ ] **Step 2: Add the instance attributes**

In `PxvApp.__init__`, just after the `self.info_dialog: InfoDialog | None = None` line (~line 98), add:

```python
        # AIDEV-NOTE: The Visual Schnauzer thumbnail browser (a non-modal Toplevel).
        # Held here so commands/load_current can drive it; None when closed.
        self.browser: BrowserWindow | None = None
        # AIDEV-NOTE: Decoded PIL thumbnails keyed by resolved path. Lives on the app
        # (not the window) so it survives browser open/close and navigation.
        self.thumbnail_cache = ThumbnailCache()
```

- [ ] **Step 3: Bind the `b` key**

In `PxvApp._bind_keys`, add alongside the other bindings (e.g. after the `<Key-i>` line, ~line 178):

```python
        self.root.bind("<Key-b>", lambda _: commands.cmd_toggle_browser(self))
```

- [ ] **Step 4: Add the viewer→grid sync hook in `load_current`**

In `PxvApp.load_current`, change the success tail. The current code (lines 263–264) is:

```python
        self.refresh_display()
        return True
```

Replace it with:

```python
        self.refresh_display()
        # AIDEV-NOTE: Keep the open browser's highlight on the displayed image. This
        # covers every load path (Space/arrows, jumps, Open). sync_selection never
        # loads, so there is no recursion with _activate -> cmd_show_index.
        if self.browser is not None:
            self.browser.sync_selection(self.file_list.index)
        return True
```

- [ ] **Step 5: Type-check and run the full suite**

```bash
uv run ruff format src/pxv/app.py
uv run mypy src
uv run pytest
```
Expected: `mypy` clean; full suite PASS (the browser module doesn't exist yet, but nothing imports it at runtime until `cmd_toggle_browser` is called).

- [ ] **Step 6: Commit**

```bash
git add src/pxv/app.py
git commit -m "feat(browser): wire browser state, b key, and load_current sync hook"
```

---

## Task 8: `thumbnail_browser.py` — `BrowserWindow` + `DISPLAY`-gated tests

This is the central component. Write the test file first (TDD), watch it fail on the missing module, then implement the whole widget.

**Files:**
- Create: `src/pxv/thumbnail_browser.py`
- Test: `tests/test_thumbnail_browser.py` (new)

- [ ] **Step 1: Write the failing display-gated tests**

Create `tests/test_thumbnail_browser.py`:

```python
"""DISPLAY-gated tests for the Visual Schnauzer browser window.

AIDEV-NOTE: These build real Tk widgets, so they need an X display and are skipped
headlessly (pattern from test_dialog_focus.py). Run under Xvfb, e.g.
`Xvfb :99 & DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requires an X display (Tk browser test)"
)


def _make_app(tmp_path: Path, n: int) -> tuple[object, tk.Tk]:
    """Build a real PxvApp over n synthetic PNGs (no auto-load)."""
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    paths = []
    for i in range(n):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (40, 30), (40 * i % 256, 10, 10)).save(p)
        paths.append(p.resolve())
    root = tk.Tk()
    app = PxvApp(root, FileList(paths))
    root.update_idletasks()
    return app, root


def _drain_loader(browser: object) -> None:
    while browser._load_queue:  # type: ignore[attr-defined]
        browser._pump_loader()  # type: ignore[attr-defined]


def test_app_has_browser_state(tmp_path: Path) -> None:
    from pxv.thumbnails import ThumbnailCache

    app, root = _make_app(tmp_path, 1)
    try:
        assert app.browser is None
        assert isinstance(app.thumbnail_cache, ThumbnailCache)
    finally:
        root.destroy()


def test_open_builds_one_tile_per_file(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is not None
        assert len(app.browser._tiles) == 3
    finally:
        root.destroy()


def test_click_tile_loads_that_image(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        app.browser._activate(2)
        root.update()
        assert app.file_list.index == 2
        assert app.image_model.current_path == app.file_list.paths()[2]
    finally:
        root.destroy()


def test_arrow_navigation_moves_selection_and_index(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        app.browser._nav(1)  # Right
        root.update()
        assert app.file_list.index == 1
        assert app.browser._selected == 1
    finally:
        root.destroy()


def test_main_navigation_updates_grid_highlight(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        commands.cmd_next_image(app)  # index 0 -> 1 in the main window
        root.update()
        assert app.browser._selected == 1
    finally:
        root.destroy()


def test_loader_decodes_and_populates_cache(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 3)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        _drain_loader(app.browser)
        assert all(t.loaded for t in app.browser._tiles)
        assert app.file_list.paths()[0] in app.thumbnail_cache
    finally:
        root.destroy()


def test_broken_file_does_not_stall_loader(tmp_path: Path) -> None:
    from pxv import commands
    from pxv.file_list import FileList

    good = tmp_path / "good.png"
    Image.new("RGB", (20, 20), (0, 200, 0)).save(good)
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    root = tk.Tk()
    from pxv.app import PxvApp

    app = PxvApp(root, FileList([good.resolve(), bad.resolve()]))
    root.update_idletasks()
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        _drain_loader(app.browser)
        # Both tiles resolve to a terminal state; the bad one is marked, not hung.
        assert all(t.loaded for t in app.browser._tiles)
    finally:
        root.destroy()


def test_toggle_opens_then_closes(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is not None
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser is None
    finally:
        root.destroy()


def test_close_restores_canvas_focus(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        app.browser.focus_force()
        root.update()
        app.browser._on_close()
        root.update()
        assert app.browser is None
        assert root.focus_get() is app.canvas_view.canvas
    finally:
        root.destroy()


def test_empty_file_list_shows_no_images_state(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 0)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert app.browser._tiles == []
        assert app.browser._empty_label is not None
    finally:
        root.destroy()
```

- [ ] **Step 2: Run to verify failure**

Run: `DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py -v`
(Start `Xvfb :99 &` first if not already running.)
Expected: FAIL — `ModuleNotFoundError: No module named 'pxv.thumbnail_browser'` (the import inside `cmd_toggle_browser`).

- [ ] **Step 3: Implement `src/pxv/thumbnail_browser.py`**

```python
"""The Visual Schnauzer: a Toplevel grid of thumbnails over the file list.

AIDEV-NOTE: A standalone non-modal window (modeled on info_dialog.InfoDialog) showing
one tile per FileList entry. Picking a tile (click / arrow+Enter) loads that image
into the viewer via commands.cmd_show_index; conversely every viewer load calls
sync_selection() so the grid highlight tracks the viewer. The two directions never
recurse: _activate only loads, load_current only highlights.

Tk constraint: PhotoImage must be built on the main thread, so thumbnails decode in
small batches via a self-rescheduling after() loop (_pump_loader). Decoded PIL images
live in app.thumbnail_cache so reopening is cheap.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

from pxv import commands, thumbnails
from pxv.thumbnails import CELL_BG, THUMBNAIL_SIZE

if TYPE_CHECKING:
    from pxv.app import PxvApp

# Tile/grid geometry. BORDER doubles as the selection-highlight thickness, so the
# tile footprint (TILE_W) used for column math includes it on both sides.
BORDER = 3
GAP = 10
PAD = 10
TILE_W = THUMBNAIL_SIZE + 2 * BORDER  # 134
_NAME_MAXLEN = 18
_NAME_FG = "#aab8d0"
_SELECT_FG = "yellow"


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _truncate(name: str, maxlen: int) -> str:
    return name if len(name) <= maxlen else name[: maxlen - 1] + "…"


class _Tile:
    """One grid cell: its file-list index, source path, and its widgets."""

    __slots__ = ("index", "path", "frame", "image_label", "name_label", "photo", "loaded")

    def __init__(
        self,
        index: int,
        path: Path,
        frame: tk.Frame,
        image_label: tk.Label,
        name_label: tk.Label,
    ) -> None:
        self.index = index
        self.path = path
        self.frame = frame
        self.image_label = image_label
        self.name_label = name_label
        self.photo: ImageTk.PhotoImage | None = None
        self.loaded = False


class BrowserWindow(tk.Toplevel):
    """Scrollable thumbnail grid that mirrors and drives the file-list cursor."""

    def __init__(self, app: PxvApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("pxv: Browse")
        self.transient(app.root)

        self._cell_hex = _hex(CELL_BG)
        self.configure(bg=self._cell_hex)

        self._tiles: list[_Tile] = []
        self._columns: int = 1
        self._selected: int | None = None
        self._load_queue: list[int] = []
        self._loader_after_id: str | None = None
        self._configure_after_id: str | None = None
        self._empty_label: tk.Label | None = None

        # Shared placeholder shown until a tile's real thumbnail decodes, so every
        # tile has its final footprint immediately and the grid never jumps.
        self._placeholder = ImageTk.PhotoImage(
            Image.new("RGB", (THUMBNAIL_SIZE, THUMBNAIL_SIZE), CELL_BG)
        )

        self._build_scaffold()
        self.rebuild()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_keys()

        self.geometry(self._initial_geometry())
        self.focus_force()

    # --- construction ----------------------------------------------------

    def _build_scaffold(self) -> None:
        """Build the canvas + scrollbar + inner frame that holds the tile grid."""
        self._canvas = tk.Canvas(self, bg=self._cell_hex, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self._canvas, bg=self._cell_hex)
        self._inner_id = self._canvas.create_window((0, 0), window=self._inner, anchor=tk.NW)
        self._inner.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    def _initial_geometry(self) -> str:
        """A 4-column default size, positioned just right of the main window."""
        width = 2 * PAD + 4 * TILE_W + 3 * GAP
        height = 640
        self.update_idletasks()
        px = self.app.root.winfo_x() + self.app.root.winfo_width() + 10
        py = self.app.root.winfo_y()
        return f"{width}x{height}+{px}+{py}"

    def _bind_keys(self) -> None:
        # Root bindings don't reach a separate Toplevel, so the grid owns its keys.
        self.bind("<Left>", lambda _e: self._nav(-1))
        self.bind("<Right>", lambda _e: self._nav(1))
        self.bind("<Up>", lambda _e: self._nav(-self._columns))
        self.bind("<Down>", lambda _e: self._nav(self._columns))
        self.bind("<Return>", lambda _e: self._activate_selected())
        self.bind("<Escape>", lambda _e: self._on_close())
        self.bind("<Key-b>", lambda _e: self._on_close())
        self.bind("<Key-q>", lambda _e: self._on_close())
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", self._on_wheel)
        self.bind("<Button-5>", self._on_wheel)

    # --- (re)building the grid -------------------------------------------

    def rebuild(self) -> None:
        """Tear down and rebuild every tile from the current file list.

        Used on first open and after cmd_open adds a file. The ThumbnailCache keeps
        the re-decode cheap.
        """
        self._cancel_loader()
        for tile in self._tiles:
            tile.frame.destroy()
        self._tiles.clear()
        self._load_queue.clear()
        self._selected = None
        if self._empty_label is not None:
            self._empty_label.destroy()
            self._empty_label = None

        paths = self.app.file_list.paths()
        if not paths:
            self._empty_label = tk.Label(
                self._inner, text="No images", bg=self._cell_hex, fg=_NAME_FG, padx=40, pady=40
            )
            self._empty_label.grid(row=0, column=0)
            return

        for i, path in enumerate(paths):
            self._tiles.append(self._build_tile(i, path))
            self._load_queue.append(i)

        self._columns = 0  # force the first _reflow to lay tiles out
        self._reflow()
        self.sync_selection(self.app.file_list.index)
        self._kick_loader()

    def _build_tile(self, index: int, path: Path) -> _Tile:
        frame = tk.Frame(
            self._inner,
            bg=self._cell_hex,
            highlightthickness=BORDER,
            highlightbackground=self._cell_hex,
            highlightcolor=self._cell_hex,
        )
        image_label = tk.Label(frame, image=self._placeholder, bg=self._cell_hex, bd=0)
        image_label.pack()
        name_label = tk.Label(
            frame,
            text=_truncate(path.name, _NAME_MAXLEN),
            bg=self._cell_hex,
            fg=_NAME_FG,
            font=("TkDefaultFont", 8),
        )
        name_label.pack()
        for widget in (frame, image_label, name_label):
            widget.bind("<Button-1>", lambda _e, i=index: self._activate(i))
            widget.bind("<Double-Button-1>", lambda _e, i=index: self._activate(i))
        return _Tile(index, path, frame, image_label, name_label)

    # --- layout / reflow -------------------------------------------------

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # Keep the inner frame as wide as the canvas (so centering works), and
        # debounce a column recompute that only re-grids when the count changes.
        self._canvas.itemconfigure(self._inner_id, width=event.width)
        if self._configure_after_id is not None:
            self.after_cancel(self._configure_after_id)
        self._configure_after_id = self.after(80, self._reflow)

    def _reflow(self) -> None:
        self._configure_after_id = None
        if not self.winfo_exists() or not self._tiles:
            return
        width = self._canvas.winfo_width()
        columns = thumbnails.columns_for_width(width, TILE_W, GAP, PAD)
        if columns == self._columns:
            return
        self._columns = columns
        self._regrid()

    def _regrid(self) -> None:
        for tile in self._tiles:
            row, col = divmod(tile.index, self._columns)
            tile.frame.grid(row=row, column=col, padx=GAP // 2, pady=GAP // 2)
        if self._selected is not None:
            self._scroll_into_view(self._selected)

    # --- selection / activation ------------------------------------------

    def sync_selection(self, index: int) -> None:
        """Highlight `index` and scroll it into view. Never loads (viewer -> grid)."""
        if not self._tiles or not (0 <= index < len(self._tiles)):
            return
        if self._selected is not None and 0 <= self._selected < len(self._tiles):
            self._highlight(self._selected, on=False)
        self._selected = index
        self._highlight(index, on=True)
        self._scroll_into_view(index)

    def _highlight(self, index: int, *, on: bool) -> None:
        tile = self._tiles[index]
        color = _SELECT_FG if on else self._cell_hex
        tile.frame.configure(highlightbackground=color, highlightcolor=color)
        tile.name_label.configure(fg=_SELECT_FG if on else _NAME_FG)

    def _nav(self, delta: int) -> None:
        if not self._tiles:
            return
        current = self._selected if self._selected is not None else 0
        target = max(0, min(len(self._tiles) - 1, current + delta))
        self._activate(target)

    def _activate_selected(self) -> None:
        if self._selected is not None:
            self._activate(self._selected)

    def _activate(self, index: int) -> None:
        """Pick a tile: delegate to the viewer. load_current() calls sync_selection.

        focus_force keeps keyboard focus on the grid after a click so the arrow keys
        keep working; the load path never steals focus back.
        """
        self.focus_force()
        commands.cmd_show_index(self.app, index)

    def _scroll_into_view(self, index: int) -> None:
        self._canvas.update_idletasks()
        region = self._inner.winfo_height()
        if region <= 1:
            return
        tile = self._tiles[index]
        fy = tile.frame.winfo_y()
        fh = tile.frame.winfo_height()
        top = self._canvas.canvasy(0)
        view_h = self._canvas.winfo_height()
        if fy < top:
            self._canvas.yview_moveto(fy / region)
        elif fy + fh > top + view_h:
            self._canvas.yview_moveto(max(0.0, (fy + fh - view_h) / region))

    # --- incremental thumbnail loading -----------------------------------

    def _kick_loader(self) -> None:
        if self._load_queue and self._loader_after_id is None:
            self._loader_after_id = self.after(1, self._pump_loader)

    def _pump_loader(self) -> None:
        self._loader_after_id = None
        if not self.winfo_exists():
            return
        batch = 3
        while self._load_queue and batch > 0:
            self._load_tile(self._load_queue.pop(0))
            batch -= 1
        if self._load_queue:
            self._loader_after_id = self.after(1, self._pump_loader)

    def _load_tile(self, index: int) -> None:
        tile = self._tiles[index]
        cached = self.app.thumbnail_cache.get(tile.path)
        if cached is None:
            try:
                cached = thumbnails.load_thumbnail(tile.path, THUMBNAIL_SIZE)
            except Exception:
                self._mark_broken(tile)
                return
            self.app.thumbnail_cache.put(tile.path, cached)
        photo = ImageTk.PhotoImage(cached)
        tile.photo = photo  # keep a ref or Tk garbage-collects the image
        tile.image_label.configure(image=photo, text="")
        tile.loaded = True

    def _mark_broken(self, tile: _Tile) -> None:
        tile.image_label.configure(
            image=self._placeholder, text="broken", compound=tk.CENTER, fg="#cc6666"
        )
        tile.loaded = True

    def _cancel_loader(self) -> None:
        if self._loader_after_id is not None:
            self.after_cancel(self._loader_after_id)
            self._loader_after_id = None

    # --- scrolling / teardown --------------------------------------------

    def _on_wheel(self, event: tk.Event) -> str | None:
        num = getattr(event, "num", 0)
        if num == 4:
            delta = -1
        elif num == 5:
            delta = 1
        elif getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1
        else:
            return None
        self._canvas.yview_scroll(delta, "units")
        return "break"

    def _on_close(self) -> None:
        # AIDEV-NOTE: Cancel the pending loader/reflow timers, null the app ref, then
        # destroy and reclaim focus AFTER destroy() (see PxvApp.restore_main_focus —
        # destroying a Toplevel that holds input focus clears it).
        self._cancel_loader()
        if self._configure_after_id is not None:
            self.after_cancel(self._configure_after_id)
            self._configure_after_id = None
        self.app.browser = None
        self.destroy()
        self.app.restore_main_focus()
```

- [ ] **Step 4: Run the display-gated tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py -v`
Expected: PASS (10 tests). If `test_close_restores_canvas_focus` is flaky under a bare WM, re-run once — focus reclaim is the same mechanism the existing `test_dialog_focus.py` relies on.

- [ ] **Step 5: Type-check and run the full display-free suite**

```bash
uv run ruff format src/pxv/thumbnail_browser.py tests/test_thumbnail_browser.py
uv run mypy src
uv run pytest
```
Expected: `mypy` clean; full suite PASS (the new file is display-gated and skipped headlessly).

- [ ] **Step 6: Commit**

```bash
git add src/pxv/thumbnail_browser.py tests/test_thumbnail_browser.py
git commit -m "feat(browser): BrowserWindow thumbnail grid with incremental loader"
```

---

## Task 9: `cmd_open` rebuild hook + test

When the browser is open and the user opens a new file, the grid must gain a tile for it.

**Files:**
- Modify: `src/pxv/commands.py` (`cmd_open`, ~lines 97–99)
- Test: `tests/test_thumbnail_browser.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_thumbnail_browser.py`:

```python
def test_rebuild_picks_up_a_newly_added_file(tmp_path: Path) -> None:
    from pxv import commands

    app, root = _make_app(tmp_path, 2)
    try:
        commands.cmd_toggle_browser(app)
        root.update()
        assert len(app.browser._tiles) == 2

        new_path = tmp_path / "added.png"
        Image.new("RGB", (20, 20), (0, 0, 200)).save(new_path)
        app.file_list.add(new_path.resolve())
        app.browser.rebuild()
        root.update()
        assert len(app.browser._tiles) == 3
    finally:
        root.destroy()
```

(This exercises the same `rebuild()` that `cmd_open` will call, without invoking the blocking file dialog.)

- [ ] **Step 2: Run to verify it passes for `rebuild` but confirm `cmd_open` lacks the hook**

Run: `DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py -k rebuild -v`
Expected: PASS (the `rebuild()` method already works). The gap is that `cmd_open` doesn't call it yet — fix that next so a real Open updates the grid.

- [ ] **Step 3: Add the hook to `cmd_open`**

In `src/pxv/commands.py`, the current `cmd_open` tail (lines 97–99) is:

```python
    p = Path(path)
    app.file_list.add(p)
    app.load_current()
```

Replace it with:

```python
    p = Path(path)
    app.file_list.add(p)
    app.load_current()
    # AIDEV-NOTE: A newly opened file must appear in the Visual Schnauzer if it's open.
    if app.browser is not None:
        app.browser.rebuild()
```

- [ ] **Step 4: Type-check and run the suites**

```bash
uv run ruff format src/pxv/commands.py tests/test_thumbnail_browser.py
uv run mypy src
uv run pytest
DISPLAY=:99 uv run pytest tests/test_thumbnail_browser.py -v
```
Expected: `mypy` clean; both suites PASS (11 display-gated tests).

- [ ] **Step 5: Commit**

```bash
git add src/pxv/commands.py tests/test_thumbnail_browser.py
git commit -m "feat(browser): rebuild grid when cmd_open adds a file"
```

---

## Task 10: Discoverability — context menu, help dialog, README

Expose the feature in the right-click menu, the help dialog (`?`), and the README shortcuts table.

**Files:**
- Modify: `src/pxv/context_menu.py` (~line 53)
- Modify: `src/pxv/dialogs.py` (`KEYBINDINGS`, ~lines 39–40)
- Modify: `README.md` (Keyboard Shortcuts table, ~line 55)
- Test: `tests/test_thumbnail_browser.py` (one display-free assertion in `tests/test_commands.py` is simpler — see Step 1)

- [ ] **Step 1: Add a failing test for the help-table entry**

Append to `tests/test_commands.py` (display-free — `KEYBINDINGS` is a plain list):

```python
def test_keybindings_table_lists_browse() -> None:
    from pxv.dialogs import KEYBINDINGS

    keys = [k for k, _desc in KEYBINDINGS]
    assert "b" in keys
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_commands.py -k browse -v`
Expected: FAIL — `assert 'b' in [...]`

- [ ] **Step 3: Add the `KEYBINDINGS` row**

In `src/pxv/dialogs.py`, in the `KEYBINDINGS` list, add this entry just after the `("Backspace / Left", "Previous image")` line:

```python
    ("b", "Browse thumbnails (Visual Schnauzer)"),
```

- [ ] **Step 4: Add the context-menu entry**

In `src/pxv/context_menu.py`, after the `Info...` command (line 53), add:

```python
        self.menu.add_command(
            label="Browse thumbnails...", command=lambda: commands.cmd_toggle_browser(app)
        )
```

- [ ] **Step 5: Add the README row**

In `README.md`, in the Keyboard Shortcuts table, add this row just after the `` | `Backspace` / `Left` | Previous image | `` line:

```markdown
| `b` | Browse thumbnails (Visual Schnauzer) |
```

- [ ] **Step 6: Run tests, type-check, format**

```bash
uv run ruff format src/pxv/context_menu.py src/pxv/dialogs.py tests/test_commands.py
uv run mypy src
uv run pytest
```
Expected: `mypy` clean; full suite PASS (including `test_keybindings_table_lists_browse`).

- [ ] **Step 7: Commit**

```bash
git add src/pxv/context_menu.py src/pxv/dialogs.py README.md tests/test_commands.py
git commit -m "feat(browser): expose Visual Schnauzer in menu, help, and README"
```

---

## Task 11: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete display-free suite**

Run: `uv run pytest`
Expected: PASS — all prior tests plus the new `test_thumbnails.py`, `test_commands.py`, and `FileList.paths` test.

- [ ] **Step 2: Run the display-gated suite under Xvfb**

```bash
DISPLAY=:99 uv run pytest tests/test_dialog_focus.py tests/test_thumbnail_browser.py -v
```
Expected: PASS — the new browser tests and the existing focus tests (regression check that focus restoration still holds with the new Toplevel in play).

- [ ] **Step 3: Full type-check and format check**

```bash
uv run mypy src
uv run ruff format --check src
```
Expected: `mypy` clean; `ruff format --check` reports no files would be reformatted.

- [ ] **Step 4: Manual smoke test (optional but recommended)**

```bash
DISPLAY=:99 uv run pxv /path/to/a/folder/of/images
```
Then press `b` to open the browser; click and arrow-key through tiles (viewer follows); press Space in the main window (highlight follows); resize the browser (columns reflow); press `b` or `Esc` to close (main window keys still respond).

---

## Self-Review notes (author)

- **Spec coverage:** separate Toplevel grid (Task 8), navigate-only/live pick=load (Tasks 6, 8), medium 128px tiles + filename (Tasks 1, 8), fixed `THUMBNAIL_SIZE` knob (Task 1), incremental main-thread loader + per-path cache (Tasks 4, 8), `b` toggle + menu + help (Tasks 7, 10), bidirectional sync without recursion (Tasks 6, 7, 8), edge cases — empty list (Task 8 empty test), broken file (Task 8 broken test), EXIF orientation + transparency (Task 2), file-added-via-Open (Task 9), failed-jump rollback (Task 6). Testing split pure vs `DISPLAY`-gated (throughout). All covered.
- **Deviation from spec:** the spec said "FileList is unchanged"; this plan adds a read-only `FileList.paths()` (Task 5) rather than have the browser read the private `_paths`. This changes no navigation behavior and improves the boundary — a justified, minimal addition.
- **Type/name consistency:** `sync_selection`, `_activate`, `rebuild`, `_pump_loader`, `_on_close`, `cmd_show_index`, `cmd_toggle_browser`, `thumbnail_cache`, `browser`, `THUMBNAIL_SIZE`, `CELL_BG`, `columns_for_width(width, cell, gap, pad)`, `load_thumbnail(path, size, bg)` are used identically across `app.py`, `commands.py`, `thumbnail_browser.py`, and the tests.
- **No placeholders:** every code and test step contains complete, runnable content.
