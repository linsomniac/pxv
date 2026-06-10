# Histogram Panel + Tabbed Enhancement Dialog (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live post-enhancement histogram panel to the Enhancements dialog and restructure it into a tabbed layout (Sliders tab now; Levels/Curves tabs arrive in later phases).

**Architecture:** A new `histogram_panel.py` module follows the `canvas_view.py` split: pure compute/render functions (headlessly testable) plus a thin `HistogramPanel` Tk widget. The dialog gains a persistent panel above a `ttk.Notebook`; `PxvApp.refresh_display()`/`_update_display()` feed the panel the same preview image they hand to the canvas, and `cmd_enhancement_dialog` triggers one refresh on open to seed it.

**Tech Stack:** Python 3.10+, Pillow (only dependency), tkinter/ttk, pytest, uv, ruff, mypy (strict).

**Spec:** `docs/superpowers/specs/2026-06-10-histogram-levels-curves-design.md`

**Branch:** `histograms` (already checked out).

---

## Environment notes for the executor

- Run pure tests with `uv run pytest <file> -v`.
- DISPLAY-gated tests need X. There is **no `xvfb-run`** on this machine; instead:
  ```bash
  Xvfb :99 &            # once, leave it running
  DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v
  ```
- After writing Python, run `uv run ruff format <files>` and `uv run mypy src/pxv`.
- Do not remove existing `AIDEV-NOTE` comments.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/histogram_panel.py` | create | Pure histogram compute/render + `HistogramPanel` widget |
| `src/pxv/enhancement_dialog.py` | modify | Persistent panel + `ttk.Notebook`; new `update_histogram()` |
| `src/pxv/app.py` | modify | Feed the dialog from both display-refresh paths |
| `src/pxv/commands.py` | modify | Seed the histogram when the dialog opens |
| `tests/test_histogram_panel.py` | create | Pure compute/render tests + display-free refresh-hook test |
| `tests/test_enhancement_dialog_ui.py` | create | DISPLAY-gated widget/dialog/command tests |

---

### Task 1: Pure histogram math (`compute_histograms`, `clipping_percentages`)

**Files:**
- Create: `src/pxv/histogram_panel.py`
- Create: `tests/test_histogram_panel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_histogram_panel.py`:

```python
"""Tests for histogram computation, rendering, and app feed (display-free).

AIDEV-NOTE: The compute/render functions are pure (no Tk) by design, mirroring
the canvas_view.py geometry split, so this whole file runs headlessly. The
HistogramPanel widget itself is exercised in test_enhancement_dialog_ui.py
under a real display.
"""

from __future__ import annotations

from PIL import Image

from pxv.histogram_panel import (
    HIST_SIZE,
    clipping_percentages,
    compute_histograms,
)


def test_compute_histograms_solid_red() -> None:
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    lum, rgb = compute_histograms(img)
    assert len(lum) == 256 and len(rgb) == 768
    assert rgb[255] == 100  # R: every pixel at 255
    assert rgb[256 + 0] == 100  # G: every pixel at 0
    assert rgb[512 + 0] == 100  # B: every pixel at 0
    assert sum(lum) == 100
    # Pure red luminance lands at ~76 (ITU-R 601 weights).
    assert lum.index(max(lum)) in (75, 76, 77)


def test_compute_histograms_converts_non_rgb() -> None:
    img = Image.new("L", (4, 4), 128)
    lum, rgb = compute_histograms(img)
    assert lum[128] == 16
    assert rgb[128] == 16 and rgb[256 + 128] == 16 and rgb[512 + 128] == 16


def test_clipping_percentages_counts_worst_channel() -> None:
    img = Image.new("RGB", (2, 2), (128, 128, 128))
    img.putpixel((0, 0), (0, 0, 0))
    img.putpixel((1, 1), (255, 255, 255))
    _lum, rgb = compute_histograms(img)
    lo, hi = clipping_percentages(rgb)
    assert lo == 25.0
    assert hi == 25.0


def test_clipping_percentages_empty_histogram() -> None:
    assert clipping_percentages([0] * 768) == (0.0, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_histogram_panel.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'pxv.histogram_panel')

- [ ] **Step 3: Write the implementation**

