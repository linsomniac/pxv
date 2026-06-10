# Curves Tab (Phase 3 of Histogram/Levels/Curves) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an xv-style Curves tab — a canvas spline editor with histogram backdrop, master + R/G/B channels, Equalize/Invert/Reset — composed into the existing single-LUT pipeline pass; plus three small carried review items from Phase 2.

**Architecture:** `tone.py` gains `CurvePoints`/`IDENTITY_CURVE`/`curve_lut` (Fritsch–Butland monotone cubic — shape-preserving, no overshoot, solarize allowed) and `equalize_curve` (CDF-sampled editable control points). `EnhancementParams` gains four immutable curve tuples composing after levels: base → master levels → channel levels → master curve → channel curve. New `curve_editor.py` widget (callback-decoupled like `LevelsTab`); the dialog adds the Curves tab and generalizes tab-change syncing.

**Tech Stack:** Python 3.10+, Pillow only, tkinter/ttk, pytest, uv, ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-06-10-histogram-levels-curves-design.md` · **Branch:** `histograms` (Phase 2 merged through `e470d50`).

---

## Environment notes for the executor

- Pure tests: `uv run pytest <file> -v`. Gated tests: Xvfb already on :99 → `DISPLAY=:99 uv run pytest <file> -v`.
- After writing Python: `uv run ruff format <files>`, `uv run mypy src/pxv` (strict).
- Never remove existing `AIDEV-NOTE` comments. Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/tone.py` | modify | CurvePoints, IDENTITY_CURVE, curve_lut, equalize_curve |
| `src/pxv/enhancements.py` | modify | Four curve fields; curves in the LUT composition |
| `src/pxv/curve_editor.py` | create | CurveEditor widget (canvas spline editor + buttons) |
| `src/pxv/enhancement_dialog.py` | modify | Curves tab wiring; generalized tab-change sync |
| `src/pxv/levels_tab.py` | modify | Carried items: Auto preserves gamma/output; TclError guard; inversion AIDEV-NOTE |
| `tests/test_tone.py` | modify | Curve math tests |
| `tests/test_enhancements.py` | modify | Params/pipeline curve tests + resolution-independence pin |
| `tests/test_enhancement_dialog_ui.py` | modify | Gated CurveEditor + dialog tests |

---

### Task 1: `tone.py` — `CurvePoints` + `curve_lut`

**Files:** Modify `src/pxv/tone.py`, modify `tests/test_tone.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tone.py` (extend the tone import with `IDENTITY_CURVE, curve_lut`):

```python
def test_curve_lut_identity() -> None:
    assert curve_lut(IDENTITY_CURVE) == IDENTITY


def test_curve_lut_two_point_inversion() -> None:
    lut = curve_lut(((0, 255), (255, 0)))
    assert lut == [255 - i for i in range(256)]


def test_curve_lut_s_curve_monotone_no_overshoot() -> None:
    lut = curve_lut(((0, 0), (64, 16), (192, 239), (255, 255)))
    assert lut[0] == 0 and lut[255] == 255
    assert lut[64] == 16 and lut[192] == 239  # interpolant passes through points
    assert all(lut[i + 1] >= lut[i] for i in range(255))  # no overshoot wiggles


def test_curve_lut_solarize_allowed() -> None:
    lut = curve_lut(((0, 0), (128, 255), (255, 0)))
    assert lut[0] == 0 and lut[128] == 255 and lut[255] == 0
    assert all(lut[i + 1] >= lut[i] for i in range(127))  # rises to the peak
    assert all(lut[i + 1] <= lut[i] for i in range(128, 255))  # falls after it


def test_curve_lut_flat_extension_outside_x_range() -> None:
    lut = curve_lut(((50, 100), (200, 150)))
    assert lut[0] == 100 and lut[49] == 100
    assert lut[201] == 150 and lut[255] == 150


def test_curve_lut_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        curve_lut(((0, 0),))
    with pytest.raises(ValueError):
        curve_lut(((0, 0), (0, 255)))  # x not strictly increasing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tone.py -v` → new tests FAIL (ImportError)

- [ ] **Step 3: Write the implementation**

Append to `src/pxv/tone.py`:

