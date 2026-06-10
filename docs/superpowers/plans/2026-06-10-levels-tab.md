# Levels Tab (Phase 2 of Histogram/Levels/Curves) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Photoshop-style Levels editing (black/gamma/white input markers, output range, per-channel, Auto button) as a second tab in the Enhancements dialog, composed into the existing single-LUT pipeline pass.

**Architecture:** New pure module `tone.py` (LevelsChannel, levels LUT, LUT composition, auto-levels, gamma↔marker math — all headlessly testable). `EnhancementParams` gains four immutable `LevelsChannel` fields that compose into the existing `Image.point()` LUT pass in fixed order: base (brightness·gamma·balance) → master levels → channel levels. New widget module `levels_tab.py` (decoupled from the app via injected callbacks, same pattern as `HistogramPanel`) hosts the UI; the dialog wires it into the Notebook and shares its 30ms debounce.

**Deviation from spec, intentional:** the spec sketches the Levels tab "inside enhancement_dialog.py"; this plan puts the widget in its own `levels_tab.py` module for file focus (the dialog stays a thin coordinator, the widget is independently testable with stub callbacks). Functionality is identical to the spec.

**Tech Stack:** Python 3.10+, Pillow only, tkinter/ttk, pytest, uv, ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-06-10-histogram-levels-curves-design.md` · **Branch:** `histograms` (Phase 1 merged through `35eb35c`).

---

## Environment notes for the executor

- Pure tests: `uv run pytest <file> -v`. DISPLAY-gated tests: Xvfb is already running on :99 → `DISPLAY=:99 uv run pytest <file> -v`.
- After writing Python: `uv run ruff format <files>` and `uv run mypy src/pxv` (strict).
- Never remove existing `AIDEV-NOTE` comments.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/tone.py` | create | Pure levels math: LevelsChannel, levels_lut, compose_luts, auto_levels, gamma↔mid mapping |
| `src/pxv/enhancements.py` | modify | Four levels fields on EnhancementParams; LUT composition in apply_enhancements |
| `src/pxv/levels_tab.py` | create | LevelsTab widget (histogram strip, draggable markers, output bar, spinboxes, Auto) |
| `src/pxv/enhancement_dialog.py` | modify | Add Levels tab; levels get/set plumbing; input-histogram cache; shared `_schedule_refresh` |
| `tests/test_tone.py` | create | Pure math tests |
| `tests/test_enhancements.py` | modify | Params identity/reset + pipeline composition tests |
| `tests/test_enhancement_dialog_ui.py` | modify | DISPLAY-gated LevelsTab + dialog wiring tests |

---

### Task 1: `tone.py` — `LevelsChannel` + `levels_lut`

**Files:** Create `src/pxv/tone.py`, create `tests/test_tone.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tone.py`:

