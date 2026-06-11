# Editing — Select Tool (Phase 3 of Image Annotations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make placed annotations editable: a Select tool (key `1`, default-arrow cursor) with hit-test click selection and a dashed marker, drag-to-move and live restyling as single coalesced undo steps, Delete/BackSpace deletion, and real in-mode undo/redo routing for every entry point (replacing Phase 2's swallow-with-hint).

**Architecture:** The pure layer mechanics (`select_at`, `replace_selected` coalescing, `undo`/`redo`) shipped in Phase 1 — this phase wires them to the UI. `canvas_view.py` gains the dashed `set_selection_marker` (image-space truth, re-derived at the end of every `display()`) and a Select-aware cursor switch; the palette grows a Select branch in its session protocol (press = topmost pick via the new pure `hit_tolerance`, drag = coalesced move from the shape as pressed, styling controls restyle the live selection), and its Phase 2 `on_undo_key`/`on_redo_key` hint bodies are replaced with `layer.undo()`/`layer.redo()` routing, consumed-when-empty. `commands.py` adds `cmd_delete`/`cmd_backspace` so BackSpace doubles as delete-with-selection while the arrow keys stay pure navigation.

**Decisions where the spec leaves internals open (BINDING on later phases):**

- The tolerance formula gets a pure home: `annotations.hit_tolerance(zoom, width_px) = max(HIT_TOL_SCREEN_PX / zoom, width_px / 2)` with `HIT_TOL_SCREEN_PX = 6.0`. `hit_test` takes ONE tol for all shapes, so the palette passes its *current* `width_px` (the live styling control) — the only width in scope at click time.
- `annotation_palette.PaletteTool = Union[Tool, Literal["select"]]`; `TOOL_KEYS` widens to `dict[str, PaletteTool]` and gains `"1": "select"`. `Shape.tool` stays the narrower `Tool` — `"select"` never reaches a `Shape`.
- The Select-move applies `translated()` from the shape *as pressed* (absolute deltas — no per-event float drift) and reuses `MIN_DRAG_SCREEN_PX = 3.0` as a click-vs-move gate, so pointer jitter on a click never creates an undo step. The release position is authoritative.
- Escape mid-move rolls back via `layer.undo()` (the move is one coalesced state, so one undo restores the pre-move shape exactly) and sets Phase 2's cancel latch. The aborted move parks on the redo stack — accepted quirk, documented in an AIDEV-NOTE.
- The marker is a single dashed white rectangle padded by `_MARKER_PAD = 3.0` canvas px (so a zero-height bbox — a horizontal line — still reads as a box), stored on `CanvasView` as an image-space bbox and re-derived inside `display()`.
- `is_dragging` is True for the *whole* Select press-to-release (not only once movement starts), so the wheel and zoom/navigation keys stay consumed for the full press.
- BackSpace routes through new `cmd_backspace` (delete with a selection, else `cmd_prev_image`); `<Left>` stays bound straight to `cmd_prev_image`. Root `<Delete>` binds to new `cmd_delete`, inert while the palette is closed.
- `on_double_click`/text re-edit is NOT here — the spec ships double-click with text labels in Phase 4.

**Tech Stack:** Python 3.10+, Pillow + tkinter/ttk, pytest, uv, ruff, mypy strict.

**Spec:** docs/superpowers/specs/2026-06-10-annotations-design.md · **Branch:** `annotations` (Phases 1–2 — `annotations.py`/`annotation_render.py`, the palette, canvas session plumbing, gating — must already be merged on it).

---

## Environment notes for the executor

- Pure tests: `uv run pytest <file> -v`. DISPLAY-gated tests need Xvfb on :99 → `DISPLAY=:99 uv run pytest <file> -v`. If `:99` is not already up: `Xvfb :99 -screen 0 1280x1024x24 &` (there is no `xvfb-run` on this machine).
- After writing Python: `uv run ruff format <files>` and `uv run mypy src/pxv` (strict).
- Never remove existing `AIDEV-NOTE` comments. Exception, sanctioned here: Task 6 REPLACES the Phase 2 note inside `on_undo_key` whose own text says "Phase 3 … replaces this body" — replace it with the updated note given in that task, never with nothing.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Code snippets quoted from `canvas_view.py`, `annotation_palette.py`, `commands.py`, and `app.py` show their **post-Phase-2** state; where a current-file line number is given it is marked pre-Phase-1/2. Phases 1–2 inserted code above most edit points, so **always match on the quoted code, not the number**.
- Test-count expectations assume Phase 2 left `tests/test_annotation_mode.py` at 31 tests, `tests/test_annotations.py` at 23, and the full suite at 367 collected. If they differ, reconcile against the per-task deltas.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/annotations.py` | modify | `hit_tolerance` + `HIT_TOL_SCREEN_PX`: the Select tool's pure pick-tolerance formula |
| `src/pxv/canvas_view.py` | modify | `set_selection_marker`/`_redraw_selection_marker` (dashed, image-space, re-derived in `display()`), `set_annotation_cursor`, disarm clears the marker |
| `src/pxv/annotation_palette.py` | modify | Select tool: `PaletteTool`, key `1`, click-select/move/restyle, Escape move-cancel + deselect, layer undo/redo routing, delete marker sync |
| `src/pxv/commands.py` | modify | `cmd_delete`; `cmd_backspace` (delete-with-selection, else previous image) |
| `src/pxv/app.py` | modify | Root `<Delete>` binding; `<BackSpace>` rebound to `cmd_backspace` |
| `tests/test_annotations.py` | modify | `hit_tolerance` formula + the exact move/restyle coalescing sequences the palette performs (pure) |
| `tests/test_annotation_mode.py` | modify | DISPLAY-gated: marker, cursor, select/move/restyle, Escape, undo routing, Delete/BackSpace |

---

### Task 1: `annotations.py` — `hit_tolerance` + pure coalescing-sequence tests

**Files:** Modify `src/pxv/annotations.py`; modify `tests/test_annotations.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_annotations.py`, extend the import (Phase 1 left it as `from pxv.annotations import AnnotationLayer, Shape, hit_test, size_presets`) to:

```python
from pxv.annotations import AnnotationLayer, Shape, hit_test, hit_tolerance, size_presets
```

Then append to the file:

```python
def test_hit_tolerance_formula() -> None:
    assert hit_tolerance(1.0, 2.0) == 6.0  # 6/zoom dominates thin strokes
    assert hit_tolerance(2.0, 2.0) == 3.0  # zoomed in: tighter picking
    assert hit_tolerance(0.5, 2.0) == 12.0  # zoomed out: more forgiving
    assert hit_tolerance(1.0, 20.0) == 10.0  # thick strokes: width/2 wins