```python
CurvePoints = tuple[tuple[int, int], ...]
IDENTITY_CURVE: CurvePoints = ((0, 0), (255, 255))


def curve_lut(points: CurvePoints) -> list[int]:
    """256-entry LUT through control points via monotone cubic interpolation.

    x must be strictly increasing; y is free in 0-255, so non-monotone curves
    (solarize) are allowed. Outside the x range the LUT extends flat.

    AIDEV-NOTE: Fritsch–Butland tangents — zero at local extrema, weighted
    harmonic mean elsewhere — keep every segment monotone between its control
    points (|m| <= 3|d| condition), which is what prevents overshoot. Keep
    this property: the curve editor promises "no wiggles between handles".
    """
    if len(points) < 2:
        raise ValueError("curve needs at least 2 points")
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        raise ValueError("curve x values must be strictly increasing")

    n = len(points)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]

    m = [0.0] * n
    m[0] = d[0]
    m[n - 1] = d[n - 2]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

    lut: list[int] = []
    seg = 0
    for x in range(256):
        if x <= xs[0]:
            y = ys[0]
        elif x >= xs[-1]:
            y = ys[-1]
        else:
            while xs[seg + 1] < x:
                seg += 1
            t = (x - xs[seg]) / h[seg]
            t2 = t * t
            t3 = t2 * t
            y = (
                (2 * t3 - 3 * t2 + 1) * ys[seg]
                + (t3 - 2 * t2 + t) * h[seg] * m[seg]
                + (-2 * t3 + 3 * t2) * ys[seg + 1]
                + (t3 - t2) * h[seg] * m[seg + 1]
            )
        lut.append(max(0, min(255, int(y + 0.5))))
    return lut
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tone.py -v` → 21 PASS (15 existing + 6 new)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/tone.py tests/test_tone.py
uv run mypy src/pxv
git add src/pxv/tone.py tests/test_tone.py
git commit -m "feat(enhance): monotone cubic curve LUT

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `tone.py` — `equalize_curve`

**Files:** Modify `src/pxv/tone.py`, modify `tests/test_tone.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tone.py` (add `equalize_curve` to the import):

```python
def test_equalize_curve_two_spike_histogram() -> None:
    hist = [0] * 256
    hist[50] = 100
    hist[200] = 100
    points = list(equalize_curve(hist))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    assert xs[0] == 0 and xs[-1] == 255
    assert all(xs[i + 1] > xs[i] for i in range(len(xs) - 1))
    assert ys[0] == 0 and ys[-1] == 255
    # Between the spikes the CDF plateaus at 0.5 -> y == 128.
    assert all(y == 128 for x, y in points if 64 <= x <= 191)


def test_equalize_curve_flat_histogram_is_near_identity() -> None:
    points = equalize_curve([100] * 256)
    assert all(abs(y - x) <= 2 for x, y in points)


def test_equalize_curve_empty_histogram_is_identity() -> None:
    assert equalize_curve([0] * 256) == IDENTITY_CURVE


def test_equalize_curve_feeds_curve_lut() -> None:
    hist = [0] * 256
    hist[50] = 100
    hist[200] = 100
    lut = curve_lut(equalize_curve(hist))
    assert len(lut) == 256 and all(0 <= v <= 255 for v in lut)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tone.py -v` → ImportError

- [ ] **Step 3: Write the implementation**

Append to `src/pxv/tone.py`:

```python
def equalize_curve(hist_lum: list[int], n_points: int = 9) -> CurvePoints:
    """Histogram-equalization master curve: the CDF sampled at even inputs.

    Returns ordinary, editable control points — equalization stays
    non-destructive and tweakable (beyond xv). Empty histogram -> identity.
    """
    total = sum(hist_lum)
    if total == 0:
        return IDENTITY_CURVE
    cdf: list[float] = []
    acc = 0
    for count in hist_lum:
        acc += count
        cdf.append(acc / total)
    points: list[tuple[int, int]] = []
    for k in range(n_points):
        x = round(k * 255 / (n_points - 1))
        points.append((x, round(255 * cdf[x])))
    return tuple(points)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tone.py -v` → 25 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/tone.py tests/test_tone.py
uv run mypy src/pxv
git add src/pxv/tone.py tests/test_tone.py
git commit -m "feat(enhance): editable histogram-equalization curve

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `EnhancementParams` curve fields + pipeline composition

