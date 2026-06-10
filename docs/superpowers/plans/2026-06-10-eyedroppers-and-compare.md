# Eyedroppers + Compare (Phase 4, final, of Histogram/Levels/Curves) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the feature: black/gray/white eyedroppers (pick a pixel on the main canvas to set levels), a hold-to-Compare before/after button, the levels+curves Apply/undo integration test, the LevelsTab/CurveEditor dedup, and the README/CHANGELOG updates.

**Architecture:** A pure `canvas_point_to_image_xy` joins `selection_to_image_box` in `canvas_view.py`; `CanvasView` gains a one-shot pick callback that consumes the next click instead of rubber-banding. `tone.py` gains `gray_balance_gammas` (per-channel gamma neutralizing a sampled cast). The dialog owns pick plumbing (`_request_pick`, sampling the working image — input side, same as the Levels strip); `LevelsTab` gets three eyedropper buttons via an injected `request_pick` callback, staying app-decoupled. Compare is an app-level flag read at refresh time (`_active_params()`), so in-flight debounces render correctly. Shared channel-row constants/builder move to a new tiny `tone_ui.py`.

**Spec deviation (documented):** the spec says "Escape or a second button press cancels" a pick. We implement second-press cancel and outside-the-image-click cancel, but NOT a root `<Escape>` binding: tkinter's `unbind(seq, funcid)` removes ALL bindings for the sequence (CPython bpo-31485), so a temporary Escape bind would clobber any future root Escape binding. AIDEV-NOTE this in the code.

**Spec:** `docs/superpowers/specs/2026-06-10-histogram-levels-curves-design.md` · **Branch:** `histograms` (Phase 3 through `c434e0b`).

---

## Environment notes for the executor

- Xvfb already on :99 for gated tests (`DISPLAY=:99 uv run pytest ...`); pure tests need no display.
- After writing Python: `uv run ruff format <files>`, `uv run mypy src/pxv` (strict).
- Never remove `AIDEV-NOTE` comments. Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- mypy-strict precedent: minimal annotation-only fixes (e.g. `math.pow`, `# type: ignore[no-untyped-call]` on untyped tkinter stubs) are sanctioned — report them.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/tone.py` | modify | `gray_balance_gammas` |
| `src/pxv/canvas_view.py` | modify | `canvas_point_to_image_xy` (pure) + one-shot pick mode |
| `src/pxv/tone_ui.py` | create | Shared `CHANNEL_KEYS`/`HIST_CHANNEL`/`build_channel_row` |
| `src/pxv/levels_tab.py` | modify | Eyedropper buttons + pick application; use tone_ui |
| `src/pxv/curve_editor.py` | modify | Use tone_ui |
| `src/pxv/enhancement_dialog.py` | modify | `_request_pick` plumbing; Compare button |
| `src/pxv/app.py` | modify | `_compare_active` + `_active_params()` |
| `README.md`, `CHANGELOG.md` | modify | Feature docs |
| tests | modify | `test_tone.py`, `test_canvas_geometry.py`, `test_histogram_panel.py`, `test_enhancement_dialog_ui.py` |

---

### Task 1: Pure math — `gray_balance_gammas` + `canvas_point_to_image_xy`

**Files:** Modify `src/pxv/tone.py`, `src/pxv/canvas_view.py`, `tests/test_tone.py`, `tests/test_canvas_geometry.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tone.py` (add `gray_balance_gammas` to the import):

```python
def test_gray_balance_neutral_sample_is_identity() -> None:
    assert gray_balance_gammas((128, 128, 128)) == (1.0, 1.0, 1.0)


def test_gray_balance_neutralizes_a_cast() -> None:
    sample = (200, 128, 100)
    gr, gg, gb = gray_balance_gammas(sample)
    assert gr < 1.0 < gb  # red too bright -> darken; blue too dark -> brighten
    # Applying the per-channel gammas maps each sampled channel near the mean.
    outs = [
        levels_lut(LevelsChannel(gamma=g))[v]
        for g, v in ((gr, 200), (gg, 128), (gb, 100))
    ]
    assert max(outs) - min(outs) <= 3


