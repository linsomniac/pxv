# Histogram, Levels & Curves in the Enhancement Dialog — Design

**Date:** 2026-06-10
**Ideas:** Ideas.md honorable mention ("A histogram (and levels/curves) in the enhancement dialog — also classic xv.")

## Background

The Enhancements dialog today is ten sliders in two LabelFrames
(`enhancement_dialog.py`) driving `EnhancementParams` through a debounced live
preview; Apply bakes the params into `working_image` and resets the sliders
(undoable via the history stack). The pipeline (`enhancements.py`) already
merges brightness, gamma, and RGB balance into a single 768-entry LUT and one
`Image.point()` call.

Classic xv's ColEdit window offered spline-based transfer-curve editors (one
Intensity graph plus R/G/B graphs, each with gamma handles) but **never drew an
actual histogram**. This feature adds a live histogram, Photoshop/GIMP-style
levels, and xv-style curves — meeting xv on curves and exceeding it on
histogram-backed editing, eyedroppers, and editable equalization.

## Decisions (from brainstorming)

- **Full scope:** histogram display, levels, curves, plus beyond-xv extras
  (eyedroppers, histogram equalization, before/after compare).
- **Tabbed layout:** the existing dialog gains a persistent histogram panel on
  top and a `ttk.Notebook` below it with **Sliders / Levels / Curves** tabs.
  One window, scales to future tabs.
- **Master + per-channel:** both levels and curves operate on RGB (master) or
  individual R/G/B channels, matching xv's four graphs.
- **Histogram shows the post-enhancement image** — the same preview image the
  user sees, so every adjustment visibly reshapes the distribution.
- **Architecture: extend `EnhancementParams` and compose into the existing LUT
  pass** (Approach A from brainstorming). Levels and curves each reduce to a
  per-channel 256-entry LUT; they compose with the existing
  brightness/gamma/balance LUT into the *same single* `Image.point()` call.
  Still non-destructive until Apply; still zero new dependencies.
- **Immutability constraint:** `PxvApp.snapshot_state()` copies params with
  `dataclasses.replace()` — a **shallow** copy. Every new field is therefore
  immutable (frozen dataclass / tuples), so the existing snapshot pattern
  stays correct with no history changes.
- **Fixed LUT composition order** (documented, applied left to right):
  base (brightness·gamma·balance) → master levels → channel levels →
  master curve → channel curve. Any fixed order works since it is pure LUT
  composition; this one is chosen and documented with an AIDEV-NOTE.
- **Preview/save parity:** LUT ops are resolution-independent, so unlike
  blur/sharpen the levels/curves preview matches the full-resolution save
  exactly. The existing `get_save_image()` path needs no changes.
- **Known overlap accepted:** the Gamma slider and levels-gamma coexist; they
  compose harmlessly (xv had the same redundancy).

## Components

### `tone.py` (new, pure — no Tk)

```python
CurvePoints = tuple[tuple[int, int], ...]   # ((x, y), ...) x strictly increasing
IDENTITY_CURVE: CurvePoints = ((0, 0), (255, 255))

@dataclass(frozen=True)
class LevelsChannel:
    """Input/output levels for one channel. Defaults are identity."""
    in_black: int = 0
    in_white: int = 255
    gamma: float = 1.0
    out_black: int = 0
    out_white: int = 255

    def is_identity(self) -> bool: ...

def levels_lut(ch: LevelsChannel) -> list[int]:
    """256-entry LUT: out_lo + clamp((i-in_b)/(in_w-in_b))^(1/gamma) * (out_hi-out_lo)."""

def curve_lut(points: CurvePoints) -> list[int]:
    """256-entry LUT via shape-preserving monotone cubic (Fritsch–Carlson/PCHIP)
    interpolation. x must be strictly increasing; y is free in 0–255, so
    non-monotone curves (solarize) are allowed — the interpolant just never
    overshoots between control points."""

def compose_luts(*luts: list[int]) -> list[int]:
    """Compose left-to-right: result[i] = last(...(first[i]))."""

def auto_levels(hist_rgb: list[int], clip_percent: float = 0.5) -> tuple[LevelsChannel, LevelsChannel, LevelsChannel]:
    """Per-channel black/white points clipping clip_percent% of pixels per end.
    Takes the 768-entry Image.histogram() of the working image."""

def equalize_curve(hist_lum: list[int], n_points: int = 9) -> CurvePoints:
    """Sample the luminance CDF at evenly spaced inputs to produce master-curve
    control points. Result is an ordinary editable curve — equalization stays
    non-destructive and tweakable (beyond xv)."""
```

~40 lines of spline math, all unit-testable without a display.

### `enhancements.py` — changes

`EnhancementParams` gains eight immutable fields:

```python
levels_master: LevelsChannel = LevelsChannel()
levels_r: LevelsChannel = LevelsChannel()
levels_g: LevelsChannel = LevelsChannel()
levels_b: LevelsChannel = LevelsChannel()
curve_master: CurvePoints = IDENTITY_CURVE
curve_r: CurvePoints = IDENTITY_CURVE
curve_g: CurvePoints = IDENTITY_CURVE
curve_b: CurvePoints = IDENTITY_CURVE
```

(Frozen-dataclass and tuple defaults are immutable, so plain defaults are fine
— no `default_factory` needed.) `is_identity()` and `reset()` extend to cover
them. In `apply_enhancements`, the step-4 LUT pass extends its `needs_lut`
gate and builds the final per-channel LUT with `compose_luts(base_ch,
levels_master, levels_ch, curve_master, curve_ch)` — still one
`Image.point()` call. Pipeline order is otherwise unchanged:
Contrast → Saturation → Hue → combined LUT → Blur → Sharpen.

### `histogram_panel.py` (new)

Pure render + widget, split like `canvas_view.py`:

- `compute_histograms(img) -> (lum: list[int], rgb: list[int])` — one
  `convert("L").histogram()` plus one `Image.histogram()` call (C-level,
  ~1–2 ms at preview resolution).
- `render_histogram(lum, rgb, channels, log_scale, size) -> Image.Image` —
  draws filled, alpha-blended channel overlays into a PIL image. Rendering via
  PIL (then one `ImageTk.PhotoImage` canvas item) avoids churning ~1000 Tk
  canvas items per refresh.
- `HistogramPanel(ttk.Frame)` — 256×100 canvas, channel toggle buttons
  (Lum/R/G/B), log-scale checkbox, clipping readouts (% of pixels at 0 and
  255). Public: `update_from_image(img: Image.Image | None)`.

**Feed:** `PxvApp.refresh_display()` and `_update_display()` each gain one
hook after computing `display_img`: if the enhancement dialog is open, call
`dialog.update_histogram(display_img)`. The dialog requests an initial
`refresh_display()` when opened. AIDEV-NOTE: for transparent images the
display image is composited onto the background color, so background pixels
contribute to the histogram — accepted, since the decision is "histogram of
what you see."

### `curve_editor.py` (new widget)

`CurveEditor(ttk.Frame)`: a 256×256 `tk.Canvas` with a dimmed histogram
backdrop, quarter grid, the sampled spline polyline, and square drag handles.

- Click empty space → add point (max 16, x kept strictly increasing, rejected
  within ±2 of an existing x). Drag handle → move (x clamped between
  neighbors; endpoint x pinned at 0/255, y free — output clipping). 
  Right-click a non-endpoint handle → delete.