**Files:** Modify `src/pxv/enhancements.py`, modify `tests/test_enhancements.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancements.py` (extend the tone import with `IDENTITY_CURVE`):

```python
def test_params_identity_covers_curves() -> None:
    p = EnhancementParams()
    assert p.is_identity()
    p.curve_g = ((0, 0), (128, 200), (255, 255))
    assert not p.is_identity()
    p.reset()
    assert p.is_identity()
    assert p.curve_g == IDENTITY_CURVE


def test_apply_enhancements_master_curve_inverts() -> None:
    img = Image.new("RGB", (2, 2), (10, 100, 200))
    p = EnhancementParams()
    p.curve_master = ((0, 255), (255, 0))
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0)) == (245, 155, 55)


def test_apply_enhancements_levels_before_curves() -> None:
    # Levels map 128 -> 50 (out_white=100); the master curve's flat-200 floor
    # then lifts everything to 200. Reversed order would curve first
    # (128 stays under the flat) then compress 200 -> 78. Pins the spec order:
    # levels before curves.
    img = Image.new("RGB", (1, 1), (128, 128, 128))
    p = EnhancementParams()
    p.levels_master = LevelsChannel(out_white=100)
    p.curve_master = ((0, 200), (255, 255))
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0))[0] >= 200


def test_apply_enhancements_lut_resolution_independent() -> None:
    # The whole tone stack is per-pixel: the same color must map identically
    # at any image size (this is why preview == save for LUT-only params).
    p = EnhancementParams()
    p.levels_master = LevelsChannel(in_black=20, gamma=1.7)
    p.curve_r = ((0, 0), (100, 180), (255, 255))
    small = apply_enhancements(Image.new("RGB", (2, 2), (90, 140, 30)), p)
    large = apply_enhancements(Image.new("RGB", (64, 64), (90, 140, 30)), p)
    assert small.getpixel((0, 0)) == large.getpixel((32, 32))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enhancements.py -v` → new tests FAIL (AttributeError: curve_g / curve_master)

- [ ] **Step 3: Modify `src/pxv/enhancements.py`**

(a) Extend the tone import:

```python
from pxv.tone import (
    IDENTITY_CURVE,
    CurvePoints,
    LevelsChannel,
    compose_luts,
    curve_lut,
    levels_lut,
)
```

(b) Add four fields to `EnhancementParams` after `levels_b`:

```python
    curve_master: CurvePoints = IDENTITY_CURVE
    curve_r: CurvePoints = IDENTITY_CURVE
    curve_g: CurvePoints = IDENTITY_CURVE
    curve_b: CurvePoints = IDENTITY_CURVE
```

(c) `is_identity()` — add to the conjunction:

```python
            and self.curve_master == IDENTITY_CURVE
            and self.curve_r == IDENTITY_CURVE
            and self.curve_g == IDENTITY_CURVE
            and self.curve_b == IDENTITY_CURVE
```

(d) `reset()` — append:

```python
        self.curve_master = IDENTITY_CURVE
        self.curve_r = IDENTITY_CURVE
        self.curve_g = IDENTITY_CURVE
        self.curve_b = IDENTITY_CURVE
```

(e) In `apply_enhancements` step 4, generalize the levels block to the full
tone stack. Replace from `levels_active = not (` through `result = result.point(lut)` with:

```python
    levels_active = not (
        params.levels_master.is_identity()
        and params.levels_r.is_identity()
        and params.levels_g.is_identity()
        and params.levels_b.is_identity()
    )
    curves_active = not (
        params.curve_master == IDENTITY_CURVE
        and params.curve_r == IDENTITY_CURVE
        and params.curve_g == IDENTITY_CURVE
        and params.curve_b == IDENTITY_CURVE
    )
    needs_lut = (
        params.brightness != 1.0
        or params.gamma != 1.0
        or params.r_balance != 1.0
        or params.g_balance != 1.0
        or params.b_balance != 1.0
        or levels_active
        or curves_active
    )
    if needs_lut:
        base = _build_lut(
            params.brightness, params.gamma, params.r_balance, params.g_balance, params.b_balance
        )
        if levels_active or curves_active:
            # AIDEV-NOTE: Fixed composition order per the 2026-06-10 design:
            # base (brightness+gamma+balance) -> master levels -> channel
            # levels -> master curve -> channel curve.
            master_lv = levels_lut(params.levels_master)
            master_cv = curve_lut(params.curve_master)
            lut: list[int] = []
            channel_tone = (
                (params.levels_r, params.curve_r),
                (params.levels_g, params.curve_g),
                (params.levels_b, params.curve_b),
            )
            for idx, (ch_lv, ch_cv) in enumerate(channel_tone):
                lut.extend(
                    compose_luts(
                        base[idx * 256 : (idx + 1) * 256],
                        master_lv,
                        levels_lut(ch_lv),
                        master_cv,
                        curve_lut(ch_cv),
                    )
                )
        else:
            lut = base
        result = result.point(lut)
```