```python
"""Tests for the pure tone-mapping math (levels, LUT composition, auto-levels)."""

from __future__ import annotations

from pxv.tone import LevelsChannel, levels_lut

IDENTITY = list(range(256))


def test_levels_channel_identity() -> None:
    assert LevelsChannel().is_identity()
    assert not LevelsChannel(in_black=1).is_identity()
    assert not LevelsChannel(gamma=2.0).is_identity()
    assert not LevelsChannel(out_white=200).is_identity()


def test_levels_lut_identity() -> None:
    assert levels_lut(LevelsChannel()) == IDENTITY


def test_levels_lut_endpoints_and_clamp() -> None:
    lut = levels_lut(LevelsChannel(in_black=64, in_white=192))
    assert lut[0] == 0 and lut[64] == 0  # at/below the black point
    assert lut[192] == 255 and lut[255] == 255  # at/above the white point
    assert lut[128] == 128  # midpoint stays put at gamma 1


def test_levels_lut_gamma_brightens_midtones() -> None:
    lut = levels_lut(LevelsChannel(gamma=2.0))
    # t**(1/2): input 64 (t~0.251) -> ~0.501 -> ~128
    assert 126 <= lut[64] <= 130
    assert lut[0] == 0 and lut[255] == 255


def test_levels_lut_output_range() -> None:
    lut = levels_lut(LevelsChannel(out_black=64, out_white=192))
    assert lut[0] == 64 and lut[255] == 192


def test_levels_lut_inverted_output() -> None:
    lut = levels_lut(LevelsChannel(out_black=255, out_white=0))
    assert lut[0] == 255 and lut[255] == 0


def test_levels_lut_degenerate_span_guard() -> None:
    lut = levels_lut(LevelsChannel(in_black=128, in_white=128))
    assert all(0 <= v <= 255 for v in lut)  # must not divide by zero
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tone.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'pxv.tone')

- [ ] **Step 3: Write the implementation**

Create `src/pxv/tone.py`:

```python
"""Pure tone-mapping math for levels (and, in a later phase, curves).

AIDEV-NOTE: Everything here is display-free and unit-tested headlessly.
LevelsChannel is FROZEN on purpose: EnhancementParams snapshots use
dataclasses.replace() (a shallow copy), so every nested params field must be
immutable or undo/redo silently shares state (see the 2026-06-10 design).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LevelsChannel:
    """Input/output levels for one channel. Defaults are identity."""

    in_black: int = 0
    in_white: int = 255
    gamma: float = 1.0
    out_black: int = 0
    out_white: int = 255

    def is_identity(self) -> bool:
        return (
            self.in_black == 0
            and self.in_white == 255
            and self.gamma == 1.0
            and self.out_black == 0
            and self.out_white == 255
        )


def levels_lut(ch: LevelsChannel) -> list[int]:
    """256-entry LUT: out_b + clamp01((i - in_b)/(in_w - in_b))**(1/gamma) * (out_w - out_b)."""
    span = max(1, ch.in_white - ch.in_black)
    inv_gamma = 1.0 / ch.gamma if ch.gamma > 0 else 1.0
    out_span = ch.out_white - ch.out_black
    lut: list[int] = []
    for i in range(256):
        t = min(1.0, max(0.0, (i - ch.in_black) / span))
        v = ch.out_black + (t**inv_gamma) * out_span
        lut.append(max(0, min(255, int(v + 0.5))))
    return lut
```

(`import math` is used by Task 2's functions; if ruff flags it now, add it in Task 2 instead.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tone.py -v`
Expected: 7 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/tone.py tests/test_tone.py
uv run mypy src/pxv
git add src/pxv/tone.py tests/test_tone.py
git commit -m "feat(enhance): LevelsChannel and levels LUT math

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `tone.py` — `compose_luts`, `auto_levels`, gamma↔mid mapping

**Files:** Modify `src/pxv/tone.py`, modify `tests/test_tone.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tone.py` (extend the import to add `auto_levels, compose_luts, gamma_to_mid, mid_to_gamma`; add `import pytest` at the top):

```python
def test_compose_luts() -> None:
    assert compose_luts(IDENTITY, IDENTITY) == IDENTITY
    invert = [255 - i for i in range(256)]
    assert compose_luts(invert, invert) == IDENTITY
    half = [i // 2 for i in range(256)]
    assert compose_luts(half, invert)[0] == 255  # invert(half(0))
    assert compose_luts(invert, half)[0] == 127  # half(invert(0))


def test_auto_levels_finds_black_white_points() -> None:
    hist = [0] * 768
    for c in range(3):
        hist[c * 256 + 30] = 100
        hist[c * 256 + 220] = 100
    r, g, b = auto_levels(hist, clip_percent=0.5)
    for ch in (r, g, b):
        assert ch.in_black == 30
        assert ch.in_white == 220
        assert ch.gamma == 1.0 and ch.out_black == 0 and ch.out_white == 255


def test_auto_levels_empty_histogram_is_identity() -> None:
    r, g, b = auto_levels([0] * 768)
    assert r.is_identity() and g.is_identity() and b.is_identity()


def test_auto_levels_degenerate_single_bin() -> None:
    hist = [0] * 768
    hist[128] = 1000  # R only; G/B empty
    r, g, b = auto_levels(hist)
    assert r.is_identity()  # hi <= lo -> identity fallback
    assert g.is_identity() and b.is_identity()


def test_gamma_mid_roundtrip() -> None:
    for gamma in (0.2, 0.5, 1.0, 2.0, 5.0):
        x = gamma_to_mid(0, 255, gamma)
        assert mid_to_gamma(0, 255, x) == pytest.approx(gamma, rel=1e-3)


def test_mid_to_gamma_clamps_at_extremes() -> None:
    assert mid_to_gamma(0, 255, 0.0) == 10.0  # far left -> max gamma
    assert mid_to_gamma(0, 255, 255.0) == 0.1  # far right -> min gamma
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tone.py -v`
Expected: new tests FAIL (ImportError)

- [ ] **Step 3: Write the implementation**

Append to `src/pxv/tone.py`:

```python
def compose_luts(*luts: list[int]) -> list[int]:
    """Compose 256-entry LUTs left to right: result[i] = last(...(first[i])...)."""
    result = list(range(256))
    for lut in luts:
        result = [lut[v] for v in result]
    return result


def auto_levels(
    hist_rgb: list[int], clip_percent: float = 0.5
) -> tuple[LevelsChannel, LevelsChannel, LevelsChannel]:
    """Per-channel black/white points clipping clip_percent% of pixels per end.

    Takes the 768-entry Image.histogram() of the (pre-enhancement) working
    image. Channels with no data or a degenerate range come back as identity.
    """
    out: list[LevelsChannel] = []
    for c in range(3):
        bins = hist_rgb[c * 256 : (c + 1) * 256]
        total = sum(bins)
        if total == 0:
            out.append(LevelsChannel())
            continue
        clip = total * clip_percent / 100.0
        acc = 0
        lo = 0
        for i in range(256):
            acc += bins[i]
            if acc > clip:
                lo = i
                break
        acc = 0
        hi = 255
        for i in range(255, -1, -1):
            acc += bins[i]
            if acc > clip:
                hi = i
                break
        if hi <= lo:
            out.append(LevelsChannel())
        else:
            out.append(LevelsChannel(in_black=lo, in_white=hi))
    return (out[0], out[1], out[2])


def gamma_to_mid(in_black: int, in_white: int, gamma: float) -> float:
    """Marker x-position whose input value maps to 50% output (the gamma diamond).

    AIDEV-NOTE: levels_lut outputs 0.5 where t**(1/gamma) == 0.5, i.e. at
    t = 0.5**gamma — keep this and mid_to_gamma in sync with levels_lut.
    """
    span = max(1, in_white - in_black)
    return in_black + span * (0.5**gamma)


def mid_to_gamma(in_black: int, in_white: int, x: float) -> float:
    """Inverse of gamma_to_mid, with t clamped so the result stays in [0.1, 10]."""
    span = max(1, in_white - in_black)
    t = min(0.9995, max(0.0005, (x - in_black) / span))
    return min(10.0, max(0.1, math.log(t) / math.log(0.5)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tone.py -v`
Expected: 13 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/tone.py tests/test_tone.py
uv run mypy src/pxv
git add src/pxv/tone.py tests/test_tone.py
git commit -m "feat(enhance): LUT composition, auto-levels, gamma marker math

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `EnhancementParams` levels fields + pipeline composition

**Files:** Modify `src/pxv/enhancements.py`, modify `tests/test_enhancements.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancements.py` (it already imports `EnhancementParams`, `apply_enhancements`, and `Image`; add `from pxv.tone import LevelsChannel`):

```python
def test_params_identity_covers_levels() -> None:
    p = EnhancementParams()
    assert p.is_identity()
    p.levels_r = LevelsChannel(in_black=10)
    assert not p.is_identity()
    p.reset()
    assert p.is_identity()


def test_apply_enhancements_master_levels() -> None:
    img = Image.new("RGB", (2, 2), (64, 128, 192))
    p = EnhancementParams()
    p.levels_master = LevelsChannel(in_black=64, in_white=192)
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0)) == (0, 128, 255)


def test_apply_enhancements_per_channel_levels() -> None:
    img = Image.new("RGB", (2, 2), (100, 100, 100))
    p = EnhancementParams()
    p.levels_r = LevelsChannel(out_black=255, out_white=0)  # invert R only
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0)) == (155, 100, 100)


def test_apply_enhancements_master_before_channel_levels() -> None:
    # Master maps 128 -> 50 (out_white=100); the R channel's in_black=100 then
    # cuts 50 to 0. The reversed order would give R ~18, so this pins the
    # spec's fixed composition order: master levels BEFORE channel levels.
    img = Image.new("RGB", (1, 1), (128, 128, 128))
    p = EnhancementParams()
    p.levels_master = LevelsChannel(out_white=100)
    p.levels_r = LevelsChannel(in_black=100)
    out = apply_enhancements(img, p)
    px = out.getpixel((0, 0))
    assert px[0] == 0
    assert px[1] == 50 and px[2] == 50  # master only on G/B
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enhancements.py -v`
Expected: new tests FAIL (AttributeError: levels_r / levels_master)

- [ ] **Step 3: Modify `src/pxv/enhancements.py`**

(a) Add the import after the PIL import:

```python
from pxv.tone import LevelsChannel, compose_luts, levels_lut
```

(b) Add four fields to `EnhancementParams` after `blur: float = 0.0` (frozen-dataclass defaults are immutable, so sharing the default instance is safe):

```python
    levels_master: LevelsChannel = LevelsChannel()
    levels_r: LevelsChannel = LevelsChannel()
    levels_g: LevelsChannel = LevelsChannel()
    levels_b: LevelsChannel = LevelsChannel()
```

(c) Extend `is_identity()` — add to the conjunction before the closing paren:

```python
            and self.levels_master.is_identity()
            and self.levels_r.is_identity()
            and self.levels_g.is_identity()
            and self.levels_b.is_identity()
```

(d) Extend `reset()` — append:

```python
        self.levels_master = LevelsChannel()
        self.levels_r = LevelsChannel()
        self.levels_g = LevelsChannel()
        self.levels_b = LevelsChannel()
```

(e) In `apply_enhancements`, replace the step-4 block (from the `# 4. Combined LUT pass` comment through `result = result.point(lut)`) with:

```python
    # 4. Combined LUT pass (brightness + gamma + RGB balance + levels)
    levels_active = not (
        params.levels_master.is_identity()
        and params.levels_r.is_identity()
        and params.levels_g.is_identity()
        and params.levels_b.is_identity()
    )
    needs_lut = (
        params.brightness != 1.0
        or params.gamma != 1.0
        or params.r_balance != 1.0
        or params.g_balance != 1.0
        or params.b_balance != 1.0
        or levels_active
    )
    if needs_lut:
        base = _build_lut(
            params.brightness, params.gamma, params.r_balance, params.g_balance, params.b_balance
        )
        if levels_active:
            # AIDEV-NOTE: Fixed composition order per the 2026-06-10 design:
            # base (brightness+gamma+balance) -> master levels -> channel
            # levels. Curves will append here in Phase 3.
            master = levels_lut(params.levels_master)
            lut: list[int] = []
            for idx, ch in enumerate((params.levels_r, params.levels_g, params.levels_b)):
                lut.extend(
                    compose_luts(base[idx * 256 : (idx + 1) * 256], master, levels_lut(ch))
                )
        else:
            lut = base
        result = result.point(lut)
```

Also update the module docstring's pipeline line to read `Combined LUT (brightness+gamma+RGB+levels)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_enhancements.py tests/test_tone.py -v`
Expected: all PASS (existing enhancement tests must stay green — `is_identity` short-circuit and the LUT-only path are exercised by them)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/enhancements.py tests/test_enhancements.py
uv run mypy src/pxv
git add src/pxv/enhancements.py tests/test_enhancements.py
git commit -m "feat(enhance): per-channel levels composed into the pipeline LUT

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `levels_tab.py` widget

**Files:** Create `src/pxv/levels_tab.py`; modify `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancement_dialog_ui.py`:

```python
def _make_levels_tab(
    root: "tk.Tk",
) -> tuple[object, dict[str, object], list[bool]]:
    """LevelsTab wired to a dict-backed store — no app or dialog needed."""
    from pxv.histogram_panel import compute_histograms
    from pxv.levels_tab import LevelsTab
    from pxv.tone import LevelsChannel

    store: dict[str, LevelsChannel] = {
        key: LevelsChannel() for key in ("master", "r", "g", "b")
    }
    changes: list[bool] = []
    hists = compute_histograms(Image.new("RGB", (16, 16), (10, 200, 60)))
    tab = LevelsTab(
        root,
        get_levels=store.__getitem__,
        set_levels=store.__setitem__,
        get_input_histograms=lambda: hists,
        on_change=lambda: changes.append(True),
    )
    return tab, store, changes


def test_levels_tab_builds_with_histogram_strip() -> None:
    root = tk.Tk()
    try:
        tab, _store, _changes = _make_levels_tab(root)
        assert tab._hist_photo is not None
        assert tab._spins["in_black"].get() == "0"
        assert tab._spins["gamma"].get() == "1.00"
    finally:
        root.destroy()


def test_levels_tab_marker_drag_updates_store() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, changes = _make_levels_tab(root)
        tab._on_in_press(types.SimpleNamespace(x=2))  # nearest = black marker
        tab._on_in_drag(types.SimpleNamespace(x=50))
        tab._on_release(types.SimpleNamespace())
        assert store["master"].in_black == 50
        assert changes  # debounce hook fired
        # Black can never cross white-1.
        store["master"] = LevelsChannel(in_black=0, in_white=60)
        tab.sync_from_params()
        tab._on_in_press(types.SimpleNamespace(x=2))
        tab._on_in_drag(types.SimpleNamespace(x=200))
        assert store["master"].in_black == 59
    finally:
        root.destroy()


def test_levels_tab_channel_switch_shows_channel_values() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, _changes = _make_levels_tab(root)
        store["r"] = LevelsChannel(in_black=42)
        tab._channel.set("r")
        tab.sync_from_params()
        assert tab._spins["in_black"].get() == "42"
    finally:
        root.destroy()


def test_levels_tab_spinbox_edit_updates_store() -> None:
    root = tk.Tk()
    try:
        tab, store, changes = _make_levels_tab(root)
        tab._spins["in_black"].delete(0, tk.END)
        tab._spins["in_black"].insert(0, "30")
        tab._on_spin_change()
        assert store["master"].in_black == 30
        assert changes
    finally:
        root.destroy()


def test_levels_tab_auto_sets_per_channel() -> None:
    root = tk.Tk()
    try:
        tab, store, changes = _make_levels_tab(root)
        tab._on_auto()
        # Solid color (10, 200, 60): every channel collapses to one bin ->
        # auto_levels degenerate fallback -> identity per channel; the point
        # here is that Auto ran per-channel and fired the change hook.
        assert changes
        assert store["master"].is_identity()  # Auto never touches master
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v`
Expected: new tests FAIL (ModuleNotFoundError: pxv.levels_tab)

- [ ] **Step 3: Write the implementation**

Create `src/pxv/levels_tab.py`:

```python
"""Levels tab widget: histogram strip with draggable black/gamma/white markers.