def test_hit_tolerance_feeds_select_at() -> None:
    layer = AnnotationLayer()
    layer.add(_line(0.0, 0.0, 100.0, 0.0))
    assert layer.select_at((50.0, 5.0), hit_tolerance(1.0, 2.0)) == 0  # tol 6
    assert layer.select_at((50.0, 5.0), hit_tolerance(2.0, 2.0)) is None  # tol 3


def test_move_run_from_original_is_driftless_and_one_undo_step() -> None:
    # The Select tool's move-drag: every step is translated() from the shape
    # AS PRESSED (absolute deltas, no accumulation), and the coalescing in
    # replace_selected makes the whole run ONE undo step.
    layer = AnnotationLayer()
    original = _line(0.0, 0.0, 10.0, 0.0)
    layer.add(original)
    layer.select_at((5.0, 0.0), 2.0)
    for dx in (0.1, 0.2, 0.3, 7.0):
        layer.replace_selected(original.translated(dx, 0.0))
    assert layer.shapes[0].points == ((7.0, 0.0), (17.0, 0.0))  # exact, no drift
    assert layer.undo() is True
    assert layer.shapes == (original,)  # one step back to the pressed shape
    assert layer.undo() is True
    assert layer.shapes == ()


def test_restyle_runs_split_by_reselect_are_separate_undo_steps() -> None:
    # The palette's restyle flow: swatch/size walks on one selection coalesce;
    # re-selecting starts a fresh undo step.
    layer = AnnotationLayer()
    original = _line(0.0, 0.0, 10.0, 0.0)
    layer.add(original)
    layer.select_at((5.0, 0.0), 2.0)
    layer.replace_selected(dataclasses.replace(original, color="#00ff00"))
    layer.replace_selected(dataclasses.replace(original, color="#0000ff"))
    layer.select_at((5.0, 0.0), 2.0)  # re-select the same shape
    layer.replace_selected(dataclasses.replace(layer.shapes[0], width_px=8.0))
    assert layer.shapes[0].color == "#0000ff" and layer.shapes[0].width_px == 8.0
    layer.undo()
    assert layer.shapes[0].color == "#0000ff" and layer.shapes[0].width_px == 2.0
    layer.undo()
    assert layer.shapes == (original,)
```

(`dataclasses` and the `_line` helper are already at the top of this file from Phase 1.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_annotations.py -v`
Expected: FAIL at collection (`ImportError: cannot import name 'hit_tolerance' from 'pxv.annotations'`)

- [ ] **Step 3: Write the implementation**

In `src/pxv/annotations.py`, `hit_test` ends with:

```python
    for i in range(len(shapes) - 1, -1, -1):
        if _shape_hit(shapes[i], xy, tol):
            return i
    return None
```

Immediately after it (before `@dataclass(frozen=True)` / `class SizePresets:`), insert:

```python
# AIDEV-NOTE: Select-tool pick tolerance (2026-06-10 design): forgiving to
# ~6 SCREEN px at any zoom, widened to half the stroke width so thick shapes
# are as easy to grab as they look. Pure — the palette passes the live zoom
# and its current width_px (hit_test takes one tol for all shapes).
HIT_TOL_SCREEN_PX = 6.0


def hit_tolerance(zoom: float, width_px: float) -> float:
    """Image-px hit-test tolerance for the Select tool: max(6.0/zoom, width/2)."""
    return max(HIT_TOL_SCREEN_PX / zoom, width_px / 2.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_annotations.py -v`
Expected: 27 PASS (23 existing + 4 new)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotations.py tests/test_annotations.py
uv run mypy src/pxv
git add src/pxv/annotations.py tests/test_annotations.py
git commit -m "feat(draw): hit_tolerance — the Select tool's pure pick-tolerance formula

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `canvas_view.py` — dashed selection marker + Select-aware cursor

**Files:** Modify `src/pxv/canvas_view.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotation_mode.py` (the `_canvas_view` and `_RecordingSession` helpers are already in this file from Phase 2):

```python
def test_selection_marker_converts_image_space_dashed_single_item() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_selection_marker((10.0, 20.0, 30.0, 40.0))
        assert view._marker_id is not None
        # Image (10,20)/(30,40) -> canvas (110,120)/(130,140) via the centering
        # offset (100), then padded by 3 canvas px on every side.
        assert view.canvas.coords(view._marker_id) == [107.0, 117.0, 133.0, 143.0]
        assert view.canvas.itemcget(view._marker_id, "dash") != ""  # dashed
        first = view._marker_id
        view.set_selection_marker((0.0, 0.0, 10.0, 10.0))
        assert view._marker_id != first
        assert len(view.canvas.find_withtag("all")) == 1  # ONE item: old deleted
        view.set_selection_marker(None)
        assert view._marker_id is None
        assert len(view.canvas.find_withtag("all")) == 0
    finally:
        root.destroy()


def test_selection_marker_rederived_on_display_and_cleared_on_disarm() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_selection_marker((10.0, 20.0, 30.0, 40.0))
        view.zoom = 2.0
        view.display(Image.new("RGB", (200, 200), (0, 0, 0)))  # re-render, new zoom
        # 200x200 display on a 300x300 canvas -> offset 50; image*2 + 50, pad 3.
        assert view.canvas.coords(view._marker_id) == [67.0, 87.0, 113.0, 133.0]
        view.set_annotation_session(_RecordingSession())
        view.set_annotation_session(None)  # disarm clears the marker
        assert view._marker_id is None
    finally:
        root.destroy()


def test_annotation_cursor_switches_arrow_for_select() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_annotation_cursor(True)  # disarmed: a no-op
        assert view.canvas.cget("cursor") == "crosshair"
        view.set_annotation_session(_RecordingSession())
        view.set_annotation_cursor(True)
        assert view.canvas.cget("cursor") == ""  # the default arrow
        view.set_annotation_cursor(False)
        assert view.canvas.cget("cursor") == "pencil"
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 3 new FAIL (`AttributeError` — the marker tests on `set_selection_marker`, the cursor test on `set_annotation_cursor`); all Phase 2 tests still PASS

- [ ] **Step 3: Write the implementation**

All edits in `src/pxv/canvas_view.py`.

(a) Immediately after the Phase 1 module-level helper `image_xy_to_canvas_point` and before `class AnnotationSession(Protocol):`, insert:

```python
# Canvas-px padding around the Select tool's dashed selection marker, so a
# zero-height bbox (a horizontal line, a 2-point shape) still reads as a box.
_MARKER_PAD = 3.0
```

(b) In `CanvasView.__init__`, Phase 2 added:

```python
        # The single transient drag-preview item (draw mode).
        self._preview_id: int | None = None