Update the module docstring's pipeline line to `Combined LUT (brightness+gamma+RGB+levels+curves)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_enhancements.py tests/test_tone.py -v` → all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/enhancements.py tests/test_enhancements.py
uv run mypy src/pxv
git add src/pxv/enhancements.py tests/test_enhancements.py
git commit -m "feat(enhance): per-channel curves composed after levels in the LUT

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `curve_editor.py` widget

**Files:** Create `src/pxv/curve_editor.py`; modify `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enhancement_dialog_ui.py`:

```python
def _make_curve_editor(
    root: "tk.Tk",
) -> tuple[object, dict[str, object], list[bool]]:
    """CurveEditor wired to a dict-backed store — no app or dialog needed."""
    from pxv.curve_editor import CurveEditor
    from pxv.histogram_panel import compute_histograms
    from pxv.tone import IDENTITY_CURVE

    store: dict[str, tuple[tuple[int, int], ...]] = {
        key: IDENTITY_CURVE for key in ("master", "r", "g", "b")
    }
    changes: list[bool] = []
    hists = compute_histograms(Image.new("RGB", (16, 16), (10, 200, 60)))
    editor = CurveEditor(
        root,
        get_curve=store.__getitem__,
        set_curve=store.__setitem__,
        get_input_histograms=lambda: hists,
        on_change=lambda: changes.append(True),
    )
    return editor, store, changes


def test_curve_editor_builds_with_backdrop_and_identity() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        assert editor._hist_photo is not None
        assert store["master"] == ((0, 0), (255, 255))
    finally:
        root.destroy()


def test_curve_editor_click_adds_point_and_drag_moves_it() -> None:
    root = tk.Tk()
    try:
        editor, store, changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=64))  # empty area -> add
        assert len(store["master"]) == 3
        assert (128, 191) in store["master"]  # canvas y=64 -> value 255-64
        editor._on_drag(types.SimpleNamespace(x=140, y=55))
        assert (140, 200) in store["master"]
        editor._on_release(types.SimpleNamespace())
        assert changes
    finally:
        root.destroy()


def test_curve_editor_drag_clamps_x_between_neighbors_and_pins_endpoints() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=128))  # add mid point
        editor._on_drag(types.SimpleNamespace(x=300, y=128))  # past right endpoint
        xs = [p[0] for p in store["master"]]
        assert xs == sorted(xs) and xs[-1] == 255 and xs[1] == 254  # clamped
        editor._on_release(types.SimpleNamespace())
        # Endpoint: x pinned, y free.
        editor._on_press(types.SimpleNamespace(x=0, y=255))  # grab (0, 0)
        editor._on_drag(types.SimpleNamespace(x=80, y=200))
        assert store["master"][0] == (0, 55)  # x stayed 0, y moved
        editor._on_release(types.SimpleNamespace())
    finally:
        root.destroy()


def test_curve_editor_right_click_deletes_only_interior_points() -> None:
    root = tk.Tk()
    try:
        editor, store, _changes = _make_curve_editor(root)
        editor._on_press(types.SimpleNamespace(x=128, y=128))
        editor._on_release(types.SimpleNamespace())
        assert len(store["master"]) == 3
        editor._on_right_click(types.SimpleNamespace(x=128, y=128))
        assert len(store["master"]) == 2
        editor._on_right_click(types.SimpleNamespace(x=0, y=255))  # endpoint
        assert len(store["master"]) == 2  # endpoints undeletable
    finally:
        root.destroy()


def test_curve_editor_buttons() -> None:
    root = tk.Tk()
    try:
        editor, store, changes = _make_curve_editor(root)
        editor._on_invert()
        assert store["master"] == ((0, 255), (255, 0))
        editor._on_reset_curve()
        assert store["master"] == ((0, 0), (255, 255))
        editor._on_equalize()
        assert store["master"] != ((0, 0), (255, 255))  # CDF of the test image
        assert len(changes) >= 3
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → ModuleNotFoundError: pxv.curve_editor

- [ ] **Step 3: Write the implementation**

Create `src/pxv/curve_editor.py`:

```python
"""Curve editor widget: canvas spline editor with histogram backdrop.

AIDEV-NOTE: Pure math (curve_lut, equalize_curve) lives in tone.py; this is
only the Tk shell, decoupled via injected callbacks like LevelsTab. Canvas
coords map 1:1 to values (256x256 canvas): px = x, py = 255 - y.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import ImageTk

from pxv.histogram_panel import render_histogram
from pxv.tone import IDENTITY_CURVE, CurvePoints, curve_lut, equalize_curve

CURVE_SIZE = (256, 256)
MAX_POINTS = 16
HIT_RADIUS = 6
CHANNEL_KEYS = [("master", "RGB"), ("r", "R"), ("g", "G"), ("b", "B")]
_HIST_CHANNEL = {"master": "lum", "r": "r", "g": "g", "b": "b"}


class CurveEditor(ttk.Frame):
    """Spline curve editor: click adds, drag moves, right-click deletes."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_curve: Callable[[str], CurvePoints],
        set_curve: Callable[[str, CurvePoints], None],
        get_input_histograms: Callable[[], tuple[list[int], list[int]] | None],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=6)
        self._get_curve = get_curve
        self._set_curve = set_curve
        self._get_input_histograms = get_input_histograms
        self._on_change = on_change

        self._channel = tk.StringVar(value="master")
        self._drag_idx: int | None = None
        self._hist_photo: ImageTk.PhotoImage | None = None

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

        w, h = CURVE_SIZE
        self._canvas = tk.Canvas(self, width=w, height=h, bg="#181818", highlightthickness=0)
        self._canvas.pack(pady=(4, 0))
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Button-3>", self._on_right_click)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text="Equalize", command=self._on_equalize).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Invert", command=self._on_invert).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Reset Curve", command=self._on_reset_curve).pack(
            side=tk.LEFT, padx=2
        )

        self.sync_from_params()

    # --- state plumbing ---

    def _points(self) -> list[tuple[int, int]]:
        return list(self._get_curve(self._channel.get()))

    def _put(self, points: list[tuple[int, int]]) -> None:
        self._set_curve(self._channel.get(), tuple(points))
        self._on_change()
        self._redraw()

    def sync_from_params(self) -> None:
        """Redraw backdrop and curve from the current channel (switch/undo/Apply)."""
        self._redraw_backdrop()
        self._redraw()

    # --- drawing ---

    def _redraw_backdrop(self) -> None:
        self._hist_photo = None
        hists = self._get_input_histograms()
        if hists is None:
            return
        lum, rgb = hists
        key = _HIST_CHANNEL[self._channel.get()]
        rendered = render_histogram(lum, rgb, {key}, log_scale=False, size=CURVE_SIZE)
        self._hist_photo = ImageTk.PhotoImage(rendered)
        self._redraw()

    def _redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        if self._hist_photo is not None:
            c.create_image(0, 0, anchor=tk.NW, image=self._hist_photo)
        for q in (64, 128, 192):
            c.create_line(q, 0, q, 255, fill="#333333")
            c.create_line(0, q, 255, q, fill="#333333")
        points = self._points()
        lut = curve_lut(tuple(points))
        coords: list[int] = []
        for x in range(256):
            coords.extend((x, 255 - lut[x]))
        c.create_line(*coords, fill="#dddddd", width=1)
        for px, py in points:
            c.create_rectangle(
                px - 3, (255 - py) - 3, px + 3, (255 - py) + 3, fill="#ffffff", outline="#000000"
            )

    # --- interaction ---

    def _hit_index(self, x: int, y: int) -> int | None:
        """Index of the control point within HIT_RADIUS of canvas (x, y), or None."""
        points = self._points()
        best: tuple[float, int] | None = None
        for i, (px, py) in enumerate(points):
            dist = max(abs(px - x), abs((255 - py) - y))
            if dist <= HIT_RADIUS and (best is None or dist < best[0]):
                best = (dist, i)
        return None if best is None else best[1]

    def _on_press(self, event: object) -> None:
        x = min(255, max(0, int(getattr(event, "x", 0))))
        y = min(255, max(0, int(getattr(event, "y", 0))))
        idx = self._hit_index(x, y)
        if idx is None:
            points = self._points()
            if len(points) >= MAX_POINTS or any(abs(px - x) <= 2 for px, _py in points):
                return
            points.append((x, 255 - y))
            points.sort()
            idx = points.index((x, 255 - y))
            self._drag_idx = idx
            self._put(points)
        else:
            self._drag_idx = idx

    def _on_drag(self, event: object) -> None:
        if self._drag_idx is None:
            return
        points = self._points()
        i = self._drag_idx
        x = min(255, max(0, int(getattr(event, "x", 0))))
        y = min(255, max(0, int(getattr(event, "y", 0))))
        if i == 0:
            new_x = 0  # endpoints: x pinned, y free
        elif i == len(points) - 1:
            new_x = 255
        else:
            new_x = min(points[i + 1][0] - 1, max(points[i - 1][0] + 1, x))
        points[i] = (new_x, 255 - y)
        self._put(points)

    def _on_release(self, _event: object) -> None:
        self._drag_idx = None

    def _on_right_click(self, event: object) -> None:
        x = int(getattr(event, "x", 0))
        y = int(getattr(event, "y", 0))
        idx = self._hit_index(x, y)
        points = self._points()
        if idx is None or idx == 0 or idx == len(points) - 1:
            return
        del points[idx]
        self._put(points)

    # --- buttons ---

    def _on_equalize(self) -> None:
        """Set the MASTER curve from the input luminance CDF (editable afterward)."""
        hists = self._get_input_histograms()
        if hists is None:
            return
        self._set_curve("master", equalize_curve(hists[0]))
        self._channel.set("master")
        self._on_change()
        self.sync_from_params()

    def _on_invert(self) -> None:
        self._put([(0, 255), (255, 0)])

    def _on_reset_curve(self) -> None:
        self._put(list(IDENTITY_CURVE))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → all PASS (5 new + existing)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/curve_editor.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/curve_editor.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): CurveEditor widget with spline handles and Equalize/Invert

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Dialog wiring + carried Phase-2 review items