AIDEV-NOTE: Pure math (levels_lut, gamma_to_mid/mid_to_gamma, auto_levels)
lives in tone.py; this module is only the Tk shell, decoupled from the app via
callbacks the dialog injects (get_levels/set_levels/get_input_histograms/
on_change) — same pattern as HistogramPanel. Marker x-coordinates equal input
values directly because the strip is exactly 256px wide.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk

from PIL import Image, ImageTk

from pxv.histogram_panel import render_histogram
from pxv.tone import LevelsChannel, auto_levels, gamma_to_mid, mid_to_gamma

STRIP_SIZE = (256, 80)
MARKER_H = 14
CHANNEL_KEYS = [("master", "RGB"), ("r", "R"), ("g", "G"), ("b", "B")]
_HIST_CHANNEL = {"master": "lum", "r": "r", "g": "g", "b": "b"}


class LevelsTab(ttk.Frame):
    """Channel levels editor: input markers, output range, spinboxes, Auto."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_levels: Callable[[str], LevelsChannel],
        set_levels: Callable[[str, LevelsChannel], None],
        get_input_histograms: Callable[[], tuple[list[int], list[int]] | None],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=6)
        self._get_levels = get_levels
        self._set_levels = set_levels
        self._get_input_histograms = get_input_histograms
        self._on_change = on_change

        self._channel = tk.StringVar(value="master")
        self._updating = False  # guard: programmatic spinbox writes
        self._drag: str | None = None
        self._hist_photo: ImageTk.PhotoImage | None = None
        self._grad_photo: ImageTk.PhotoImage | None = None

        chan_row = ttk.Frame(self)
        chan_row.pack(fill=tk.X)
        for key, label in CHANNEL_KEYS:
            ttk.Radiobutton(
                chan_row,
                text=label,
                value=key,
                variable=self._channel,
                command=self.sync_from_params,
            ).pack(side=tk.LEFT)
        ttk.Button(chan_row, text="Auto", width=6, command=self._on_auto).pack(side=tk.RIGHT)

        w, h = STRIP_SIZE
        self._hist_canvas = tk.Canvas(self, width=w, height=h, bg="#181818", highlightthickness=0)
        self._hist_canvas.pack(pady=(4, 0))

        self._in_canvas = tk.Canvas(self, width=w, height=MARKER_H, highlightthickness=0)
        self._in_canvas.pack()
        self._in_canvas.bind("<Button-1>", self._on_in_press)
        self._in_canvas.bind("<B1-Motion>", self._on_in_drag)
        self._in_canvas.bind("<ButtonRelease-1>", self._on_release)

        self._out_canvas = tk.Canvas(self, width=w, height=MARKER_H + 8, highlightthickness=0)
        self._out_canvas.pack(pady=(6, 0))
        self._out_canvas.bind("<Button-1>", self._on_out_press)
        self._out_canvas.bind("<B1-Motion>", self._on_out_drag)
        self._out_canvas.bind("<ButtonRelease-1>", self._on_release)

        spin_row = ttk.Frame(self)
        spin_row.pack(fill=tk.X, pady=(6, 0))
        self._spins: dict[str, tk.Spinbox] = {}
        for field, label, lo, hi, inc in (
            ("in_black", "Black", 0.0, 254.0, 1.0),
            ("gamma", "Gamma", 0.1, 10.0, 0.1),
            ("in_white", "White", 1.0, 255.0, 1.0),
            ("out_black", "Out lo", 0.0, 255.0, 1.0),
            ("out_white", "Out hi", 0.0, 255.0, 1.0),
        ):
            ttk.Label(spin_row, text=label).pack(side=tk.LEFT, padx=(0, 2))
            spin = tk.Spinbox(
                spin_row, from_=lo, to=hi, increment=inc, width=5, command=self._on_spin_change
            )
            spin.bind("<Return>", lambda _e: self._on_spin_change())
            spin.bind("<FocusOut>", lambda _e: self._on_spin_change())
            spin.pack(side=tk.LEFT, padx=(0, 6))
            self._spins[field] = spin

        self.sync_from_params()

    # --- state plumbing ---

    def _levels(self) -> LevelsChannel:
        return self._get_levels(self._channel.get())

    def _put(self, **changes: float) -> None:
        """Replace the current channel's LevelsChannel and propagate everywhere."""
        new = replace(self._levels(), **changes)
        self._set_levels(self._channel.get(), new)
        self._on_change()
        self._redraw(new)
        self._sync_spins(new)

    def sync_from_params(self) -> None:
        """Redraw everything from the current channel (channel switch, undo, Apply)."""
        ch = self._levels()
        self._redraw_histogram()
        self._redraw(ch)
        self._sync_spins(ch)

    # --- drawing ---

    def _redraw_histogram(self) -> None:
        self._hist_canvas.delete("all")
        self._hist_photo = None
        hists = self._get_input_histograms()
        if hists is None:
            return
        lum, rgb = hists
        key = _HIST_CHANNEL[self._channel.get()]
        rendered = render_histogram(lum, rgb, {key}, log_scale=False, size=STRIP_SIZE)
        self._hist_photo = ImageTk.PhotoImage(rendered)
        self._hist_canvas.create_image(0, 0, anchor=tk.NW, image=self._hist_photo)

    def _redraw(self, ch: LevelsChannel) -> None:
        c = self._in_canvas
        c.delete("all")
        for x, fill in (
            (float(ch.in_black), "#000000"),
            (gamma_to_mid(ch.in_black, ch.in_white, ch.gamma), "#888888"),
            (float(ch.in_white), "#ffffff"),
        ):
            c.create_polygon(
                x - 5, MARKER_H - 1, x + 5, MARKER_H - 1, x, 1, fill=fill, outline="#444444"
            )
        o = self._out_canvas
        o.delete("all")
        if self._grad_photo is None:
            grad = Image.new("L", (256, 8))
            grad.putdata(list(range(256)) * 8)
            self._grad_photo = ImageTk.PhotoImage(grad.convert("RGB"))
        o.create_image(0, 0, anchor=tk.NW, image=self._grad_photo)
        for x, fill in ((float(ch.out_black), "#000000"), (float(ch.out_white), "#ffffff")):
            o.create_polygon(
                x - 5, MARKER_H + 7, x + 5, MARKER_H + 7, x, 9, fill=fill, outline="#444444"
            )

    # --- input marker interaction ---

    def _on_in_press(self, event: "tk.Event[tk.Canvas] | object") -> None:
        ch = self._levels()
        mid_x = gamma_to_mid(ch.in_black, ch.in_white, ch.gamma)
        candidates = {"black": float(ch.in_black), "mid": mid_x, "white": float(ch.in_white)}
        x = getattr(event, "x", 0)
        self._drag = min(candidates, key=lambda k: abs(candidates[k] - x))
        self._on_in_drag(event)

    def _on_in_drag(self, event: "tk.Event[tk.Canvas] | object") -> None:
        if self._drag is None:
            return
        ch = self._levels()
        x = min(255, max(0, int(getattr(event, "x", 0))))
        if self._drag == "black":
            self._put(in_black=min(x, ch.in_white - 1))
        elif self._drag == "white":
            self._put(in_white=max(x, ch.in_black + 1))
        elif self._drag == "mid":
            self._put(gamma=round(mid_to_gamma(ch.in_black, ch.in_white, x), 2))

    def _on_out_press(self, event: "tk.Event[tk.Canvas] | object") -> None:
        ch = self._levels()
        candidates = {"out_black": float(ch.out_black), "out_white": float(ch.out_white)}
        x = getattr(event, "x", 0)
        self._drag = min(candidates, key=lambda k: abs(candidates[k] - x))
        self._on_out_drag(event)

    def _on_out_drag(self, event: "tk.Event[tk.Canvas] | object") -> None:
        if self._drag is None:
            return
        ch = self._levels()
        x = min(255, max(0, int(getattr(event, "x", 0))))
        if self._drag == "out_black":
            self._put(out_black=min(x, ch.out_white))
        elif self._drag == "out_white":
            self._put(out_white=max(x, ch.out_black))

    def _on_release(self, _event: object) -> None:
        self._drag = None

    # --- spinboxes / auto ---

    def _sync_spins(self, ch: LevelsChannel) -> None:
        self._updating = True
        for field in ("in_black", "gamma", "in_white", "out_black", "out_white"):
            spin = self._spins[field]
            spin.delete(0, tk.END)
            val = getattr(ch, field)
            spin.insert(0, f"{val:.2f}" if field == "gamma" else str(val))
        self._updating = False

    def _on_spin_change(self) -> None:
        if self._updating:
            return
        try:
            in_black = int(float(self._spins["in_black"].get()))
            gamma = float(self._spins["gamma"].get())
            in_white = int(float(self._spins["in_white"].get()))
            out_black = int(float(self._spins["out_black"].get()))
            out_white = int(float(self._spins["out_white"].get()))
        except ValueError:
            return  # ignore partial/invalid input; the next valid edit wins
        in_black = min(254, max(0, in_black))
        in_white = min(255, max(in_black + 1, in_white))
        gamma = min(10.0, max(0.1, gamma))
        out_black = min(255, max(0, out_black))
        out_white = min(255, max(0, out_white))
        self._put(
            in_black=in_black,
            gamma=gamma,
            in_white=in_white,
            out_black=out_black,
            out_white=out_white,
        )

    def _on_auto(self) -> None:
        """Auto-levels: per-channel black/white from the input histogram."""
        hists = self._get_input_histograms()
        if hists is None:
            return
        r, g, b = auto_levels(hists[1])
        for key, ch in (("r", r), ("g", g), ("b", b)):
            self._set_levels(key, ch)
        self._on_change()
        self.sync_from_params()