Create `src/pxv/histogram_panel.py`:

```python
"""Histogram computation, rendering, and the enhancement dialog's histogram panel.

AIDEV-NOTE: Split like canvas_view.py — compute_histograms/render_histogram/
clipping_percentages are pure (no Tk) so they're unit-testable headlessly; the
HistogramPanel widget is a thin Tk shell that caches the last histograms so
channel/log toggles re-render without needing a new image.
"""

from __future__ import annotations

import math

from PIL import Image

HIST_SIZE = (256, 100)

# (key, label, overlay color) for the channel toggles, in display order.
CHANNELS: list[tuple[str, str, tuple[int, int, int]]] = [
    ("lum", "Lum", (200, 200, 200)),
    ("r", "R", (235, 80, 80)),
    ("g", "G", (90, 200, 90)),
    ("b", "B", (95, 140, 235)),
]


def compute_histograms(img: Image.Image) -> tuple[list[int], list[int]]:
    """Return (luminance, rgb) histograms: 256 and 768 entries."""
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    return rgb.convert("L").histogram(), rgb.histogram()


def clipping_percentages(rgb_hist: list[int]) -> tuple[float, float]:
    """(% of pixels clipped at 0, % clipped at 255), per the worst single channel.

    AIDEV-NOTE: True "any channel clipped" needs per-pixel data; the worst
    channel's bin count is a close, cheap proxy computable from the histogram.
    """
    total = sum(rgb_hist[:256])
    if total == 0:
        return (0.0, 0.0)
    lo = max(rgb_hist[0], rgb_hist[256], rgb_hist[512])
    hi = max(rgb_hist[255], rgb_hist[511], rgb_hist[767])
    return (100.0 * lo / total, 100.0 * hi / total)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_histogram_panel.py -v`
Expected: 4 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/histogram_panel.py tests/test_histogram_panel.py
uv run mypy src/pxv
git add src/pxv/histogram_panel.py tests/test_histogram_panel.py
git commit -m "feat(enhance): pure histogram compute and clipping helpers

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `render_histogram`

**Files:**
- Modify: `src/pxv/histogram_panel.py` (append function)
- Modify: `tests/test_histogram_panel.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_histogram_panel.py` (and add `render_histogram` to the import):

```python
def test_render_histogram_size_and_mode() -> None:
    img = Image.new("RGB", (8, 8), (10, 200, 60))
    lum, rgb = compute_histograms(img)
    out = render_histogram(lum, rgb, {"lum", "r", "g", "b"}, log_scale=False)
    assert out.size == HIST_SIZE
    assert out.mode == "RGB"


def test_render_histogram_channels_differ() -> None:
    img = Image.new("RGB", (8, 8), (255, 0, 0))
    lum, rgb = compute_histograms(img)
    r_only = render_histogram(lum, rgb, {"r"}, log_scale=False)
    b_only = render_histogram(lum, rgb, {"b"}, log_scale=False)
    assert list(r_only.getdata()) != list(b_only.getdata())


def test_render_histogram_log_scale_runs() -> None:
    img = Image.new("RGB", (8, 8), (128, 128, 128))
    lum, rgb = compute_histograms(img)
    out = render_histogram(lum, rgb, {"lum"}, log_scale=True)
    assert out.size == HIST_SIZE


def test_render_histogram_all_zero_bins() -> None:
    # No division-by-zero: renders the bare background.
    out = render_histogram([0] * 256, [0] * 768, {"lum", "r"}, log_scale=True)
    assert out.size == HIST_SIZE


def test_render_histogram_no_channels_selected() -> None:
    out = render_histogram([1] * 256, [1] * 768, set(), log_scale=False)
    assert out.size == HIST_SIZE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_histogram_panel.py -v`
Expected: new tests FAIL (ImportError: cannot import name 'render_histogram')

- [ ] **Step 3: Write the implementation**

Append to `src/pxv/histogram_panel.py` (add `ImageDraw` to the PIL import):