**Files:** Modify `src/pxv/enhancement_dialog.py`, `src/pxv/levels_tab.py`; modify `tests/test_enhancement_dialog_ui.py`.

- [ ] **Step 1: Write the failing tests**

First, update the existing Phase-2 assertion that the new tab will break: in
`test_dialog_has_levels_tab_wired_to_params`, change
`assert tabs == ["Sliders", "Levels"]` to `assert tabs[:2] == ["Sliders", "Levels"]`
(the new curves test below pins the exact full list).

Then append to `tests/test_enhancement_dialog_ui.py`:

```python
def test_dialog_has_curves_tab_wired_to_params() -> None:
    from pxv.enhancement_dialog import EnhancementDialog

    app, root = _make_app()
    try:
        dlg = EnhancementDialog(app)
        tabs = [dlg._notebook.tab(tab_id, "text") for tab_id in dlg._notebook.tabs()]
        assert tabs == ["Sliders", "Levels", "Curves"]
        dlg.curve_editor._put([(0, 0), (100, 180), (255, 255)])
        assert app.enhancement_params.curve_master == ((0, 0), (100, 180), (255, 255))
        # Sync back (undo path):
        app.enhancement_params.curve_master = ((0, 10), (255, 245))
        dlg.sync_sliders_from_params()  # must not raise; editor redraws
        assert dlg.curve_editor._points() == [(0, 10), (255, 245)]
        dlg._on_close()
    finally:
        root.destroy()


def test_levels_auto_preserves_user_gamma_and_output() -> None:
    from pxv.tone import LevelsChannel

    root = tk.Tk()
    try:
        tab, store, _changes = _make_levels_tab(root)
        store["r"] = LevelsChannel(gamma=2.0, out_black=10)
        tab._on_auto()
        assert store["r"].gamma == 2.0  # Auto only touches black/white points
        assert store["r"].out_black == 10
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py -v` → both FAIL