```

Note on event typing: handlers accept the real `tk.Event` at runtime; the
tests drive them with `types.SimpleNamespace(x=...)`, hence the `getattr(event,
"x", 0)` access and the union annotation. If mypy complains about the string
annotation form, use `object` for the event parameter and keep the `getattr`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v`
Expected: all PASS (5 new + 5 existing)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/levels_tab.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/levels_tab.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): LevelsTab widget with draggable markers and Auto

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Dialog wiring — Levels tab, params plumbing, input-histogram cache

**Files:** Modify `src/pxv/enhancement_dialog.py`; modify `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_enhancement_dialog_ui.py`, first extend `_make_app`'s image_model line to include a working image (the cache and Levels strip need one):

```python
        image_model=types.SimpleNamespace(
            keep_metadata=False,
            metadata=None,
            working_image=Image.new("RGB", (8, 8), (120, 90, 200)),
        ),
```

Then append:

```python
def test_dialog_has_levels_tab_wired_to_params() -> None:
    from pxv.enhancement_dialog import EnhancementDialog
    from pxv.tone import LevelsChannel

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        tabs = [dlg._notebook.tab(tab_id, "text") for tab_id in dlg._notebook.tabs()]
        assert tabs == ["Sliders", "Levels"]
        # Widget edits land in the app params...
        dlg.levels_tab._put(in_black=12)
        assert app.enhancement_params.levels_master.in_black == 12
        # ...and external param changes flow back on sync (undo path).
        app.enhancement_params.levels_master = LevelsChannel(in_black=33)
        dlg.sync_sliders_from_params()
        assert dlg.levels_tab._spins["in_black"].get() == "33"
        dlg._on_close()
    finally:
        root.destroy()


def test_dialog_levels_edit_schedules_debounced_refresh() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        dlg.levels_tab._put(in_black=20)
        assert app.refresh_calls == []  # not synchronous — debounced
        assert dlg._refresh_after_id is not None  # 30ms timer armed
        dlg._do_refresh()  # fire deterministically (avoids Xvfb timing flake)
        assert app.refresh_calls == [True]
        dlg._on_close()
    finally:
        root.destroy()


def test_dialog_input_histogram_cache_keyed_on_working_image() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        first = dlg._input_histograms()
        assert first is not None
        assert dlg._input_histograms() is first  # cached: same object back
        app.image_model.working_image = Image.new("RGB", (8, 8), (1, 2, 3))
        second = dlg._input_histograms()
        assert second is not None and second is not first  # cache invalidated
        app.image_model.working_image = None
        assert dlg._input_histograms() is None
        dlg._on_close()
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v`
Expected: 3 new tests FAIL (no Levels tab / no `_input_histograms`)