```python
def render_histogram(
    lum: list[int],
    rgb: list[int],
    channels: set[str],
    log_scale: bool,
    size: tuple[int, int] = HIST_SIZE,
) -> Image.Image:
    """Render the enabled channel overlays into an RGB image.

    Each enabled channel is a translucent filled polygon alpha-composited over
    a dark background. Heights are normalized to the tallest bin across all
    enabled channels (log1p-scaled first when log_scale), so relative channel
    heights stay comparable.
    """
    w, h = size
    base = Image.new("RGBA", size, (24, 24, 24, 255))

    series: list[tuple[tuple[int, int, int], list[int]]] = []
    for key, _label, color in CHANNELS:
        if key not in channels:
            continue
        if key == "lum":
            bins = lum
        else:
            offset = {"r": 0, "g": 256, "b": 512}[key]
            bins = rgb[offset : offset + 256]
        series.append((color, bins))

    def scaled(v: int) -> float:
        return math.log1p(v) if log_scale else float(v)

    peak = max((scaled(v) for _color, bins in series for v in bins), default=0.0)
    if peak > 0.0:
        for color, bins in series:
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            points: list[tuple[float, float]] = [(0.0, float(h))]
            for i, v in enumerate(bins):
                x = i * (w - 1) / 255
                y = (h - 1) - (h - 2) * scaled(v) / peak
                points.append((x, y))
            points.append((float(w - 1), float(h)))
            draw.polygon(points, fill=(*color, 110))
            base = Image.alpha_composite(base, layer)
    return base.convert("RGB")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_histogram_panel.py -v`
Expected: 9 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/histogram_panel.py tests/test_histogram_panel.py
uv run mypy src/pxv
git add src/pxv/histogram_panel.py tests/test_histogram_panel.py
git commit -m "feat(enhance): histogram overlay rendering

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `HistogramPanel` widget

**Files:**
- Modify: `src/pxv/histogram_panel.py` (append widget)
- Create: `tests/test_enhancement_dialog_ui.py` (DISPLAY-gated)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_enhancement_dialog_ui.py`:

```python
"""DISPLAY-gated tests for the histogram panel and tabbed enhancement dialog.

AIDEV-NOTE: Real Tk widgets — skipped headlessly like test_dialog_focus.py.
Run under Xvfb: `Xvfb :99 &` then `DISPLAY=:99 uv run pytest <this file>`.
"""

from __future__ import annotations

import os
import types

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requires an X display (Tk widget test)"
)


def test_histogram_panel_update_and_blank() -> None:
    from pxv.histogram_panel import HistogramPanel

    root = tk.Tk()
    try:
        panel = HistogramPanel(root)
        panel.update_from_image(Image.new("RGB", (16, 16), (200, 30, 30)))
        assert panel._photo is not None
        assert panel._clip_label.cget("text") != ""
        panel.update_from_image(None)
        assert panel._photo is None
        assert panel._clip_label.cget("text") == ""
    finally:
        root.destroy()