- [ ] **Step 3: Implement**

In `src/pxv/enhancement_dialog.py`:

(a) Imports: add `from pxv.curve_editor import CurveEditor`; extend the TYPE_CHECKING tone import to `from pxv.tone import CurvePoints, LevelsChannel`.

(b) In `_build_ui`, after the Levels tab add (before `btn_frame`):

```python
        self.curve_editor = CurveEditor(
            self._notebook,
            get_curve=self._get_curve,
            set_curve=self._set_curve,
            get_input_histograms=self._input_histograms,
            on_change=self._schedule_refresh,
        )
        self._notebook.add(self.curve_editor, text="Curves")
```

Update the notebook AIDEV-NOTE wording to "Sliders, Levels, and Curves tabs; eyedroppers/Compare arrive in Phase 4."

(c) Add curve plumbing next to the levels plumbing:

```python
    _CURVE_ATTRS = {
        "master": "curve_master",
        "r": "curve_r",
        "g": "curve_g",
        "b": "curve_b",
    }

    def _get_curve(self, key: str) -> CurvePoints:
        return cast("CurvePoints", getattr(self.app.enhancement_params, self._CURVE_ATTRS[key]))

    def _set_curve(self, key: str, value: CurvePoints) -> None:
        setattr(self.app.enhancement_params, self._CURVE_ATTRS[key], value)
```

