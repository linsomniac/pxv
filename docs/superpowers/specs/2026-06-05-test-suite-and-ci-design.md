# pxv Test Suite + CI — Design Spec

**Date:** 2026-06-05
**Status:** Approved (design)

## Goal

pxv currently has zero automated tests, and `.github/workflows/` contains only
`release.yml` — nothing runs lint/type-check/tests on push or PR. The 1.0.1
hardening pass fixed 26 bugs with no regression net underneath them. This adds a
pure-logic `pytest` suite that locks in that behavior, plus a CI workflow that
runs it on every push and PR.

## Scope

**In scope (this pass):**
- A `pytest` suite covering display-independent logic in `image_model`,
  `enhancements`, `file_list`, and the save helpers in `commands`.
- One small, behavior-preserving refactor: extract the selection→image
  coordinate math from `CanvasView.get_selection_image_coords` into a pure,
  testable helper.
- A `ci.yml` GitHub Actions workflow running ruff, mypy, and pytest.

**Out of scope (deliberately, for later passes):**
- GUI/Tk tests (canvas rendering, dialogs, app wiring), end-to-end app launch
  under Xvfb.
- Coverage thresholds / `pytest-cov` gating, property-based testing
  (`hypothesis`), golden-image comparisons.

## Approach

Chosen: **example-based pytest, one test module per source module, with
synthetic Pillow-generated fixtures.** For math-heavy and visual operations we
achieve golden-master rigor by constructing inputs whose correct output is known
by construction (e.g. a colored rectangle inset within a uniform border →
autocrop must return exactly that inner box), without committing binary fixtures
or pinning Pillow within our supported `>=10` range.

Rejected:
- **Property-based (hypothesis):** more edge-case rigor but adds a dependency and
  maintenance surface; not warranted for a first pass. May revisit per-function.
- **Golden images:** strong visual-regression detection but commits binaries and
  is brittle across Pillow versions.

## Tooling & layout

- Add `pytest` to the `dev` dependency group via `uv add --dev pytest`.
- `tests/` at the repo root, with `conftest.py` for shared fixtures.
- Test modules: `test_image_model.py`, `test_enhancements.py`,
  `test_file_list.py`, `test_save_helpers.py`, `test_canvas_geometry.py`.
- Tests carry type annotations (per project convention). `mypy --strict` remains
  scoped to `src/pxv` as today. `ruff check` / `ruff format --check` cover both
  `src/` and `tests/`.

## Fixtures (synthetic, no committed binaries)

`conftest.py` provides Pillow-built images covering every mode the code
special-cases:
- `RGB`, `RGBA` (including a semi-transparent pixel such as `(255, 0, 0, 128)`),
  `LA`, `PA`, `P` + `transparency`, `L`.
- Builders such as "colored rectangle inset within a uniform-color border" for
  crop/autocrop assertions.
- A `tmp_path`-based save/reload round-trip helper.

## Test coverage by module

### image_model
- `_to_rgb_working` / `_has_transparency`: transparent modes
  (RGBA/LA/PA/P+transparency) composite onto white; opaque non-RGB convert
  directly; transparent pixels do not leak their underlying color.
- `crop` + `uncrop`: one level of undo restores prior `working_image` and
  `_save_rgba`; the box is applied to both buffers.
- `autocrop`: RGB path (4-corner averaged background, EPSILON tolerance, MISSPCT
  slack) trims a known border; alpha path trims fully-transparent borders;
  returns `None`/`False` for "nothing to crop" and "entirely background".
- `rotate` / `flip_horizontal` / `flip_vertical` / `resize`: `working_image` and
  `_save_rgba` stay in lockstep (size and orientation).
- `reset`: returns to original working state and original `_save_rgba`.
- `get_save_image(preserve_alpha=True)`: `(255, 0, 0, 128)` round-trips without
  white fringing (the 1.0.1 fix); alpha band preserved.

### enhancements
- `EnhancementParams.is_identity` / `reset`.
- `_build_lut`: known-point values for brightness, gamma, and per-channel
  balance; clamping at 0/255; 768-entry length.
- `_apply_hue_rotation`: 0° is a no-op; wraps modulo 256/360.
- `apply_enhancements`: identity short-circuit returns an unmodified copy;
  brightness>1 raises mean luminance; **blur is gated on the slider value, not
  the zoom-scaled radius** (the 1.0.1 regression fix) — a nonzero blur at low
  zoom still blurs.

### file_list
- `FileList`: `next`/`prev` wrap-around, `position_str`, index-setter wraps,
  `add()` deduplicates by resolved path and selects the existing entry.
- `expand_paths`: files added directly; directories expand to sorted image
  files; duplicates removed (first wins); non-image extensions filtered;
  nonexistent paths reported to stderr (captured) and skipped.

### save helpers (commands)
- `_resolve_save_format`: recognized extensions map to the right Pillow format;
  unknown or missing extension → `("PNG", <path>.png)`.
- `_rgba_to_gif`: returns a palettized image with binary transparency reserved on
  index 255 and the expected save kwargs.

### canvas geometry (after refactor)
- `selection_to_image_box(selection, display_size, canvas_size, zoom)`: centering
  offset subtracted correctly; division by zoom; clamping to image bounds;
  degenerate selection (`ix2 <= ix1` or `iy2 <= iy1`) → `None`.

## Refactor (behavior-preserving)

Extract the coordinate math currently inside
`CanvasView.get_selection_image_coords` (`canvas_view.py`) into a module-level
pure function — e.g.
`selection_to_image_box(selection, display_size, canvas_size, zoom) -> tuple[int, int, int, int] | None`.
The widget method continues to read live widget sizes (`winfo_width`/
`winfo_height`, `_display_width`/`_display_height`) and delegates the arithmetic
to the helper. No behavior change; this exists solely to make the recently-fixed
crop-coordinate logic unit-testable without a display.

## CI workflow (`.github/workflows/ci.yml`)

- **Triggers:** `push` to `main`, and `pull_request` (all branches).
- **`lint` job** (single Python, 3.12): `ruff check src/ tests/`,
  `ruff format --check src/ tests/`, `mypy src/pxv/`.
- **`test` job** (matrix Python 3.10, 3.11, 3.12, 3.13 — matching project
  classifiers): `pytest`.
- Both jobs: `astral-sh/setup-uv`, `uv sync`. No display required (pure logic) —
  no Xvfb.
- Hardened to match `release.yml`: top-level `permissions: contents: read`,
  `actions/checkout` with `persist-credentials: false`.

## Definition of Done

- `uv run pytest` passes locally with the suite above.
- `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, and
  `uv run mypy src/pxv/` are all clean.
- The canvas-geometry refactor leaves runtime behavior unchanged (the widget
  still crops correctly).
- `ci.yml` is present and green on a PR.
- No binary fixtures committed; no new runtime dependencies (pytest is dev-only).