- [ ] **Step 3: Modify `src/pxv/enhancement_dialog.py`**

(a) Imports — add after the existing `from pxv.histogram_panel import HistogramPanel`:

```python
from pxv.histogram_panel import compute_histograms
from pxv.levels_tab import LevelsTab
```

and to the TYPE_CHECKING block:

```python
    from pxv.tone import LevelsChannel
```

Also add `from typing import TYPE_CHECKING, cast` (replacing the bare TYPE_CHECKING import).

(b) In `__init__`, after `self._scales: dict[str, tk.Scale] = {}` add:

```python
        # Cache of (working_image object, (lum, rgb)) for the Levels strip.
        self._input_hist_cache: tuple[object, tuple[list[int], list[int]]] | None = None
```

(c) In `_build_ui`, after the `color_frame` block (still inside the method, before `btn_frame`), add:

```python
        self.levels_tab = LevelsTab(
            self._notebook,
            get_levels=self._get_levels,
            set_levels=self._set_levels,
            get_input_histograms=self._input_histograms,
            on_change=self._schedule_refresh,
        )
        self._notebook.add(self.levels_tab, text="Levels")
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
```

Update the AIDEV-NOTE above the notebook to say Sliders+Levels today, Curves in a later phase.

(d) Refactor the debounce tail of `_on_slider_change` into a shared method — `_on_slider_change` becomes:

```python
    def _on_slider_change(self, attr: str) -> None:
        """Called when any slider moves. Debounces the display refresh."""
        if self._updating_sliders:
            return

        # Update the corresponding param
        val = self._slider_vars[attr].get()
        setattr(self.app.enhancement_params, attr, val)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Debounce the display refresh (shared by sliders and levels edits)."""
        if self._refresh_after_id is not None:
            self.after_cancel(self._refresh_after_id)
        self._refresh_after_id = self.after(30, self._do_refresh)
```

(e) Add the plumbing methods after `update_histogram`:

```python
    _LEVELS_ATTRS = {
        "master": "levels_master",
        "r": "levels_r",
        "g": "levels_g",
        "b": "levels_b",
    }

    def _get_levels(self, key: str) -> LevelsChannel:
        return cast("LevelsChannel", getattr(self.app.enhancement_params, self._LEVELS_ATTRS[key]))

    def _set_levels(self, key: str, value: LevelsChannel) -> None:
        setattr(self.app.enhancement_params, self._LEVELS_ATTRS[key], value)

    def _input_histograms(self) -> tuple[list[int], list[int]] | None:
        """Histograms of the working image (input side of the pipeline), cached.

        AIDEV-NOTE: Levels markers operate on INPUT values, so the strip shows
        the pre-enhancement working image, not the live preview (which would
        feed back while dragging). The cache keys on the working_image object
        identity — every mutation (crop/rotate/Apply/undo) replaces the object.
        """
        img = self.app.image_model.working_image
        if img is None:
            return None
        if self._input_hist_cache is None or self._input_hist_cache[0] is not img:
            self._input_hist_cache = (img, compute_histograms(img))
        return self._input_hist_cache[1]

    def _on_tab_changed(self, _event: tk.Event) -> None:
        """Refresh the Levels strip when its tab becomes visible (image may have changed)."""
        if self._notebook.select() == str(self.levels_tab):
            self.levels_tab.sync_from_params()
```