(d) Generalize `_on_tab_changed`:

```python
    def _on_tab_changed(self, _event: tk.Event) -> None:
        """Resync the newly shown tone tab (the image may have changed since)."""
        selected = self._notebook.select()
        if selected == str(self.levels_tab):
            self.levels_tab.sync_from_params()
        elif selected == str(self.curve_editor):
            self.curve_editor.sync_from_params()
```

(e) `sync_sliders_from_params`: after `self.levels_tab.sync_from_params()` add `self.curve_editor.sync_from_params()`.

(f) `update_histogram`'s image-change resync: after `self.levels_tab.sync_from_params()` inside the `if current is not None and ...` block, also call `self.curve_editor.sync_from_params()` (the backdrop tracks the same input image).

In `src/pxv/levels_tab.py` (carried review items):

(g) `_on_auto` preserves user gamma/output — replace the set loop:

```python
        for key, ch in (("r", r), ("g", g), ("b", b)):
            current = self._get_levels(key)
            self._set_levels(
                key, replace(current, in_black=ch.in_black, in_white=ch.in_white)
            )
```

(h) `_on_spin_change`: change `except ValueError:` to `except (ValueError, tk.TclError):` (FocusOut during teardown can hit a destroyed Spinbox), and add above the out_black/out_white clamping lines:

```python
        # AIDEV-NOTE: Spinboxes deliberately allow out_black > out_white
        # (output inversion / negative effect — levels_lut supports it);
        # marker DRAGS clamp no-cross because accidental inversion while
        # dragging feels broken. Intentional asymmetry.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_enhancement_dialog_ui.py tests/test_dialog_focus.py -v` → all PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/enhancement_dialog.py src/pxv/levels_tab.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/enhancement_dialog.py src/pxv/levels_tab.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(enhance): wire Curves tab; Auto preserves gamma/output; teardown guard

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Full-suite verification + smoke

**Files:** none.

- [ ] **Step 1:** `DISPLAY=:99 uv run pytest` — expect 259 pass, 0 fail (238 + 21 new).
- [ ] **Step 2:** `uv run ruff format --check src tests` and `uv run mypy src/pxv` — clean.
- [ ] **Step 3:** Smoke under Xvfb (construct app per Phase 1/2 smoke): open dialog, select Curves tab, `_on_press`/`_on_drag` to add and move a point, pump 120ms, assert `app.enhancement_params.curve_master` changed and the top histogram `_photo` changed; `_on_equalize()` on a noise image → master curve non-identity; Apply → `is_identity()` True; undo → curve restored and editor shows it (`dlg.curve_editor._points()`). Report per-step PASS/FAIL; no code fixes.

---

## Out of scope (Phase 4)

- Eyedroppers / canvas pick mode, Compare button
- README/help/CHANGELOG updates (land with Phase 4)