```

Append directly below it:

```python
        # The Select tool's dashed marker: Tk item id + IMAGE-space bbox truth.
        self._marker_id: int | None = None
        self._marker_bbox: tuple[float, float, float, float] | None = None
```

(c) Replace Phase 2's `set_annotation_session` (the whole method) with:

```python
    def set_annotation_session(self, session: AnnotationSession | None) -> None:
        """Arm (or disarm with None) draw-mode event forwarding.

        AIDEV-NOTE: Entering clears any rubber-band selection (selection
        handling is suspended for the whole session) and shows the pencil
        cursor — the canvas is already crosshair normally, so the mode is
        visually distinct (the Select tool switches to the default arrow via
        set_annotation_cursor). Disarming clears the transient preview item
        AND the selection marker; the palette calls this FIRST in
        _end_session (the eyedropper _on_close pattern), so no event can
        reach a dying session.
        """
        self._annotation_session = session
        if session is not None:
            self.clear_selection()
            self.canvas.config(cursor="pencil")
        else:
            self.clear_preview()
            self.set_selection_marker(None)
            self.canvas.config(cursor="crosshair")
```

(d) After Phase 2's `clear_preview` (ends `self._preview_id = None`), insert:

```python
    def set_selection_marker(self, bbox: tuple[float, float, float, float] | None) -> None:
        """Show (or clear with None) the Select tool's dashed selection marker.

        AIDEV-NOTE: bbox is IMAGE-space (x0, y0, x1, y1) — the shape's source
        of truth. The Tk item is re-derived inside display() on every
        re-render, so zoom/pan/resize can never strand it at stale coords.
        """
        self._marker_bbox = bbox
        self._redraw_selection_marker()

    def _redraw_selection_marker(self) -> None:
        """(Re)create the marker item from the stored image-space bbox."""
        if self._marker_id is not None:
            self.canvas.delete(self._marker_id)
            self._marker_id = None
        if self._marker_bbox is None:
            return
        disp = (self._display_width, self._display_height)
        csize = (self.canvas.winfo_width(), self.canvas.winfo_height())
        x0, y0 = image_xy_to_canvas_point(
            (self._marker_bbox[0], self._marker_bbox[1]), disp, csize, self.zoom
        )
        x1, y1 = image_xy_to_canvas_point(
            (self._marker_bbox[2], self._marker_bbox[3]), disp, csize, self.zoom
        )
        self._marker_id = self.canvas.create_rectangle(
            x0 - _MARKER_PAD,
            y0 - _MARKER_PAD,
            x1 + _MARKER_PAD,
            y1 + _MARKER_PAD,
            outline="#ffffff",
            dash=(4, 4),
            width=1,
        )

    def set_annotation_cursor(self, select_tool: bool) -> None:
        """Default arrow for the Select tool, pencil for the drawing tools.

        A no-op while disarmed, so a late tool-change callback can never
        repaint the cursor after the session ended.
        """
        if self._annotation_session is not None:
            self.canvas.config(cursor="" if select_tool else "pencil")
```

(e) `display()` ends with (canvas_view.py:171–172 pre-Phase-1):

```python
        if size_changed:
            self._center_view()
```

Append directly below, still inside `display()`:

```python
        # Re-derive the Select tool's marker from image-space truth — its
        # canvas coords go stale on every zoom/pan/resize re-render.
        self._redraw_selection_marker()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 34 PASS (31 + 3)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/canvas_view.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/canvas_view.py tests/test_annotation_mode.py
git commit -m "feat(draw): dashed selection marker and Select-aware cursor on the canvas

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Palette Select tool — key `1`, click selection, coalesced move-drag

**Files:** Modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

(a) Phase 2's `test_tool_keys_two_through_six_select_and_others_inert` asserts key `1` is inert — Phase 3 ships it. Replace that entire test function with:

```python
def test_tool_keys_select_and_others_inert(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        for char, tool in (
            ("1", "select"),
            ("2", "freehand"),
            ("3", "line"),
            ("4", "arrow"),
            ("5", "rect"),
            ("6", "ellipse"),
        ):
            palette.select_tool_key(char)
            assert palette.tool == tool
            assert palette._tool_var.get() == tool  # button row follows
        for char in ("7", "8"):  # Phase 4 tools: stable numbers, inert keys
            palette.select_tool_key(char)
        assert palette.tool == "ellipse"
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

(b) Append the new tests:

```python
def test_key_1_selects_select_tool_with_arrow_cursor(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        assert app.canvas_view.canvas.cget("cursor") == "pencil"
        palette.select_tool_key("1")
        assert palette.tool == "select"
        assert app.canvas_view.canvas.cget("cursor") == ""  # the default arrow
        palette.select_tool_key("3")
        assert app.canvas_view.canvas.cget("cursor") == "pencil"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_select_click_picks_topmost_and_shows_marker(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # shape 0
        _draw_line(palette, y=10.0)  # shape 1, right on top of it
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 1  # topmost (later) wins
        assert app.canvas_view._marker_id is not None
        palette.on_press((25.0, 60.0))  # empty canvas area
        palette.on_release((25.0, 60.0))
        assert palette.layer.selected is None  # click-empty deselects
        assert app.canvas_view._marker_id is None
        palette.on_press((25.0, 10.0))
        palette.select_tool_key("3")  # mid-press: inert, never orphans the drag
        assert palette.tool == "select"
        palette.on_release((25.0, 10.0))
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_select_drag_moves_shape_in_one_undo_step(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # (10,10)-(40,10)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        assert palette.is_dragging  # the whole press-to-release is a drag
        palette.on_drag((30.0, 15.0))  # +5,+5 from the press point
        palette.on_drag((35.0, 30.0))  # +10,+20 ABSOLUTE from the press point
        palette.on_release((35.0, 30.0))
        assert not palette.is_dragging
        (shape,) = palette.layer.shapes
        assert shape.points == ((20.0, 30.0), (50.0, 30.0))
        assert palette.layer.selected == 0  # still selected after the move
        assert palette.layer.undo() is True  # the whole move: ONE undo step
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))
        assert palette.layer.undo() is True  # the add itself
        assert palette.layer.shapes == ()
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tiny_select_drag_is_a_click_not_a_move(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_drag((26.0, 11.0))  # ~1.4 image px * zoom 1.0 < 3 screen px
        palette.on_release((26.0, 11.0))
        (shape,) = palette.layer.shapes
        assert shape.points == ((10.0, 10.0), (40.0, 10.0))  # unmoved
        assert palette.layer.selected == 0  # but selected
        assert palette.layer.undo() is True
        assert palette.layer.shapes == ()  # only the add was on the stack
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 5 FAIL (key `1` is inert so `palette.tool` never becomes `"select"`: mostly `AssertionError`; `test_select_drag_moves_shape_in_one_undo_step` fails with `ValueError` because the press/drag/release runs the line-tool branch, adds a second line, and the 1-tuple unpack raises); the rest PASS

- [ ] **Step 3: Write the implementation**

All edits in `src/pxv/annotation_palette.py`.

(a) Replace the import block (Phase 2 state shown first):

```python
import math
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from typing import TYPE_CHECKING, cast

from pxv.annotation_render import render_overlay
from pxv.annotations import AnnotationLayer, Shape, Tool, size_presets
```

with:

```python
import math
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from typing import TYPE_CHECKING, Literal, Union, cast

from pxv.annotation_render import render_overlay
from pxv.annotations import AnnotationLayer, Shape, Tool, hit_tolerance, size_presets
```

(b) After the `if TYPE_CHECKING:` block and before the `TOOL_KEYS` AIDEV-NOTE, insert:

```python
# The palette's active tool: any drawing Tool, or the non-drawing Select tool.
# Shape.tool stays the narrower Tool — "select" never reaches a Shape.
# typing.Union (not the | operator): this alias is evaluated at runtime.
PaletteTool = Union[Tool, Literal["select"]]
```

(c) Replace the `TOOL_KEYS` note + dict (Phase 2 state):

```python
# AIDEV-NOTE: Tool numbering is stable across phases (2026-06-10 design):
# 1 Select, 2 freehand, 3 line, 4 arrow, 5 rect, 6 ellipse, 7 highlighter,
# 8 text. Phase 2 ships 2-6; the other keys are inert and their buttons
# disabled until their phases (Select: 3; highlight/text: 4).
TOOL_KEYS: dict[str, Tool] = {
    "2": "freehand",
    "3": "line",
    "4": "arrow",
    "5": "rect",
    "6": "ellipse",
}
```

with:

```python
# AIDEV-NOTE: Tool numbering is stable across phases (2026-06-10 design):
# 1 Select, 2 freehand, 3 line, 4 arrow, 5 rect, 6 ellipse, 7 highlighter,
# 8 text. Phases 2-3 ship 1-6; the 7/8 keys are inert and their buttons
# disabled until Phase 4.
TOOL_KEYS: dict[str, PaletteTool] = {
    "1": "select",
    "2": "freehand",
    "3": "line",
    "4": "arrow",
    "5": "rect",
    "6": "ellipse",
}
```

(d) In `__init__`, change the tool attribute line:

```python
        self.tool: Tool = "freehand"
```

to:

```python
        self.tool: PaletteTool = "freehand"
```

and after the Escape-latch line:

```python
        # Escape latch: swallow motion/release until the physical ButtonRelease.
        self._cancel_latch = False
```

append:

```python
        # In-flight Select-tool move: (press_xy, shape AS PRESSED), plus
        # whether the 3-screen-px gate opened (a click with jitter ≠ a move).
        self._select_drag: tuple[tuple[float, float], Shape] | None = None
        self._select_moved = False
```

(e) In `_build_ui`, the tools tuple begins `("1", "Select", False),` — flip it to shipped:

```python
            ("1", "Select", True),
```

(f) Replace `select_tool_key` and `_on_tool_selected` (Phase 2 state):

```python
    def select_tool_key(self, char: str) -> None:
        """Tool hotkey (root- and palette-bound). Unshipped keys are inert."""
        tool = TOOL_KEYS.get(char)
        if tool is None:
            return
        self.tool = tool
        self._tool_var.set(tool)

    def _on_tool_selected(self) -> None:
        # Only enabled (shipped) radiobuttons can fire, so the var holds a Tool.
        self.tool = cast(Tool, self._tool_var.get())
```

with:

```python
    def select_tool_key(self, char: str) -> None:
        """Tool hotkey (root- and palette-bound). Unshipped keys are inert."""
        if self.is_dragging:
            return  # a mid-press switch would orphan the in-flight drag state
        tool = TOOL_KEYS.get(char)
        if tool is None:
            return
        self.tool = tool
        self._tool_var.set(tool)
        self._update_canvas_cursor()

    def _on_tool_selected(self) -> None:
        # Only enabled (shipped) radiobuttons can fire: the var holds a PaletteTool.
        self.tool = cast(PaletteTool, self._tool_var.get())
        self._update_canvas_cursor()

    def _update_canvas_cursor(self) -> None:
        """Arrow for Select, pencil for drawing tools (no-op once disarmed)."""
        self.app.canvas_view.set_annotation_cursor(self.tool == "select")
```

(g) Replace the session-protocol methods `is_dragging`, `on_press`, `on_drag`, `on_release` (Phase 2 state — from `@property` / `def is_dragging` through the end of `on_release`) with:

```python
    @property
    def is_dragging(self) -> bool:
        # A Select press counts from the click itself, so the wheel and the
        # zoom/navigation keys stay consumed for the whole press-to-release.
        return self._drag_points is not None or self._select_drag is not None

    def on_press(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            return
        if self.tool == "select":
            self._select_press(image_xy)
            return
        self._drag_points = [image_xy]

    def on_drag(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            return
        if self.tool == "select":
            self._select_drag_to(image_xy)
            return
        if self._drag_points is None:
            return
        tool = cast(Tool, self.tool)  # the select branch returned above
        if tool == "freehand":
            self._drag_points.append(image_xy)
        else:
            self._drag_points = [self._drag_points[0], image_xy]
        self.app.canvas_view.set_preview_shape(
            _PREVIEW_KINDS[tool],  # type: ignore[arg-type]
            self._drag_points,
            self.color,
            self.width_px,
        )

    def on_release(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            # The physical ButtonRelease of an Escape-cancelled drag re-arms us.
            self._cancel_latch = False
            return
        if self.tool == "select":
            self._select_release(image_xy)
            return
        if self._drag_points is None:
            return
        tool = cast(Tool, self.tool)
        points = self._drag_points
        self._drag_points = None
        self.app.canvas_view.clear_preview()
        if tool == "freehand":
            points.append(image_xy)
        else:
            points = [points[0], image_xy]
        # AIDEV-NOTE: Tiny accidental drags make no shape. Screen px = image
        # px * zoom; measured as the MAX displacement from the press point so
        # a closed freehand loop (release near press) still counts as a drag.
        zoom = self.app.canvas_view.zoom
        x0, y0 = points[0]
        if max(math.hypot(x - x0, y - y0) for x, y in points) * zoom < MIN_DRAG_SCREEN_PX:
            return
        self.layer.add(
            Shape(tool=tool, points=tuple(points), color=self.color, width_px=self.width_px)
        )
        self.app.annotations_unsaved = True  # set on the first shape (and kept)
        self.app.refresh_display()
```

(The drawing branches are Phase 2's logic verbatim, re-rooted on the local `tool` so mypy sees a `Tool`, not a `PaletteTool`.)

(h) Insert the Select helpers directly after `on_release` and before `render_display_overlay`:

```python
    # --- Select tool (key 1) ----------------------------------------------

    def _select_press(self, image_xy: tuple[float, float]) -> None:
        """Click: pick the topmost hit (or deselect on empty), arm a move."""
        tol = hit_tolerance(self.app.canvas_view.zoom, self.width_px)
        index = self.layer.select_at(image_xy, tol)
        self._select_drag = None if index is None else (image_xy, self.layer.shapes[index])
        self._select_moved = False
        self._refresh_selection_marker()

    def _select_drag_to(self, image_xy: tuple[float, float]) -> None:
        """Drag: move the selection. The whole run is ONE coalesced undo step."""
        if self._select_drag is None:
            return
        (px, py), original = self._select_drag
        dx, dy = image_xy[0] - px, image_xy[1] - py
        zoom = self.app.canvas_view.zoom
        if not self._select_moved and math.hypot(dx, dy) * zoom < MIN_DRAG_SCREEN_PX:
            return  # a click with pointer jitter is a selection, not a move
        self._select_moved = True
        # AIDEV-NOTE: Every step is translated() from the shape AS PRESSED
        # (absolute deltas), so a long move accumulates no float error, and
        # consecutive replace_selected calls coalesce into one undo state
        # (select_at at press broke the previous run).
        self.layer.replace_selected(original.translated(dx, dy))
        self._refresh_selection_marker()
        self.app.refresh_display()

    def _select_release(self, image_xy: tuple[float, float]) -> None:
        """Release: the final pointer position is authoritative for a move."""
        if self._select_drag is not None and self._select_moved:
            (px, py), original = self._select_drag
            self.layer.replace_selected(original.translated(image_xy[0] - px, image_xy[1] - py))
            self._refresh_selection_marker()
            self.app.refresh_display()
        self._select_drag = None
        self._select_moved = False

    def _refresh_selection_marker(self) -> None:
        """Sync the canvas marker with layer.selected (None clears it)."""
        if self.layer.selected is None:
            self.app.canvas_view.set_selection_marker(None)
        else:
            shape = self.layer.shapes[self.layer.selected]
            self.app.canvas_view.set_selection_marker(shape.bbox())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 38 PASS (34 + 4 new; the rewritten tool-keys test passes too)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): Select tool — click selection and coalesced move-drag

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Escape — cancel a move (rollback + latch), then deselect

**Files:** Modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotation_mode.py`:

```python
def test_escape_cancels_move_with_latch_and_rolls_back(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_drag((45.0, 40.0))  # +20,+30: mid-move
        assert palette.layer.shapes[0].points == ((30.0, 40.0), (60.0, 40.0))
        palette.on_escape()
        # The move was ONE coalesced undo state: rolled back exactly.
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))
        assert palette.layer.selected is None  # layer.undo() clears selection
        assert app.canvas_view._marker_id is None
        assert not palette.is_dragging
        palette.on_drag((60.0, 60.0))  # latched: swallowed
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))
        palette.on_release((60.0, 60.0))  # the physical release re-arms us
        palette.select_tool_key("3")
        palette.on_press((10.0, 50.0))
        palette.on_drag((40.0, 50.0))
        palette.on_release((40.0, 50.0))
        assert len(palette.layer.shapes) == 2  # drawing works again
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_escape_deselects_before_doing_nothing(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        app.annotation_palette = palette  # cmd_escape routes through the app attr
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 0
        commands.cmd_escape(app)  # the root Escape entry point
        assert palette.layer.selected is None  # deselect step
        assert app.canvas_view._marker_id is None
        assert len(palette.layer.shapes) == 1  # nothing deleted or undone
        commands.cmd_escape(app)  # nothing selected: consumed, no-op
        assert app.annotation_palette is palette  # never exits the mode
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

(`commands` is already imported at the top of this file from Phase 2; `_open_palette` already sets `app.annotation_palette`, the explicit assignment is belt-and-braces documentation.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 2 new FAIL (`AssertionError` — `on_escape` ignores a Select move, so the shape stays moved and the selection survives); the rest PASS

- [ ] **Step 3: Write the implementation**

In `src/pxv/annotation_palette.py`, replace `on_escape` (Phase 2 state):

```python
    def on_escape(self) -> None:
        """Escape inside the mode: cancel an in-flight drag, else nothing.

        AIDEV-NOTE: Never exits the mode (no accidental bakes) and never
        falls through to app.escape_action — leaving fullscreen during a
        session is f/F11. The latch swallows the cancelled drag's remaining
        motion events until the physical ButtonRelease (see on_release).
        """
        if self._drag_points is not None:
            self._drag_points = None
            self._cancel_latch = True
            self.app.canvas_view.clear_preview()
```

with:

```python
    def on_escape(self) -> None:
        """Escape inside the mode: cancel a drag, else deselect, else nothing.

        AIDEV-NOTE: Never exits the mode (no accidental bakes) and never
        falls through to app.escape_action — leaving fullscreen during a
        session is f/F11. The latch swallows the cancelled drag's remaining
        motion events until the physical ButtonRelease (see on_release).
        A cancelled MOVE rolls back through layer.undo(): the move run is one
        coalesced undo state, so one undo restores the pre-move shape exactly
        (the aborted move parks on the redo stack — accepted quirk).
        """
        if self._drag_points is not None:
            self._drag_points = None
            self._cancel_latch = True
            self.app.canvas_view.clear_preview()
            return
        if self._select_drag is not None:
            if self._select_moved:
                self.layer.undo()  # rolls back the move, clears the selection
                self.app.refresh_display()
            self._select_drag = None
            self._select_moved = False
            self._cancel_latch = True
            self._refresh_selection_marker()
            return
        if self.layer.selected is not None:
            self.layer.selected = None
            self._refresh_selection_marker()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 40 PASS (38 + 2; Phase 2's `test_escape_cancels_drag_with_latch_until_physical_release` and `test_zoom_consumed_during_drag_and_escape_never_leaves_mode` must stay green — the drawing-drag branch is unchanged)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): Escape cancels a move and deselects inside draw mode

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Styling controls restyle the live selection (coalesced)

**Files:** Modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_annotation_mode.py`:

```python
def test_styling_controls_restyle_live_selection_coalesced(tmp_path) -> None:  # noqa: ANN001
    from pxv.annotations import size_presets

    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)  # red, medium (width 2.0 at long side 100)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        palette.set_color("#00ff00")
        palette.set_color("#0000ff")  # same coalesced run
        palette._size_var.set("thick")
        palette._on_size_selected()  # still the same run
        (shape,) = palette.layer.shapes
        assert shape.color == "#0000ff"
        assert shape.width_px == size_presets(100).widths[2]
        assert palette.color == "#0000ff"  # defaults for NEW shapes follow too
        assert palette.layer.undo() is True  # ONE step: the whole restyle run
        (shape,) = palette.layer.shapes
        assert shape.color == "#ff0000" and shape.width_px == 2.0
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 1 new FAIL (`AssertionError` — `set_color` only sets the default, so `shape.color` stays `#ff0000`); the rest PASS

- [ ] **Step 3: Write the implementation**

All edits in `src/pxv/annotation_palette.py`.

(a) Add to the imports, after `import tkinter as tk`:

```python
from dataclasses import replace
```

(b) In `__init__`, update the Phase 2 comment line:

```python
        # Styling state for NEW shapes (restyling a selection arrives in Phase 3).
```

to:

```python
        # Styling state for NEW shapes; with a live selection the controls
        # also restyle it (see _restyle_selection).
```

(c) Replace `set_color` and `_on_size_selected` (Phase 2 state):

```python
    def set_color(self, color: str) -> None:
        """Set the '#rrggbb' color for NEW shapes."""
        self.color = color
        self._color_indicator.configure(bg=color)

    def _on_custom_color(self) -> None:
        _rgb, hexcolor = colorchooser.askcolor(color=self.color, parent=self)
        if hexcolor is not None:
            self.set_color(hexcolor)

    def _on_size_selected(self) -> None:
        idx = {"thin": 0, "medium": 1, "thick": 2}[self._size_var.get()]
        self.width_px = self._presets.widths[idx]
```

with (`_on_custom_color` is unchanged and routes through `set_color`, so the custom chooser restyles too):

```python
    def set_color(self, color: str) -> None:
        """Set the '#rrggbb' color for new shapes; restyle the selection live."""
        self.color = color
        self._color_indicator.configure(bg=color)
        self._restyle_selection(color=color)

    def _on_custom_color(self) -> None:
        _rgb, hexcolor = colorchooser.askcolor(color=self.color, parent=self)
        if hexcolor is not None:
            self.set_color(hexcolor)

    def _on_size_selected(self) -> None:
        idx = {"thin": 0, "medium": 1, "thick": 2}[self._size_var.get()]
        self.width_px = self._presets.widths[idx]
        self._restyle_selection(width_px=self.width_px)

    def _restyle_selection(self, **changes: object) -> None:
        """Apply a styling change to the live selection; no-op without one.

        AIDEV-NOTE: Consecutive replace_selected calls on the same index
        coalesce (annotations.py), so walking through swatches and sizes with
        a selection held is ONE undo step; re-selecting breaks the run.
        """
        if self.layer.selected is None:
            return
        shape = replace(self.layer.shapes[self.layer.selected], **changes)
        self.layer.replace_selected(shape)
        self._refresh_selection_marker()
        self.app.refresh_display()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 41 PASS (Phase 2's `test_color_and_size_controls_style_new_shapes` must stay green — without a selection `_restyle_selection` is a no-op)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): styling controls restyle the live selection (coalesced)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: In-mode undo/redo routing for ALL entry points

Every undo/redo entry point already funnels into two palette methods, so swapping their bodies covers the whole surface — no other file changes:

- Root keys `u`/`Ctrl-z` and `Ctrl-y`/`Ctrl-Shift-Z` → `commands.cmd_undo`/`cmd_redo` (app.py:169–172 pre-Phase-2), which Phase 2 routed to `palette.on_undo_key()`/`on_redo_key()` while the palette exists.
- Context-menu Undo/Redo → the same `cmd_undo`/`cmd_redo` (context_menu.py:24–25: `self.menu.add_command(label="Undo", command=lambda: commands.cmd_undo(app))` — **no edit needed**).
- The palette's own key mirrors (`_bind_keys`, Phase 2) call `on_undo_key`/`on_redo_key` directly.

**Files:** Modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Rewrite the two Phase 2 hint tests and add the marker test**

(a) Replace the entire Phase 2 test `test_undo_keys_swallowed_with_hint_while_open` with:

```python
def test_undo_keys_route_to_layer_while_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        app.record_history()  # a fall-through to app history would be visible
        _draw_line(palette, y=10.0)
        palette.on_undo_key()  # the palette key mirrors land here directly
        assert palette.layer.shapes == ()
        palette.on_redo_key()
        assert len(palette.layer.shapes) == 1
        assert len(app.history._undo) == 1  # app history untouched
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

(b) Replace the entire Phase 2 test `test_undo_keys_route_to_palette_when_open_and_history_when_closed` with:

```python
def test_undo_entry_points_route_to_layer_and_consume_when_empty(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        app.record_history()
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)
        commands.cmd_undo(app)  # u / Ctrl-z / context-menu Undo all call this
        assert palette.layer.shapes == ()
        commands.cmd_redo(app)  # Ctrl-y / Ctrl-Shift-Z / context-menu Redo
        assert len(palette.layer.shapes) == 1
        commands.cmd_undo(app)
        commands.cmd_undo(app)  # layer stack empty: CONSUMED, not app history
        assert len(app.history._undo) == 1
        assert "nothing to undo" not in root.title()  # consumed silently
        palette._end_session(bake=False)
        commands.cmd_undo(app)  # closed: routes to app history again
        assert len(app.history._undo) == 0
    finally:
        root.destroy()
```

(c) Append the new test:

```python
def test_undo_clears_selection_and_marker(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert app.canvas_view._marker_id is not None
        palette.on_undo_key()  # pops the add: shape gone, selection cleared
        assert palette.layer.shapes == () and palette.layer.selected is None
        assert app.canvas_view._marker_id is None
        palette.on_redo_key()  # restored WITHOUT a selection (layer semantics)
        assert len(palette.layer.shapes) == 1 and palette.layer.selected is None
        assert app.canvas_view._marker_id is None
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 3 FAIL (`AssertionError` — `on_undo_key` still shows the Phase 2 hint and never touches the layer); the rest PASS

- [ ] **Step 3: Write the implementation**

In `src/pxv/annotation_palette.py`, replace `on_undo_key` and `on_redo_key` (Phase 2 state — including the AIDEV-NOTE whose own text schedules this replacement):

```python
    def on_undo_key(self) -> None:
        """In-mode undo entry point — every undo key/menu path lands here.

        AIDEV-NOTE: Phase 2 swallows the key with a hint: the layer's undo
        stack exists (Phase 1) but editing ships with the Select tool in
        Phase 3, which replaces this body with layer.undo() routing. It must
        NEVER fall through to app history while the mode is active.
        """
        self.app.show_temp_title("pxv: undo arrives with the Select tool")

    def on_redo_key(self) -> None:
        self.app.show_temp_title("pxv: undo arrives with the Select tool")
```

with:

```python
    def on_undo_key(self) -> None:
        """In-mode undo — every undo entry point lands here while the mode is on.

        AIDEV-NOTE: u/Ctrl-z and the context-menu Undo funnel through
        commands.cmd_undo (which routes here while the palette exists); the
        palette's own key mirrors call this directly. When the layer stack is
        empty the key is CONSUMED and does nothing — it must never fall
        through to app history while the mode is active (2026-06-10 design).
        layer.undo() clears the selection, so the marker is re-synced.
        """
        if self.layer.undo():
            self._refresh_selection_marker()
            self.app.refresh_display()

    def on_redo_key(self) -> None:
        """In-mode redo (see on_undo_key); consumed when the redo stack is empty."""
        if self.layer.redo():
            self._refresh_selection_marker()
            self.app.refresh_display()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_undo_redo.py -v`
Expected: 42 + existing PASS (`test_undo_redo.py` pins that app history is untouched when the palette is closed)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): route in-mode undo/redo to the annotation layer

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Delete and BackSpace-with-selection delete the selected shape

**Files:** Modify `src/pxv/commands.py`; modify `src/pxv/app.py`; modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotation_mode.py`:

```python
def test_delete_key_and_backspace_delete_selection(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)
        _draw_line(palette, y=30.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        commands.cmd_delete(app)  # the root <Delete> chokepoint
        assert len(palette.layer.shapes) == 1
        assert palette.layer.shapes[0].points[0] == (10.0, 30.0)  # other survived
        assert palette.layer.selected is None
        assert app.canvas_view._marker_id is None  # marker cleared with it
        palette.on_press((25.0, 30.0))
        palette.on_release((25.0, 30.0))
        commands.cmd_backspace(app)  # BackSpace WITH a selection deletes
        assert palette.layer.shapes == ()
        assert app.file_list.index == 0  # and did NOT navigate
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_backspace_without_selection_navigates_through_the_gate(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)  # unsaved work, nothing selected
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: True)
        )
        commands.cmd_backspace(app)  # no selection: the navigate gate runs
        assert app.file_list.index == 1  # wrapped to the previous image
        assert app.annotation_palette is None  # confirmed prompt ended the session
        assert app.annotations_unsaved is False
    finally:
        root.destroy()


def test_delete_key_inert_without_draw_mode(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        assert root.bind("<Delete>")  # the root binding exists
        commands.cmd_delete(app)  # no palette: nothing to do, must not raise
        assert app.annotation_palette is None
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 3 new FAIL (two with `AttributeError: module 'pxv.commands' has no attribute 'cmd_delete'`/`'cmd_backspace'`; `test_delete_key_inert_without_draw_mode` with `AssertionError` at `assert root.bind("<Delete>")` — the binding doesn't exist yet); the rest PASS

- [ ] **Step 3: Write the implementation**

(a) In `src/pxv/commands.py`, after `cmd_redo` (Phase 2 state, ends `app.redo()`):

```python
def cmd_redo(app: PxvApp) -> None:
    """Redo the last undone edit (palette-routed while draw mode is active)."""
    if app.annotation_palette is not None:
        app.annotation_palette.on_redo_key()
        return
    app.redo()
```

insert:

```python
def cmd_delete(app: PxvApp) -> None:
    """Delete the selected annotation shape (Delete key; draw mode only).

    Inert while the palette is closed — pxv binds <Delete> for draw mode
    alone, and the palette mirrors the key on itself for when IT holds focus.
    """
    if app.annotation_palette is not None:
        app.annotation_palette.on_delete_key()


def cmd_backspace(app: PxvApp) -> None:
    """BackSpace: delete the selected shape in draw mode, else previous image.

    AIDEV-NOTE: Only BackSpace doubles as delete-with-selection (2026-06-10
    design); the Left arrow stays pure navigation, so it binds straight to
    cmd_prev_image while BackSpace routes here. Without a selection this
    falls through to cmd_prev_image and its navigate gate (discard prompt).
    """
    palette = app.annotation_palette
    if palette is not None and palette.layer.selected is not None:
        palette.on_delete_key()
        return
    cmd_prev_image(app)
```

(b) In `src/pxv/app.py` `_bind_keys` (lines 184–187 pre-Phase-2):

```python
        self.root.bind("<space>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<Right>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<BackSpace>", lambda _: commands.cmd_prev_image(self))
        self.root.bind("<Left>", lambda _: commands.cmd_prev_image(self))
```

replace the block with:

```python
        self.root.bind("<space>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<Right>", lambda _: commands.cmd_next_image(self))
        # AIDEV-NOTE: BackSpace doubles as delete-with-selection in draw mode
        # (the Left arrow stays pure navigation); Delete is draw-mode only.
        self.root.bind("<BackSpace>", lambda _: commands.cmd_backspace(self))
        self.root.bind("<Left>", lambda _: commands.cmd_prev_image(self))
        self.root.bind("<Delete>", lambda _: commands.cmd_delete(self))
```

(c) In `src/pxv/annotation_palette.py`, replace `on_delete_key` (Phase 2 state):

```python
    def on_delete_key(self) -> None:
        """Delete the selected shape (selection ships in Phase 3; no-op now)."""
        if self.layer.selected is None:
            return
        self.layer.delete_selected()
        self.app.refresh_display()
```

with:

```python
    def on_delete_key(self) -> None:
        """Delete the selected shape (Delete, or BackSpace with a selection)."""
        if self.layer.selected is None:
            return
        self.layer.delete_selected()
        self._refresh_selection_marker()
        self.app.refresh_display()
```

(The palette's own `<Delete>` mirror from Phase 2's `_bind_keys` already calls `on_delete_key`; BackSpace is deliberately NOT mirrored on the palette — navigation keys must keep prompting through the root chokepoint.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_commands.py -v`
Expected: 45 + existing PASS (`test_commands.py` pins that the gate helpers are untouched)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/commands.py src/pxv/app.py src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/commands.py src/pxv/app.py src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): Delete and BackSpace-with-selection delete the selected shape

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Full-suite verification + smoke

**Files:** none (verification only)

- [ ] **Step 1: Full suite under a display**

```bash
DISPLAY=:99 uv run pytest
```
Expected: 385 collected (367 after Phase 2 + 18 new: 4 pure annotations, 14 annotation-mode), 0 failures. If Phase 2's final count differed, reconcile against the +18 delta.

- [ ] **Step 2: Lint + typecheck**

```bash
uv run ruff format --check src tests
uv run mypy src/pxv
```
Expected: no reformats, mypy clean.

- [ ] **Step 3: Manual smoke under Xvfb — the full editing flow**

```bash
DISPLAY=:99 uv run python - << 'EOF'
import tkinter as tk
from pathlib import Path

from PIL import Image

from pxv import commands
from pxv.app import PxvApp
from pxv.file_list import FileList

p = Path("/tmp/select_smoke.png")
Image.new("RGB", (320, 240), (30, 30, 60)).save(p)

root = tk.Tk(className="pxv")
root.geometry("800x600")
app = PxvApp(root, FileList([p]))
root.update()
app.load_current()
root.update()

commands.cmd_annotate(app)
palette = app.annotation_palette
assert palette is not None

# Draw a red line and a red rect outline.
palette.select_tool_key("3")
palette.on_press((40.0, 120.0)); palette.on_drag((280.0, 120.0)); palette.on_release((280.0, 120.0))
palette.select_tool_key("5")
palette.on_press((60.0, 40.0)); palette.on_drag((160.0, 90.0)); palette.on_release((160.0, 90.0))

# Select tool: arrow cursor, pick the line, move it down 40 px, restyle green.
palette.select_tool_key("1")
assert app.canvas_view.canvas.cget("cursor") == ""
palette.on_press((150.0, 120.0)); palette.on_drag((150.0, 160.0)); palette.on_release((150.0, 160.0))
assert palette.layer.selected == 0
assert app.canvas_view._marker_id is not None
palette.set_color("#00ff00")
assert palette.layer.shapes[0].color == "#00ff00"

# Pick the rect by its border, delete it, undo the delete in-mode.
palette.on_press((60.0, 65.0)); palette.on_release((60.0, 65.0))
assert palette.layer.selected == 1
commands.cmd_delete(app)
assert len(palette.layer.shapes) == 1
commands.cmd_undo(app)  # routes to the layer while the palette is open
assert len(palette.layer.shapes) == 2
root.update()

# Done bakes ONE snapshot; moved green line + restored red rect in the pixels.
palette._on_done()
assert app.annotation_palette is None and len(app.history._undo) == 1
working = app.image_model.working_image
assert (0, 255, 0) in list(working.crop((148, 156, 153, 165)).getdata())
assert (255, 0, 0) in list(working.crop((59, 60, 64, 70)).getdata())
assert working.getpixel((10, 10)) == (30, 30, 60)
root.destroy()
print("smoke OK")
EOF
```

Expected: `smoke OK`. Delete `/tmp/select_smoke.png` afterwards. Report exact results.

---

## Out of scope (later phases)

- Text labels (key `8`, entry popup), highlighter (key `7`), opacity slider, fill toggle — Phase 4.
- `<Double-Button-1>` canvas binding + `on_double_click(image_xy)` and Select-double-click text re-edit — Phase 4 (ships with the text tool it re-edits).
- Context-menu "Draw / Annotate…" entry, `?` dialog rows (`KEYBINDINGS` in `dialogs.py`), README/CHANGELOG, per-tool cursor refinements beyond the Select arrow — Phase 5.
- Resize/endpoint handles on placed shapes — out of scope for the feature (undo and redraw instead).