def test_histogram_panel_toggle_rerenders_without_new_image() -> None:
    from pxv.histogram_panel import HistogramPanel

    root = tk.Tk()
    try:
        panel = HistogramPanel(root)
        panel.update_from_image(Image.new("RGB", (16, 16), (255, 0, 0)))
        first = panel._photo
        panel._channel_vars["r"].set(True)
        panel._redraw()
        assert panel._photo is not None
        assert panel._photo is not first
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` (start `Xvfb :99 &` first if not running)
Expected: FAIL (ImportError: cannot import name 'HistogramPanel')

- [ ] **Step 3: Write the implementation**

Append to `src/pxv/histogram_panel.py`. The file's full import block becomes (`ImageTk` joins the PIL import; tkinter is stdlib, so it sits with `math`):

```python
import math
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk
```

Then the widget:

```python
class HistogramPanel(ttk.Frame):
    """Histogram display with channel toggles, log scale, and clipping readouts."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self._lum: list[int] | None = None
        self._rgb: list[int] | None = None
        # AIDEV-NOTE: Tkinter garbage-collects PhotoImage if no Python reference
        # exists (same pattern as CanvasView._photo_image) — keep one here.
        self._photo: ImageTk.PhotoImage | None = None

        w, h = HIST_SIZE
        self._canvas = tk.Canvas(self, width=w, height=h, bg="#181818", highlightthickness=0)
        self._canvas.pack(fill=tk.X)

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, pady=(2, 0))
        self._channel_vars: dict[str, tk.BooleanVar] = {}
        for key, label, _color in CHANNELS:
            var = tk.BooleanVar(value=(key == "lum"))
            ttk.Checkbutton(controls, text=label, variable=var, command=self._redraw).pack(
                side=tk.LEFT
            )
            self._channel_vars[key] = var
        self._log_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Log", variable=self._log_var, command=self._redraw).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self._clip_label = ttk.Label(controls, text="")
        self._clip_label.pack(side=tk.RIGHT)

    def update_from_image(self, img: Image.Image | None) -> None:
        """Recompute histograms from a new preview image (None blanks the panel)."""
        if img is None:
            self._lum = None
            self._rgb = None
        else:
            self._lum, self._rgb = compute_histograms(img)
        self._redraw()

    def _redraw(self) -> None:
        """Re-render from the cached histograms (channel/log toggles reuse them)."""
        self._canvas.delete("all")
        if self._lum is None or self._rgb is None:
            self._photo = None
            self._clip_label.config(text="")
            return
        enabled = {key for key, var in self._channel_vars.items() if var.get()}
        rendered = render_histogram(self._lum, self._rgb, enabled, self._log_var.get())
        self._photo = ImageTk.PhotoImage(rendered)
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        lo, hi = clipping_percentages(self._rgb)
        self._clip_label.config(text=f"◂{lo:.1f}%  {hi:.1f}%▸")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py tests/test_histogram_panel.py -v`
Expected: all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/histogram_panel.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/histogram_panel.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): HistogramPanel widget with channel/log toggles

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Tabbed dialog restructure + `update_histogram`

**Files:**
- Modify: `src/pxv/enhancement_dialog.py` (`_build_ui`, new method, imports)
- Modify: `tests/test_enhancement_dialog_ui.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancement_dialog_ui.py`. The `_make_app` double follows
`test_dialog_focus.py`, plus a `refresh_display` recorder (the dialog's debounce
path calls it):

```python
def _make_app() -> tuple[types.SimpleNamespace, "tk.Tk"]:
    """Lightweight PxvApp double around real Tk widgets (see test_dialog_focus)."""
    from pxv.app import PxvApp
    from pxv.canvas_view import CanvasView
    from pxv.enhancements import EnhancementParams

    root = tk.Tk()
    canvas_view = CanvasView(root)
    root.update_idletasks()
    app = types.SimpleNamespace(
        root=root,
        canvas_view=canvas_view,
        info_dialog=None,
        enhancement_dialog=None,
        enhancement_params=EnhancementParams(),
        image_model=types.SimpleNamespace(keep_metadata=False, metadata=None),
        refresh_calls=[],
    )
    app.refresh_display = lambda: app.refresh_calls.append(True)
    app.restore_main_focus = types.MethodType(PxvApp.restore_main_focus, app)
    return app, root


def test_dialog_has_histogram_panel_and_sliders_tab() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        tabs = [dlg._notebook.tab(tab_id, "text") for tab_id in dlg._notebook.tabs()]
        assert tabs == ["Sliders"]
        # Sliders still build and sync inside the tab.
        app.enhancement_params.brightness = 1.5
        dlg.sync_sliders_from_params()
        assert dlg._slider_vars["brightness"].get() == 1.5
        dlg._on_close()
    finally:
        root.destroy()


def test_dialog_update_histogram_delegates_to_panel() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg.update_histogram(Image.new("RGB", (8, 8), (0, 255, 0)))
        assert dlg.histogram_panel._photo is not None
        dlg.update_histogram(None)
        assert dlg.histogram_panel._photo is None
        dlg._on_close()
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v`
Expected: new tests FAIL (AttributeError: '_notebook' / 'update_histogram')

- [ ] **Step 3: Modify the dialog**

In `src/pxv/enhancement_dialog.py`:

Add imports — `HistogramPanel` at runtime, `Image` for the type annotation:

```python
from pxv.enhancements import COLOR_SLIDER_SPECS, SLIDER_SPECS
from pxv.histogram_panel import HistogramPanel

if TYPE_CHECKING:
    from PIL import Image

    from pxv.app import PxvApp
```

Replace `_build_ui` with:

```python
    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Histogram stays visible above whichever tab is active.
        self.histogram_panel = HistogramPanel(main_frame)
        self.histogram_panel.pack(fill=tk.X, pady=(0, 6))

        # AIDEV-NOTE: Tabbed layout per the 2026-06-10 histogram/levels/curves
        # design — Sliders today; Levels and Curves tabs arrive in later phases.
        self._notebook = ttk.Notebook(main_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        sliders_tab = ttk.Frame(self._notebook, padding=6)
        self._notebook.add(sliders_tab, text="Sliders")

        core_frame = ttk.LabelFrame(sliders_tab, text="Core Adjustments", padding=6)
        core_frame.pack(fill=tk.X, pady=(0, 6))
        self._add_sliders(core_frame, SLIDER_SPECS)

        color_frame = ttk.LabelFrame(sliders_tab, text="Color", padding=6)
        color_frame.pack(fill=tk.X)
        self._add_sliders(color_frame, COLOR_SLIDER_SPECS)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="Apply", command=self._on_apply, width=8).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Reset", command=self._on_reset, width=8).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Close", command=self._on_close, width=8).pack(
            side=tk.LEFT, padx=4
        )
```

Add the public method after `sync_sliders_from_params`:

```python
    def update_histogram(self, img: Image.Image | None) -> None:
        """Feed the latest preview image to the histogram panel (None blanks it)."""
        self.histogram_panel.update_from_image(img)
```

- [ ] **Step 4: Run tests — new and existing — to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py tests/test_dialog_focus.py -v`
Expected: all PASS (the focus-restore tests guard the `_on_close` path we didn't touch)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/enhancement_dialog.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/enhancement_dialog.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): tabbed dialog layout with persistent histogram panel

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Feed the histogram from the app's refresh paths

**Files:**
- Modify: `src/pxv/app.py` (`refresh_display`, `_update_display`)
- Modify: `src/pxv/commands.py` (`cmd_enhancement_dialog`)
- Modify: `tests/test_histogram_panel.py` (display-free hook tests)
- Modify: `tests/test_enhancement_dialog_ui.py` (gated open-seed test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_histogram_panel.py` (add `import types` to the top-level
imports; `EnhancementParams` is imported inside the helper):

```python
def _refresh_double(
    display_img: Image.Image | None,
) -> tuple[types.SimpleNamespace, list[Image.Image | None]]:
    """PxvApp double for refresh_display: stubs everything the method touches."""
    from pxv.enhancements import EnhancementParams

    received: list[Image.Image | None] = []
    app = types.SimpleNamespace(
        image_model=types.SimpleNamespace(
            get_display_image=lambda zoom, params, bg_color: display_img,
            current_path=None,
        ),
        canvas_view=types.SimpleNamespace(zoom=1.0, display=lambda im: None),
        enhancement_params=EnhancementParams(),
        fullscreen=True,  # skips _resize_window_to_image
        enhancement_dialog=types.SimpleNamespace(update_histogram=received.append),
        _bg_color=lambda: (0, 0, 0),
        _update_title=lambda: None,
    )
    return app, received


def test_refresh_display_feeds_open_dialog() -> None:
    from pxv.app import PxvApp

    img = Image.new("RGB", (4, 4), (1, 2, 3))
    app, received = _refresh_double(img)
    PxvApp.refresh_display(app)
    assert received == [img]


def test_refresh_display_feeds_none_when_no_image() -> None:
    from pxv.app import PxvApp

    app, received = _refresh_double(None)
    PxvApp.refresh_display(app)
    assert received == [None]


def test_update_display_feeds_open_dialog() -> None:
    from pxv.app import PxvApp

    img = Image.new("RGB", (4, 4), (9, 9, 9))
    app, received = _refresh_double(img)
    PxvApp._update_display(app)
    assert received == [img]


def test_refresh_display_with_no_dialog_does_not_crash() -> None:
    from pxv.app import PxvApp

    app, _received = _refresh_double(None)
    app.enhancement_dialog = None
    PxvApp.refresh_display(app)  # must not raise
```

Append to `tests/test_enhancement_dialog_ui.py`:

```python
def test_cmd_enhancement_dialog_seeds_histogram_via_refresh() -> None:
    from pxv import commands

    app, root = _make_app()
    try:
        commands.cmd_enhancement_dialog(app)
        assert app.enhancement_dialog is not None
        assert app.refresh_calls == [True]
        app.enhancement_dialog._on_close()
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_histogram_panel.py -v` — the three feed tests FAIL (`received == []`).
Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` — seed test FAILS (`refresh_calls == []`).

- [ ] **Step 3: Modify `app.py` and `commands.py`**

In `src/pxv/app.py`, `refresh_display` — add the two-line feed before
`self._update_title()` (after the existing `if display_img is not None:` block):

```python
    def refresh_display(self) -> None:
        """Re-render the image with current zoom and enhancement params."""
        display_img = self.image_model.get_display_image(
            zoom=self.canvas_view.zoom,
            params=self.enhancement_params,
            bg_color=self._bg_color(),
        )
        if display_img is not None:
            # AIDEV-NOTE: Resize window BEFORE display() so the canvas has correct
            # dimensions when centering the image. Skipped in fullscreen, where the
            # window must stay screen-sized and the image is centered on black.
            if not self.fullscreen:
                self._resize_window_to_image(display_img.width, display_img.height)
            self.canvas_view.display(display_img)
        # AIDEV-NOTE: The histogram tracks the post-enhancement preview — exactly
        # what the user sees, including the background composite for transparent
        # images (accepted in the 2026-06-10 design). None blanks the panel.
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.update_histogram(display_img)
        self._update_title()
```

In `_update_display`, the same feed before `self._update_title()`:

```python
    def _update_display(self) -> None:
        """Refresh display without changing zoom or window size (for resize events)."""
        display_img = self.image_model.get_display_image(
            zoom=self.canvas_view.zoom,
            params=self.enhancement_params,
            bg_color=self._bg_color(),
        )
        if display_img is not None:
            self.canvas_view.display(display_img)
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.update_histogram(display_img)
        self._update_title()
```

In `src/pxv/commands.py`, `cmd_enhancement_dialog` — seed after construction:

```python
def cmd_enhancement_dialog(app: PxvApp) -> None:
    """Open or raise the enhancement dialog."""
    from pxv.enhancement_dialog import EnhancementDialog

    if app.enhancement_dialog is not None:
        try:
            app.enhancement_dialog.deiconify()
            app.enhancement_dialog.lift()
            return
        except Exception:
            app.enhancement_dialog = None

    app.enhancement_dialog = EnhancementDialog(app)
    # Seed the histogram panel: the refresh paths feed it on every render, but
    # a freshly opened dialog needs one render to pull the current image in.
    app.refresh_display()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_histogram_panel.py -v`
Expected: all PASS
Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v`
Expected: all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/app.py src/pxv/commands.py tests/test_histogram_panel.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/app.py src/pxv/commands.py tests/test_histogram_panel.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): feed live preview histogram from refresh paths

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite under a display**

```bash
Xvfb :99 2>/dev/null &
DISPLAY=:99 uv run pytest
```

Expected: all tests pass (186 pre-existing + 18 new), no skips besides any
already-skipped platform-specific tests.

- [ ] **Step 2: Lint + typecheck the tree**

```bash
uv run ruff format --check src tests
uv run mypy src/pxv
```

Expected: no reformats needed, mypy clean.

- [ ] **Step 3: Manual smoke (if a display is available)**

```bash
DISPLAY=:99 uv run pxv <some test image> &
```

Open the Enhancements dialog (the keybinding/menu is unchanged); verify the
histogram appears, moves with the Brightness slider, and the Sliders tab
behaves exactly as before. Kill the app afterward.

---

## Out of scope for this plan (later phases)

- Levels tab, `tone.py`, auto-levels (Phase 2 plan)
- Curves tab, spline math, `curve_editor.py`, Equalize/Invert (Phase 3 plan)
- Eyedroppers/pick mode, Compare button (Phase 4 plan)
- README/help/CHANGELOG updates land with the final phase, when the feature is
  user-visible as a whole