(f) Extend `sync_sliders_from_params` — append inside the method, after the loop but before the guard reset is fine too; keep the guard semantics:

```python
        self._updating_sliders = True
        params = self.app.enhancement_params
        for attr, var in self._slider_vars.items():
            val = getattr(params, attr)
            var.set(val)
        self._updating_sliders = False
        self.levels_tab.sync_from_params()
```

(Also update its docstring first line to: `"""Sync all tabs' controls from the current EnhancementParams."""`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py tests/test_dialog_focus.py -v`
Expected: all PASS (13 + 2). Note: `test_dialog_focus.py`'s `_make_app` double lacks `working_image`; if `EnhancementDialog` construction now fails there, that double needs `working_image=None` added to its `image_model` SimpleNamespace — that is an allowed edit, mirroring this file's `_make_app`.

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/enhancement_dialog.py tests/test_enhancement_dialog_ui.py tests/test_dialog_focus.py
uv run mypy src/pxv
git add src/pxv/enhancement_dialog.py tests/test_enhancement_dialog_ui.py tests/test_dialog_focus.py
git commit -m "feat(enhance): wire Levels tab into the dialog with input-histogram cache

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Full-suite verification + smoke

**Files:** none (verification only)

- [ ] **Step 1: Full suite under a display**

```bash
DISPLAY=:99 uv run pytest
```
Expected: all pass (207 from Phase 1 + 25 new = 232), 0 failures.

- [ ] **Step 2: Lint + typecheck**

```bash
uv run ruff format --check src tests
uv run mypy src/pxv
```
Expected: no reformats, mypy clean.

- [ ] **Step 3: Manual smoke under Xvfb**

Construct the app the way `pxv.main` does (root + FileList + PxvApp + load_current — see Phase 1's smoke), open the enhancement dialog, then:
- select the Levels tab via `dlg._notebook.select(dlg.levels_tab)` and `root.update()`;
- drive a black-point drag (`dlg.levels_tab._on_in_press/_on_in_drag` with SimpleNamespace(x=...)), pump the loop ~120ms, and assert `app.enhancement_params.levels_master.in_black` changed and the top histogram `_photo` object changed (preview followed);
- click Auto (`dlg.levels_tab._on_auto()`) on a noise image and assert at least one of `levels_r/g/b` is non-identity;
- verify Apply: `dlg._on_apply()` bakes and `app.enhancement_params.is_identity()` is True after.
Report exact results. Clean up any temp image.

---

## Out of scope (later phases)

- Curves tab, spline math, curve_editor.py, Equalize/Invert (Phase 3)
- Eyedroppers/pick mode, Compare button (Phase 4)
- README/help/CHANGELOG updates (land with the final phase)