- Channel selector (RGB/R/G/B) switches which curve is shown/edited.
- Buttons: **Equalize** (sets the master curve from `equalize_curve`),
  **Invert** (sets the *current channel's* curve to `((0,255),(255,0))`),
  **Reset Curve** (identity for the current channel).
- Constructor takes `get_points`/`set_points`/`on_change` callbacks; the
  widget never touches `EnhancementParams` directly (testable in isolation).

### Levels tab (inside `enhancement_dialog.py`)

- Channel selector (RGB/R/G/B).
- Enlarged single-channel histogram strip with three draggable input markers
  (black ▲, gamma ◆, white ▲) below it, plus an output gradient bar with two
  markers. Spinboxes stay synced with the markers (drag or type).
- Marker constraints: `in_black ≤ in_white − 1`; gamma marker positions
  itself proportionally between them.
- **Auto** button → `auto_levels()` on the *working* image's histogram, sets
  per-channel black/white points.
- **Eyedroppers** (black / gray / white): arming one puts the main canvas
  into pick mode; the next click samples the **working image** (levels map
  input values, so pre-enhancement pixels are the right source). Black sets
  each channel's `in_black` to the sampled channel value; white sets
  `in_white`; gray sets per-channel `gamma` so the sampled pixel becomes
  neutral. Escape or a second button press cancels.

### `canvas_view.py` — pick-mode support

- New pure function `canvas_point_to_image_xy(point, working_size,
  display_size, canvas_size, zoom)` — the single-point analog of
  `selection_to_image_box`, unit-testable the same way.
- `CanvasView` gains `set_pick_callback(cb | None)`; while set, `_on_press`
  consumes the click (no rubber-band), maps it through the new function, and
  invokes the callback with image coords (or None for a miss). Cursor switches
  to `tcross` while armed.

### Dialog restructure (`enhancement_dialog.py`)

Top-to-bottom: `HistogramPanel` → `ttk.Notebook` (Sliders tab keeps the
existing two LabelFrames verbatim; Levels tab; Curves tab) → button row
**Apply / Reset / Compare / Close**.

- **Compare** (before/after, beyond xv): `<ButtonPress>` sets an
  `app._compare_active` flag and refreshes — `refresh_display()` substitutes
  identity params while the flag is set — `<ButtonRelease>` clears it. The
  histogram follows the display, so it shows the unenhanced distribution
  during compare.
- **Apply** and **Reset** need no logic changes: they already operate on the
  whole params object, and `is_identity()` now covers levels/curves. Apply
  bakes *everything* (sliders + levels + curves) and returns all controls to
  identity — same semantics as today, and as xv.
- `sync_sliders_from_params()` extends to also redraw levels markers and the
  curve editor (renamed internally if useful, but the public name is kept —
  `app._restore_snapshot` calls it on undo/redo).

### History / undo

**No changes.** Snapshots already capture params; all new fields are
immutable so `replace()`'s shallow copy is safe. Undoing an Apply restores
levels and curves exactly as it restores sliders today.

## Phasing (each independently shippable)

1. **Histogram panel + tabbed restructure** — dialog reorg, `histogram_panel.py`, refresh hook.
2. **Levels** — `tone.py` (levels + auto-levels), Levels tab UI.
3. **Curves** — spline math, `curve_editor.py`, Curves tab, Equalize/Invert.
4. **Extras** — eyedroppers (pick mode), Compare button.

## Edge cases

- **No image loaded:** `update_histogram(None)` blanks the panel; eyedroppers
  and Auto are no-ops.
- **Transparent images:** histogram includes composited background pixels
  (accepted; AIDEV-NOTE at the hook).
- **Grayscale sources:** `working_image` is always RGB (model converts on
  load), so per-channel editing just works.
- **Degenerate levels:** UI clamps `in_white ≥ in_black + 1`; `levels_lut`
  also guards the division defensively.
- **Solarize-style curves:** allowed — x strictly increasing, y free; the
  monotone interpolant prevents overshoot but not non-monotone control data.
- **Equalize on a flat histogram:** CDF is linear → near-identity curve; fine.
- **Performance:** histogram + LUT rebuild ride the existing 30 ms debounce;
  both are ~1–2 ms at preview resolution. Dragging curve handles redraws only
  the editor canvas immediately and the preview on the debounce.
- **Compare while dragging:** Compare reads a flag at refresh time, so an
  in-flight debounce timer firing during compare still renders the compare
  state correctly (identity params).
- **Auto/eyedropper vs. other live adjustments:** Auto-levels and the
  eyedroppers sample the working image, but in the pipeline the levels LUT
  receives post-base-LUT values — so with non-identity
  brightness/gamma/balance the result is an approximation. At identity (the
  common case) it is exact, and the outcome is always hand-adjustable
  afterward; not worth re-deriving through the live params.

## Testing

Mirrors the suite's split: pure logic display-free; Tk wiring DISPLAY-gated
(Xvfb in CI per existing convention).

- **`tests/test_tone.py`** (new, pure): `levels_lut` endpoints, gamma, output
  range, degenerate-input guard; `curve_lut` identity through
  `IDENTITY_CURVE`, no overshoot on steep S-curves, solarize (non-monotone y),
  single-segment linearity; `compose_luts` identity/associativity;
  `auto_levels` clip math on synthetic histograms; `equalize_curve` on a
  known two-spike histogram; `LevelsChannel.is_identity`.
- **`tests/test_enhancements.py`** (extend): `is_identity()`/`reset()` with
  new fields; `apply_enhancements` with known levels/curves on tiny synthetic
  images against exact expected pixels; preview/save parity for LUT-only
  params (scaled-then-enhanced equals enhanced-then-scaled pixel sampling).
- **`tests/test_canvas_geometry.py`** (extend, pure): `canvas_point_to_image_xy`
  centering, zoom, out-of-image clicks — alongside the existing
  `selection_to_image_box` tests.
- **DISPLAY-gated** (pattern from existing dialog tests): dialog builds with
  three tabs and histogram; `sync_sliders_from_params` round-trip including
  curve/levels widgets after undo; curve editor add/drag/delete via
  `event_generate`; levels marker drag updates params; Apply bakes
  levels+curves and resets to identity; Compare press/release toggles the
  flag; eyedropper pick mode consumes the canvas click and disarms.

## Out of scope

- xv's hue *wedge* remapping (rotate a slice of the hue circle) — the global
  Hue slider stays; a wedge remap could be a future Color-tab idea.
- Colormap/palette cell editing (xv's 8-bit tools) — pxv's pipeline is RGB.
- Saving/loading named curve or levels presets to disk — pairs naturally with
  the future persisted-config-file idea (Ideas.md), not this feature.
- 16-bit-per-channel histograms/LUTs — the Pillow pipeline is 8-bit.
- Live histogram of the *original* image as an overlay (decided: post-enhancement only).