def test_gray_balance_extreme_channels_fall_back_to_identity() -> None:
    # Channels at 0 or 255 (or an extreme mean) can't be gamma-balanced.
    gr, _gg, gb = gray_balance_gammas((0, 128, 255))
    assert gr == 1.0 and gb == 1.0
    assert gray_balance_gammas((255, 255, 255)) == (1.0, 1.0, 1.0)
```

Append to `tests/test_canvas_geometry.py` (it already imports from `pxv.canvas_view`; extend the import with `canvas_point_to_image_xy`):

```python
def test_point_maps_through_centering_offset() -> None:
    # 100x100 image displayed 1:1 on a 300x300 canvas -> offset (100, 100).
    assert canvas_point_to_image_xy((150, 150), (100, 100), (100, 100), (300, 300), 1.0) == (
        50,
        50,
    )


def test_point_maps_through_zoom() -> None:
    # 100x100 image at 2x -> display 200x200 on a 200x200 canvas, no offset.
    assert canvas_point_to_image_xy((100, 100), (100, 100), (200, 200), (200, 200), 2.0) == (
        50,
        50,
    )


def test_point_outside_image_returns_none() -> None:
    assert canvas_point_to_image_xy((10, 10), (100, 100), (100, 100), (300, 300), 1.0) is None
    assert canvas_point_to_image_xy((299, 299), (100, 100), (100, 100), (300, 300), 1.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

`uv run pytest tests/test_tone.py tests/test_canvas_geometry.py -v` → ImportError ×2

- [ ] **Step 3: Implement**

Append to `src/pxv/tone.py`:

```python
def gray_balance_gammas(sample: tuple[int, int, int]) -> tuple[float, float, float]:
    """Per-channel gammas that map a sampled near-gray pixel to neutral.

    Target is the sample mean. From levels_lut, output (v/255)**(1/gamma)
    equals m/255 when gamma = log(v/255) / log(m/255). Channels at 0/255 (or
    an extreme mean) cannot be gamma-balanced and fall back to 1.0.
    """
    m = sum(sample) / 3.0
    if m <= 0.0 or m >= 255.0:
        return (1.0, 1.0, 1.0)
    gammas: list[float] = []
    for v in sample:
        if v <= 0 or v >= 255:
            gammas.append(1.0)
        else:
            g = math.log(v / 255.0) / math.log(m / 255.0)
            gammas.append(min(10.0, max(0.1, round(g, 2))))
    return (gammas[0], gammas[1], gammas[2])
```

Append to `src/pxv/canvas_view.py`, right after `selection_to_image_box` (module level):

```python
def canvas_point_to_image_xy(
    point: tuple[int, int],
    working_size: tuple[int, int],
    display_size: tuple[int, int],
    canvas_size: tuple[int, int],
    zoom: float,
) -> tuple[int, int] | None:
    """Map one canvas-space point to working-image pixel coords, or None if outside.

    AIDEV-NOTE: Single-point analog of selection_to_image_box — same centering
    offset and zoom math, kept pure for headless testing.
    """
    x, y = point
    img_w, img_h = working_size
    disp_w, disp_h = display_size
    canvas_w, canvas_h = canvas_size
    area_w = max(canvas_w, disp_w)
    area_h = max(canvas_h, disp_h)
    ix = int((x - (area_w - disp_w) / 2) / zoom)
    iy = int((y - (area_h - disp_h) / 2) / zoom)
    if ix < 0 or iy < 0 or ix >= img_w or iy >= img_h:
        return None
    return (ix, iy)
```

- [ ] **Step 4:** `uv run pytest tests/test_tone.py tests/test_canvas_geometry.py -v` → all PASS (28 + existing+3)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/tone.py src/pxv/canvas_view.py tests/test_tone.py tests/test_canvas_geometry.py
uv run mypy src/pxv
git add -A src/pxv/tone.py src/pxv/canvas_view.py tests/test_tone.py tests/test_canvas_geometry.py
git commit -m "feat(enhance): gray-balance gamma math and canvas point mapping

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `CanvasView` one-shot pick mode

**Files:** Modify `src/pxv/canvas_view.py`; modify `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancement_dialog_ui.py`:

```python
def test_canvas_pick_mode_consumes_click_and_disarms() -> None:
    from pxv.canvas_view import CanvasView

    root = tk.Tk()
    try:
        view = CanvasView(root)
        view.canvas.config(width=300, height=300)
        root.update()  # full update: an unmapped canvas reports winfo_width()==1
        view._display_width = 100
        view._display_height = 100
        view.zoom = 1.0
        picks: list[tuple[int, int] | None] = []
        view.set_pick_callback(picks.append, (100, 100))
        assert "tcross" in view.canvas.cget("cursor")
        view._on_press(types.SimpleNamespace(x=150, y=150))
        assert picks == [(50, 50)]
        assert view._rb_start is None  # no rubber band started
        assert view._pick_callback is None  # one-shot: disarmed
        assert view.canvas.cget("cursor") == "crosshair"
        # Next click is a normal rubber-band press again.
        view._on_press(types.SimpleNamespace(x=10, y=10))
        assert view._rb_start is not None
    finally:
        root.destroy()


def test_canvas_pick_outside_image_delivers_none() -> None:
    from pxv.canvas_view import CanvasView

    root = tk.Tk()
    try:
        view = CanvasView(root)
        view.canvas.config(width=300, height=300)
        root.update()  # full update: an unmapped canvas reports winfo_width()==1
        view._display_width = 100
        view._display_height = 100
        view.zoom = 1.0
        picks: list[tuple[int, int] | None] = []
        view.set_pick_callback(picks.append, (100, 100))
        view._on_press(types.SimpleNamespace(x=5, y=5))
        assert picks == [None]
    finally:
        root.destroy()
```

NOTE for the implementer: `_on_press` calls `self._canvas_xy(event)`, which uses
`canvas.canvasx/canvasy` — those work with a plain int attribute event only via
`event.x`; SimpleNamespace is the established driving pattern. If `_canvas_xy`
rejects SimpleNamespace, route the pick branch through `getattr(event, "x", 0)`
directly (before `_canvas_xy` is reached), which the implementation below does.

- [ ] **Step 2:** `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → AttributeError: set_pick_callback

- [ ] **Step 3: Implement in `src/pxv/canvas_view.py`**

In `CanvasView.__init__`, near the other state fields:

```python
        # One-shot eyedropper pick mode (None = normal rubber-band behavior).
        self._pick_callback: Callable[[tuple[int, int] | None], None] | None = None
        self._pick_working_size: tuple[int, int] | None = None
```

(Add `from collections.abc import Callable` to imports if not present.)

New method next to `get_selection_image_coords`:

```python
    def set_pick_callback(
        self,
        callback: Callable[[tuple[int, int] | None], None] | None,
        working_size: tuple[int, int] | None,
    ) -> None:
        """Arm (or disarm with None) a one-shot pick: the next click is consumed
        and the callback receives working-image coords, or None for a miss."""
        self._pick_callback = callback
        self._pick_working_size = working_size
        self.canvas.config(cursor="tcross" if callback is not None else "crosshair")
```

In `_on_press`, after the existing `self.canvas.focus_set()` line and BEFORE
`self.clear_selection()`:

```python
        # AIDEV-NOTE: Pick mode consumes this click entirely — no rubber band,
        # one shot, then auto-disarm (cursor restored) before delivering.
        if self._pick_callback is not None and self._pick_working_size is not None:
            callback = self._pick_callback
            coords = canvas_point_to_image_xy(
                (int(getattr(event, "x", 0)), int(getattr(event, "y", 0))),
                self._pick_working_size,
                (self._display_width, self._display_height),
                (self.canvas.winfo_width(), self.canvas.winfo_height()),
                self.zoom,
            )
            self.set_pick_callback(None, None)
            callback(coords)
            return
```

- [ ] **Step 4:** `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py tests/test_canvas_geometry.py -v` → all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/canvas_view.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/canvas_view.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): one-shot pick mode on the main canvas

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `tone_ui.py` dedup

**Files:** Create `src/pxv/tone_ui.py`; modify `src/pxv/levels_tab.py`, `src/pxv/curve_editor.py`.

- [ ] **Step 1:** No new tests — this is a behavior-preserving refactor guarded by the existing 261-test suite.

Create `src/pxv/tone_ui.py`:

```python
"""Shared UI bits for the tone-editing tabs (Levels, Curves).

AIDEV-NOTE: Extracted in Phase 4 because LevelsTab and CurveEditor carried
byte-identical channel constants and radio-row construction.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

CHANNEL_KEYS = [("master", "RGB"), ("r", "R"), ("g", "G"), ("b", "B")]
HIST_CHANNEL = {"master": "lum", "r": "r", "g": "g", "b": "b"}


def build_channel_row(
    parent: tk.Misc, variable: tk.StringVar, command: Callable[[], None]
) -> ttk.Frame:
    """Packed row of RGB/R/G/B radiobuttons; returned so callers can add to it."""
    row = ttk.Frame(parent)
    row.pack(fill=tk.X)
    for key, label in CHANNEL_KEYS:
        ttk.Radiobutton(
            row, text=label, value=key, variable=variable, command=command
        ).pack(side=tk.LEFT)
    return row
```

In `src/pxv/levels_tab.py`: delete the module-level `CHANNEL_KEYS` and
`_HIST_CHANNEL`; import `from pxv.tone_ui import HIST_CHANNEL, build_channel_row`;
replace the channel-row construction block (the `chan_row = ttk.Frame(self)` /
loop of Radiobuttons) with:

```python
        chan_row = build_channel_row(self, self._channel, self.sync_from_params)
        ttk.Button(chan_row, text="Auto", width=6, command=self._on_auto).pack(side=tk.RIGHT)
```

and change the `_HIST_CHANNEL[...]` lookup to `HIST_CHANNEL[...]`.

In `src/pxv/curve_editor.py`: same — drop its `CHANNEL_KEYS`/`_HIST_CHANNEL`,
import from `pxv.tone_ui`, replace its radio-row block with
`build_channel_row(self, self._channel, self.sync_from_params)` (it adds no
extra buttons to the row), switch the lookup to `HIST_CHANNEL`.

- [ ] **Step 2:** `DISPLAY=:99 uv run pytest` → 261 pass (pure refactor, no count change)

- [ ] **Step 3: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/tone_ui.py src/pxv/levels_tab.py src/pxv/curve_editor.py
uv run mypy src/pxv
git add src/pxv/tone_ui.py src/pxv/levels_tab.py src/pxv/curve_editor.py
git commit -m "refactor(enhance): extract shared channel-row helpers to tone_ui

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Eyedroppers

**Files:** Modify `src/pxv/levels_tab.py`, `src/pxv/enhancement_dialog.py`; modify `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancement_dialog_ui.py`:

```python
def _levels_tab_with_pick(
    root: "tk.Tk", sample: tuple[int, int, int] | None
) -> tuple[object, dict[str, object], list[bool]]:
    """LevelsTab whose request_pick immediately delivers `sample`."""
    from pxv.histogram_panel import compute_histograms
    from pxv.levels_tab import LevelsTab
    from pxv.tone import LevelsChannel

    store: dict[str, LevelsChannel] = {
        key: LevelsChannel() for key in ("master", "r", "g", "b")
    }
    changes: list[bool] = []
    hists = compute_histograms(Image.new("RGB", (16, 16), (10, 200, 60)))

    def request_pick(on_sample):  # noqa: ANN001, ANN202 - test double
        on_sample(sample)
        return lambda: None

    tab = LevelsTab(
        root,
        get_levels=store.__getitem__,
        set_levels=store.__setitem__,
        get_input_histograms=lambda: hists,
        on_change=lambda: changes.append(True),
        request_pick=request_pick,
    )
    return tab, store, changes


def test_eyedropper_black_sets_per_channel_black_points() -> None:
    root = tk.Tk()
    try:
        tab, store, changes = _levels_tab_with_pick(root, (10, 60, 30))
        tab._on_eyedropper("black")
        assert store["r"].in_black == 10
        assert store["g"].in_black == 60
        assert store["b"].in_black == 30
        assert store["master"].is_identity()
        assert changes
    finally:
        root.destroy()


def test_eyedropper_white_sets_per_channel_white_points() -> None:
    root = tk.Tk()
    try:
        tab, store, _changes = _levels_tab_with_pick(root, (240, 200, 220))
        tab._on_eyedropper("white")
        assert store["r"].in_white == 240
        assert store["g"].in_white == 200
        assert store["b"].in_white == 220
    finally:
        root.destroy()


def test_eyedropper_gray_sets_balancing_gammas() -> None:
    from pxv.tone import gray_balance_gammas

    root = tk.Tk()
    try:
        tab, store, _changes = _levels_tab_with_pick(root, (200, 128, 100))
        tab._on_eyedropper("gray")
        gr, gg, gb = gray_balance_gammas((200, 128, 100))
        assert store["r"].gamma == gr
        assert store["g"].gamma == gg
        assert store["b"].gamma == gb
    finally:
        root.destroy()


def test_eyedropper_cancelled_pick_changes_nothing() -> None:
    root = tk.Tk()
    try:
        tab, store, changes = _levels_tab_with_pick(root, None)
        tab._on_eyedropper("black")
        assert all(store[k].is_identity() for k in ("master", "r", "g", "b"))
        assert changes == []
    finally:
        root.destroy()


def test_dialog_request_pick_samples_working_image() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        samples: list[tuple[int, int, int] | None] = []
        cancel = dlg._request_pick(samples.append)
        # The canvas is now armed; simulate a hit at image coords (2, 3).
        cb = app.canvas_view._pick_callback
        assert cb is not None
        app.canvas_view.set_pick_callback(None, None)
        cb((2, 3))
        assert samples == [(120, 90, 200)]  # _make_app's working_image color
        # Cancel path: re-arm then cancel -> delivers None and disarms.
        cancel = dlg._request_pick(samples.append)
        cancel()
        assert samples[-1] is None
        assert app.canvas_view._pick_callback is None
        dlg._on_close()
    finally:
        root.destroy()
```

- [ ] **Step 2:** `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → new tests FAIL (unexpected kwarg request_pick / no _request_pick)

- [ ] **Step 3: Implement**

In `src/pxv/levels_tab.py`:

(a) Extend the tone import with `gray_balance_gammas`. Add constructor parameter
(after `on_change`):

```python
        request_pick: Callable[
            [Callable[[tuple[int, int, int] | None], None]], Callable[[], None]
        ]
        | None = None,
```

store it (`self._request_pick = request_pick`) and init pick state:

```python
        self._pick_cancel: Callable[[], None] | None = None
        self._pick_kind: str | None = None
```

(b) Add an eyedropper row after the spinbox row in `__init__`:

```python
        pick_row = ttk.Frame(self)
        pick_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(pick_row, text="Pick:").pack(side=tk.LEFT, padx=(0, 4))
        for kind, label in (("black", "Black"), ("gray", "Gray"), ("white", "White")):
            ttk.Button(
                pick_row,
                text=label,
                width=6,
                command=lambda k=kind: self._on_eyedropper(k),
            ).pack(side=tk.LEFT, padx=2)
```

(c) Add the handlers (after `_on_auto`):

```python
    def _on_eyedropper(self, kind: str) -> None:
        """Arm a one-shot pick on the main canvas; second press cancels.

        AIDEV-NOTE: No root <Escape> cancel binding on purpose — tkinter's
        unbind(seq, funcid) removes ALL bindings for the sequence (bpo-31485),
        so a temporary bind would clobber future root Escape bindings.
        Cancel paths: press the same button again, press another eyedropper
        (re-arms), or click outside the image (delivers None).
        """
        if self._request_pick is None:
            return
        if self._pick_cancel is not None:
            cancel, armed = self._pick_cancel, self._pick_kind
            self._pick_cancel = None
            self._pick_kind = None
            cancel()
            if armed == kind:
                return  # second press on the same button = plain cancel

        def on_sample(sample: tuple[int, int, int] | None) -> None:
            self._pick_cancel = None
            self._pick_kind = None
            self._apply_pick(kind, sample)

        self._pick_cancel = self._request_pick(on_sample)
        self._pick_kind = kind

    def _apply_pick(self, kind: str, sample: tuple[int, int, int] | None) -> None:
        """Apply a sampled pixel to per-channel levels (black/white/gray)."""
        if sample is None:
            return
        if kind == "gray":
            for key, gamma in zip(("r", "g", "b"), gray_balance_gammas(sample)):
                self._set_levels(key, replace(self._get_levels(key), gamma=gamma))
        else:
            for key, value in zip(("r", "g", "b"), sample):
                ch = self._get_levels(key)
                if kind == "black":
                    ch = replace(ch, in_black=min(value, ch.in_white - 1))
                else:
                    ch = replace(ch, in_white=max(value, ch.in_black + 1))
                self._set_levels(key, ch)
        self._on_change()
        self.sync_from_params()
```

In `src/pxv/enhancement_dialog.py`:

(d) Pass the plumbing when constructing LevelsTab — add `request_pick=self._request_pick,` to the `LevelsTab(...)` call.

(e) Add the method (near `_input_histograms`); `Callable` is already imported:

```python
    def _request_pick(
        self, on_sample: Callable[[tuple[int, int, int] | None], None]
    ) -> Callable[[], None]:
        """Arm a one-shot eyedropper pick on the main canvas; returns a cancel.

        AIDEV-NOTE: Samples the WORKING image (input side), consistent with the
        Levels strip — see the spec's eyedropper-approximation note. No image
        means an immediate None delivery.
        """
        img = self.app.image_model.working_image
        if img is None:
            on_sample(None)
            return lambda: None

        def deliver(coords: tuple[int, int] | None) -> None:
            if coords is None:
                on_sample(None)
                return
            pixel = img.getpixel(coords)
            on_sample((int(pixel[0]), int(pixel[1]), int(pixel[2])))

        self.app.canvas_view.set_pick_callback(deliver, img.size)

        def cancel() -> None:
            self.app.canvas_view.set_pick_callback(None, None)
            on_sample(None)

        return cancel
```

- [ ] **Step 4:** `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py tests/test_dialog_focus.py -v` → all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/levels_tab.py src/pxv/enhancement_dialog.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/levels_tab.py src/pxv/enhancement_dialog.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): black/gray/white eyedroppers via canvas pick mode

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Compare (hold for before/after)

**Files:** Modify `src/pxv/app.py`, `src/pxv/enhancement_dialog.py`; modify `tests/test_histogram_panel.py`, `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_histogram_panel.py`, extend `_refresh_double` with FOUR precise
edits (keep every existing field untouched otherwise):

1. Before the `app = types.SimpleNamespace(` line add: `received_params: list[object] = []`
2. Replace the `get_display_image=...` lambda with one that records its params:
   `get_display_image=lambda zoom, params, bg_color: (received_params.append(params), display_img)[1],`
3. Add a field to the SimpleNamespace: `_compare_active=False,`
4. After the SimpleNamespace construction add:
   ```python
   from pxv.app import PxvApp

   app._active_params = types.MethodType(PxvApp._active_params, app)
   app.received_params = received_params
   ```

Append:

```python
def test_refresh_display_uses_live_params_normally() -> None:
    from pxv.app import PxvApp

    app, _received = _refresh_double(None)
    PxvApp.refresh_display(app)
    assert app.received_params == [app.enhancement_params]


def test_refresh_display_substitutes_identity_during_compare() -> None:
    from pxv.app import PxvApp
    from pxv.tone import LevelsChannel

    app, _received = _refresh_double(None)
    app.enhancement_params.levels_master = LevelsChannel(in_black=40)
    app._compare_active = True
    PxvApp.refresh_display(app)
    assert len(app.received_params) == 1
    assert app.received_params[0] is not app.enhancement_params
    assert app.received_params[0].is_identity()
```

Append to `tests/test_enhancement_dialog_ui.py` (also add `_compare_active=False`
to `_make_app`'s SimpleNamespace fields):

```python
def test_dialog_compare_press_and_release_toggle_flag() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg._on_compare_press(types.SimpleNamespace())
        assert app._compare_active is True
        assert app.refresh_calls  # re-rendered to show the original
        dlg._on_compare_release(types.SimpleNamespace())
        assert app._compare_active is False
        # Close while held must never leave the flag stuck:
        dlg._on_compare_press(types.SimpleNamespace())
        dlg._on_close()
        assert app._compare_active is False
    finally:
        root.destroy()
```

- [ ] **Step 2:** Run both files → new tests FAIL (no `_active_params` / `_on_compare_press`)

- [ ] **Step 3: Implement**

In `src/pxv/app.py`:

- `__init__`: add `self._compare_active = False` near the other display-state fields.
- New method next to `refresh_display`:

```python
    def _active_params(self) -> EnhancementParams:
        """Identity params while Compare is held in the dialog, else the live ones.

        AIDEV-NOTE: Read at refresh time, so an in-flight debounce timer firing
        during a Compare hold still renders the compare (original) state.
        """
        return EnhancementParams() if self._compare_active else self.enhancement_params
```

- In `refresh_display` AND `_update_display`, change `params=self.enhancement_params,`
  to `params=self._active_params(),`.

In `src/pxv/enhancement_dialog.py`:

- In `_build_ui`'s button row, between Reset and Close:

```python
        compare_btn = ttk.Button(btn_frame, text="Compare", width=8)
        compare_btn.pack(side=tk.LEFT, padx=4)
        # Hold-to-compare: press shows the unenhanced image, release restores.
        compare_btn.bind("<ButtonPress-1>", self._on_compare_press)
        compare_btn.bind("<ButtonRelease-1>", self._on_compare_release)
```

- New handlers (near `_on_reset`):

```python
    def _on_compare_press(self, _event: object) -> None:
        self.app._compare_active = True
        self.app.refresh_display()

    def _on_compare_release(self, _event: object) -> None:
        self.app._compare_active = False
        self.app.refresh_display()
```

- In `_on_close`, before `self.destroy()`: add

```python
        self.app._compare_active = False
```

- [ ] **Step 4:** `uv run pytest tests/test_histogram_panel.py -v` and `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/app.py src/pxv/enhancement_dialog.py tests/test_histogram_panel.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/app.py src/pxv/enhancement_dialog.py tests/test_histogram_panel.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): hold-to-compare before/after button

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Integration test, docs, full verification

**Files:** Modify `tests/test_enhancement_dialog_ui.py`, `README.md`, `CHANGELOG.md`.

- [ ] **Step 1: Integration test (levels + curves through Apply/undo)**

Append to `tests/test_enhancement_dialog_ui.py`. CHECK the real constructor
signatures first (`src/pxv/app.py` `PxvApp.__init__`, `src/pxv/file_list.py`
`FileList.__init__`) and adapt the construction lines — the Phase 1-3 smokes
used `tk root + FileList + PxvApp + load_current` successfully:

```python
def test_apply_undo_round_trips_levels_and_curves(tmp_path: "Path") -> None:
    from pxv import commands
    from pxv.app import PxvApp
    from pxv.file_list import FileList
    from pxv.tone import LevelsChannel

    img_path = tmp_path / "t.png"
    Image.effect_noise((40, 30), 64).convert("RGB").save(img_path)
    root = tk.Tk()
    try:
        app = PxvApp(root, FileList([str(img_path)]))
        app.load_current()
        commands.cmd_enhancement_dialog(app)
        dlg = app.enhancement_dialog
        assert dlg is not None
        app.enhancement_params.levels_master = LevelsChannel(in_black=20, gamma=1.5)
        app.enhancement_params.curve_master = ((0, 0), (96, 160), (255, 255))
        dlg.sync_sliders_from_params()
        dlg._on_apply()
        assert app.enhancement_params.is_identity()
        assert app.history.can_undo
        app.undo()
        assert app.enhancement_params.levels_master == LevelsChannel(in_black=20, gamma=1.5)
        assert app.enhancement_params.curve_master == ((0, 0), (96, 160), (255, 255))
        assert dlg.curve_editor._points() == [(0, 0), (96, 160), (255, 255)]
        dlg._on_close()
    finally:
        root.destroy()
```

(Add `from pathlib import Path` under `if TYPE_CHECKING:` or just import it
plainly at the top — tests are not mypy-gated.)

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → passes.

- [ ] **Step 2: README**

In `README.md`, replace the body of the `## Enhancements` section (keep the
heading and intro line) with:

```markdown
The enhancement dialog (`e`) provides real-time adjustment with a live
histogram (luminance + RGB overlays, log scale, clipping readouts) that tracks
every change:

- **Sliders** — brightness, contrast, gamma, sharpen, blur, saturation, hue
  rotation, per-channel RGB balance
- **Levels** — black/gamma/white input markers over the channel histogram,
  output range, Auto (percentile clip), and black/gray/white eyedroppers that
  sample the image
- **Curves** — spline curve editor per channel (master + R/G/B) with histogram
  backdrop, editable histogram Equalize, and Invert — the classic xv intensity
  and RGB graphs, modernized

**Compare** (hold) flips between the original and adjusted image; **Apply**
bakes the adjustments into the working image (undoable with `u`/Ctrl+Z).
```

Also add to the `## Features` list:

```markdown
- Histogram, levels, and curves in the enhancement dialog (beyond-xv: live histogram backdrop, eyedroppers, editable equalization)
```

- [ ] **Step 3: CHANGELOG**

Under `## [Unreleased]` / `### Added` in `CHANGELOG.md`, add (create the
`### Added` heading if a release consumed it):

```markdown
- Enhancement dialog overhaul: live histogram panel (luminance/RGB overlays,
  log scale, clipping readouts), a Levels tab (per-channel black/gamma/white
  markers, output range, Auto, black/gray/white eyedroppers), a Curves tab
  (monotone spline editor per channel with histogram backdrop, editable
  Equalize, Invert), and a hold-to-Compare before/after button. All
  adjustments compose into a single LUT pass and bake undoably via Apply.
```

- [ ] **Step 4: Remove the shipped idea from Ideas.md**

In `Ideas.md`, delete the line
`- A histogram (and levels/curves) in the enhancement dialog — also classic xv.`
from the honorable mentions (it's shipped). NOTE: Ideas.md is untracked — edit
the file but do NOT `git add` it.

- [ ] **Step 5: Full verification**

```bash
DISPLAY=:99 uv run pytest          # expect 278 pass, 0 fail
uv run ruff format --check src tests
uv run mypy src/pxv
```

Count basis: 261 at Phase-3 close + 6 (Task 1: 3 tone, 3 geometry) + 2 (Task 2)
+ 5 (Task 4) + 3 (Task 5) + 1 (Task 6) = 278. Report the actual number; the
hard requirements are 0 failures and that every new test ran.

- [ ] **Step 6: Commit**

```bash
git add tests/test_enhancement_dialog_ui.py README.md CHANGELOG.md
git commit -m "test+docs(enhance): levels+curves integration test; document the feature

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## After this plan

Full-feature smoke + final whole-feature review happen outside the plan
(controller-driven), then the branch is ready for merge consideration.
