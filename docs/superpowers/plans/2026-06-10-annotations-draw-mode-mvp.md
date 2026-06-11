# Draw Mode MVP (Phase 2 of Image Annotations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make annotations usable end-to-end: a palette window (`d`) that turns the canvas into a drawing surface for freehand/line/arrow/rect/ellipse (keys `2`–`6`) with colors and size presets, live PIL-overlay preview, a one-snapshot bake on Done, and full key/command gating with unsaved-annotations prompts.

**Architecture:** New `annotation_palette.py` (a non-modal Toplevel, Enhance-dialog style) owns the `AnnotationLayer` and the session protocol (`on_press`/`on_drag`/`on_release`/`is_dragging`/`render_display_overlay`); every way out of the mode funnels through one `_end_session(bake)`. `CanvasView` multiplexes mouse events to the session ahead of the rubber band (the pick-mode precedent) via a structural `AnnotationSession` Protocol and renders the in-flight drag as a single Tk preview item from image-space truth. The app gains a shared composite hook used by *both* display paths (overlay cached per `(layer.revision, display_size)` in the palette), `bake_annotations` following the crop/rotate snapshot pattern, the `annotations_unsaved` dirty flag, and a single `annotation_gate` chokepoint in `commands.py` that all gated `cmd_*` functions consult (root keys and the context menu call the same functions, so one check covers both).

**Decisions where the spec leaves internals open (BINDING on later phases):**

- `commands.annotation_gate(app, kind)` is the gating chokepoint; `kind` is `"mutate"` (consumed with a title hint while the palette is open), `"zoom"` (consumed only while a drag is in flight), or `"navigate"` (consumed during a drag; otherwise the discard prompt, ending an active session on confirm). Undo/redo and Escape route through the palette methods `on_undo_key`/`on_redo_key`/`on_escape` instead (Phase 3 swaps their bodies for layer routing).
- Canvas-side names: `CanvasView.set_annotation_session(session)`, the `AnnotationSession` Protocol (canvas-facing subset only), `set_preview_shape(kind, points, color, width_px)` with `kind in ("polyline", "line", "arrow", "rect", "ellipse")` and IMAGE-space points, `clear_preview()`, `_event_image_xy(event)`.
- Palette names: `AnnotationPalette.layer`, `.tool`, `.color`, `.width_px`, `.select_tool_key(char)`, `.set_color(color)`, `.image_is_current()`, `.cancel_stale()`, `._end_session(bake)`, `._on_done()`, `._on_cancel()`, `.on_delete_key()`; module constants `TOOL_KEYS`, `SWATCHES`, `MIN_DRAG_SCREEN_PX = 3.0`.
- The 3.0-screen-px discard measures the *maximum* displacement from the press point (screen px = image px × zoom), so a closed freehand loop that releases near its start still counts as a real drag.
- The stale-image title message shows *after* the teardown refresh (`_update_title` at the end of the display paths would clobber it otherwise).
- A user-confirmed Cancel (palette button) clears `annotations_unsaved` — it is "the user confirming a discard prompt" in the spec's lifecycle clause (b).

**Tech Stack:** Python 3.10+, Pillow + tkinter/ttk, pytest, uv, ruff, mypy strict.

**Spec:** docs/superpowers/specs/2026-06-10-annotations-design.md · **Branch:** `annotations` (Phase 1 — `annotations.py`, `annotation_render.py`, the float geometry helpers, Pillow ≥ 10.1 — must already be merged on it).

---

## Environment notes for the executor

- Pure tests: `uv run pytest <file> -v`. DISPLAY-gated tests need Xvfb on :99 → `DISPLAY=:99 uv run pytest <file> -v`. If `:99` is not already up: `Xvfb :99 -screen 0 1280x1024x24 &` (there is no `xvfb-run` on this machine).
- After writing Python: `uv run ruff format <files>` and `uv run mypy src/pxv` (strict).
- Never remove existing `AIDEV-NOTE` comments.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Line numbers below for `canvas_view.py` are quoted *post-Phase-1* where stated; Phase 1 inserted ~43 lines of float helpers before `class CanvasView`, so when in doubt match on the quoted code, not the number. `app.py`, `commands.py`, `image_model.py` line numbers are exact (Phase 1 did not touch them).

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/image_model.py` | modify | `apply_overlay`: composite a full-res RGBA overlay onto working + save buffers in lockstep |
| `src/pxv/canvas_view.py` | modify | `AnnotationSession` Protocol, `set_annotation_session`, event multiplexing, pencil cursor, drag-preview item, wheel gating |
| `src/pxv/annotation_palette.py` | create | `AnnotationPalette` Toplevel: layer ownership, session protocol, tools/colors/sizes UI, Done/Cancel, `_end_session`, stale-image guard, key mirrors |
| `src/pxv/app.py` | modify | `annotation_palette`/`annotations_unsaved` state, `bake_annotations`, shared display-composite hook in both display paths, `d` + tool-key bindings, root `WM_DELETE_WINDOW` |
| `src/pxv/commands.py` | modify | `cmd_annotate`, `annotation_gate` chokepoint wired into mutate/save/zoom/navigate commands, undo/redo/Escape routing, `cmd_save_as -> bool` |
| `tests/test_image_model.py` | modify | `apply_overlay` lockstep + identity-replacement tests (pure) |
| `tests/test_annotation_mode.py` | create | DISPLAY-gated: canvas plumbing, palette session, bake/cancel, composite, guard, gating, prompts |
| `tests/test_commands.py` | modify | Pure `annotation_gate` tests; `_stub_app` gains the new attrs |
| `tests/test_enhancement_dialog_ui.py` | modify | `_make_app` double gains `annotation_palette=None` (gate access in `cmd_enhancement_dialog`) |

---

### Task 1: `image_model.apply_overlay`

**Files:** Modify `src/pxv/image_model.py` (insert between `resize`, lines 283–288, and `reset`, line 290); modify `tests/test_image_model.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_image_model.py`:

```python
# --- apply_overlay (annotation bake) ------------------------------------------


def _dot_overlay(size: tuple[int, int]) -> Image.Image:
    """Transparent RGBA overlay with one opaque and one half-alpha red pixel."""
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay.putpixel((1, 1), (255, 0, 0, 255))
    overlay.putpixel((2, 1), (255, 0, 0, 128))
    return overlay


def test_apply_overlay_paints_working_image() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 4), (0, 0, 255))
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model.working_image is not None
    assert model.working_image.getpixel((1, 1)) == (255, 0, 0)  # opaque replaces
    r, g, b = model.working_image.getpixel((2, 1))  # type: ignore[misc]
    assert 126 <= r <= 130 and g == 0 and 124 <= b <= 129  # ~50% red over blue
    assert model.working_image.getpixel((0, 0)) == (0, 0, 255)  # untouched elsewhere


def test_apply_overlay_keeps_buffers_in_lockstep() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 4), (0, 0, 255))
    model._save_rgba = Image.new("RGBA", (4, 4), (0, 0, 255, 200))
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model._save_rgba is not None
    assert model._save_rgba.getpixel((1, 1)) == (255, 0, 0, 255)
    assert model._save_rgba.getpixel((0, 0)) == (0, 0, 255, 200)  # alpha intact


def test_apply_overlay_opaque_image_keeps_no_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 4), (0, 0, 255))
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model._save_rgba is None


def test_apply_overlay_replaces_buffer_objects() -> None:
    # Consumers key caches on working_image object identity (enhancement-dialog
    # input histograms, the annotation stale-image guard) — see the method note.
    model = ImageModel()
    working_before = Image.new("RGB", (4, 4), (0, 0, 255))
    rgba_before = Image.new("RGBA", (4, 4), (0, 0, 255, 255))
    model.working_image = working_before
    model._save_rgba = rgba_before
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model.working_image is not working_before
    assert model._save_rgba is not rgba_before


def test_apply_overlay_no_image_is_noop() -> None:
    model = ImageModel()
    model.apply_overlay(Image.new("RGBA", (4, 4), (0, 0, 0, 0)))
    assert model.working_image is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_image_model.py -v`
Expected: 5 new tests FAIL (`AttributeError: 'ImageModel' object has no attribute 'apply_overlay'`)

- [ ] **Step 3: Write the implementation**

In `src/pxv/image_model.py`, after `resize` (ends line 288: `self._save_rgba = self._save_rgba.resize(new_size, Image.Resampling.LANCZOS)`) and before `def reset(self) -> None:` (line 290), insert:

```python
    def apply_overlay(self, overlay: Image.Image) -> None:
        """Alpha-composite a full-resolution RGBA overlay onto both buffers.

        AIDEV-NOTE: The annotation-bake mutator (2026-06-10 design).
        working_image (RGB) takes a paste-with-mask; _save_rgba, when present,
        takes a proper RGBA alpha_composite — in lockstep, so annotations
        survive alpha-preserving saves of transparent images. Both buffers are
        REPLACED, never mutated in place: consumers key caches on
        working_image object identity (the enhancement dialog's input
        histograms, the annotation stale-image guard), and every other
        mutator in this class replaces the object too.
        """
        if self.working_image is None:
            return
        base = self.working_image.copy()
        base.paste(overlay, (0, 0), overlay)
        self.working_image = base
        if self._save_rgba is not None:
            self._save_rgba = Image.alpha_composite(self._save_rgba, overlay)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_image_model.py -v`
Expected: 36 PASS (31 existing + 5 new)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/image_model.py tests/test_image_model.py
uv run mypy src/pxv
git add src/pxv/image_model.py tests/test_image_model.py
git commit -m "feat(draw): ImageModel.apply_overlay composites annotations onto both buffers

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `canvas_view.py` — session multiplexing, pencil cursor, drag preview, wheel gating

**Files:** Modify `src/pxv/canvas_view.py`; create `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_annotation_mode.py`:

```python
"""DISPLAY-gated tests for draw mode: canvas plumbing, palette, gating, prompts.

AIDEV-NOTE: Real Tk widgets — skipped headlessly like test_enhancement_dialog_ui.
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


class _RecordingSession:
    """Minimal stand-in satisfying the canvas-facing AnnotationSession protocol."""

    def __init__(self) -> None:
        self.events: list[tuple[str, tuple[float, float]]] = []
        self.dragging = False

    @property
    def is_dragging(self) -> bool:
        return self.dragging

    def on_press(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("press", image_xy))

    def on_drag(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("drag", image_xy))

    def on_release(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("release", image_xy))


def _canvas_view(root):  # noqa: ANN001, ANN202 - Tk fixture helper
    """A bare 300x300 CanvasView pretending to show a 100x100 image at zoom 1."""
    from pxv.canvas_view import CanvasView

    view = CanvasView(root)
    view.canvas.config(width=300, height=300)
    root.update()  # an unmapped canvas reports winfo_width() == 1
    view._display_width = 100
    view._display_height = 100
    view.zoom = 1.0
    return view


def test_session_armed_forwards_events_and_suppresses_rubber_band() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        session = _RecordingSession()
        view.set_annotation_session(session)
        assert view.canvas.cget("cursor") == "pencil"
        view._on_press(types.SimpleNamespace(x=150, y=150))
        view._on_drag(types.SimpleNamespace(x=180, y=160))
        view._on_release(types.SimpleNamespace(x=180, y=160))
        # 300x300 canvas, 100x100 display at zoom 1 -> centering offset 100.
        assert session.events == [
            ("press", (50.0, 50.0)),
            ("drag", (80.0, 60.0)),
            ("release", (80.0, 60.0)),
        ]
        assert view._rb_start is None and not view.has_selection()
    finally:
        root.destroy()


def test_session_entry_clears_selection_and_exit_restores_cursor() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view._selection = (10, 10, 50, 50)
        view.set_annotation_session(_RecordingSession())
        assert not view.has_selection()  # stale canvas coords never survive entry
        view.set_annotation_session(None)
        assert view.canvas.cget("cursor") == "crosshair"
        # Disarmed: events run the normal rubber-band path again.
        view._on_press(types.SimpleNamespace(x=10, y=10))
        assert view._rb_start is not None
    finally:
        root.destroy()


def test_preview_shape_converts_image_space_and_is_single_item() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_preview_shape("line", [(0.0, 0.0), (50.0, 50.0)], "#ff0000", 2.0)
        assert view._preview_id is not None
        # Image (0,0)/(50,50) -> canvas (100,100)/(150,150) via the centering offset.
        assert view.canvas.coords(view._preview_id) == [100.0, 100.0, 150.0, 150.0]
        first_id = view._preview_id
        view.set_preview_shape("rect", [(0.0, 0.0), (10.0, 10.0)], "#00ff00", 2.0)
        assert view._preview_id != first_id
        assert len(view.canvas.find_withtag("all")) == 1  # ONE item: old one deleted
        view.clear_preview()
        assert view._preview_id is None
        assert len(view.canvas.find_withtag("all")) == 0
    finally:
        root.destroy()


def test_wheel_ignored_while_session_drag_in_flight() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        session = _RecordingSession()
        view.set_annotation_session(session)
        scrolls: list[tuple[int, str]] = []
        view.canvas.yview_scroll = lambda n, what: scrolls.append((n, what))  # type: ignore[method-assign]
        session.dragging = True
        assert view._on_mouse_wheel(types.SimpleNamespace(num=4, delta=0, state=0)) == "break"
        assert scrolls == []  # the wheel is pxv's only pan input: dead mid-drag
        session.dragging = False
        view._on_mouse_wheel(types.SimpleNamespace(num=4, delta=0, state=0))
        assert scrolls == [(-1, "units")]
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 4 FAIL (`AttributeError: 'CanvasView' object has no attribute 'set_annotation_session'`)

- [ ] **Step 3: Write the implementation**

All edits in `src/pxv/canvas_view.py`.

(a) Extend the typing import (line 14 pre-Phase-1: `from typing import TYPE_CHECKING`) and the collections import (line 13: `from collections.abc import Callable`) to:

```python
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal, Protocol
```

(b) Immediately before `class CanvasView:` (after Phase 1's `image_xy_to_canvas_point` helper), insert:

```python
class AnnotationSession(Protocol):
    """What CanvasView needs from the draw-mode session (the palette).

    AIDEV-NOTE: A Protocol instead of importing AnnotationPalette — the
    palette already depends on the app, which owns this view, so a real import
    would be circular. The full session protocol additionally includes
    render_display_overlay(target_size, scale), which the APP consumes in its
    display-composite hook, not this view.
    """

    @property
    def is_dragging(self) -> bool: ...

    def on_press(self, image_xy: tuple[float, float]) -> None: ...

    def on_drag(self, image_xy: tuple[float, float]) -> None: ...

    def on_release(self, image_xy: tuple[float, float]) -> None: ...
```

(c) In `__init__`, after the pick-mode state (post-Phase-1 ~lines 154–157):

```python
        # One-shot eyedropper pick mode (None = normal rubber-band behavior).
        self._pick_callback: Callable[[tuple[int, int] | None], None] | None = None
        self._pick_working_size: tuple[int, int] | None = None
```

append:

```python
        # Draw-mode session (None = normal behavior). While set, mouse events
        # forward image-space float coords to it instead of the rubber band.
        self._annotation_session: AnnotationSession | None = None
        # The single transient drag-preview item (draw mode).
        self._preview_id: int | None = None
```

(d) After `set_pick_callback` (post-Phase-1 ~line 264, ends `self.canvas.config(cursor="tcross" if callback is not None else "crosshair")`), insert:

```python
    def set_annotation_session(self, session: AnnotationSession | None) -> None:
        """Arm (or disarm with None) draw-mode event forwarding.

        AIDEV-NOTE: Entering clears any rubber-band selection (selection
        handling is suspended for the whole session) and shows the pencil
        cursor — the canvas is already crosshair normally, so the mode is
        visually distinct. Disarming clears the transient preview item; the
        palette calls this FIRST in _end_session (the eyedropper _on_close
        pattern), so no event can reach a dying session.
        """
        self._annotation_session = session
        if session is not None:
            self.clear_selection()
            self.canvas.config(cursor="pencil")
        else:
            self.clear_preview()
            self.canvas.config(cursor="crosshair")

    def _event_image_xy(self, event: tk.Event) -> tuple[float, float]:
        """Per-event canvas->image conversion for the annotation session.

        Scroll-aware, float precision, UNCLAMPED — out-of-image points pass
        through; clipping happens at render time (2026-06-10 design).
        """
        cx = self.canvas.canvasx(event.x)  # type: ignore[no-untyped-call]
        cy = self.canvas.canvasy(event.y)  # type: ignore[no-untyped-call]
        return canvas_point_to_image_xy_f(
            (float(cx), float(cy)),
            (self._display_width, self._display_height),
            (self.canvas.winfo_width(), self.canvas.winfo_height()),
            self.zoom,
        )

    def set_preview_shape(
        self,
        kind: Literal["polyline", "line", "arrow", "rect", "ellipse"],
        points: Sequence[tuple[float, float]],
        color: str,
        width_px: float,
    ) -> None:
        """Draw/replace the single transient drag-preview Tk item.

        AIDEV-NOTE: points are IMAGE-space floats (the session's source of
        truth), converted through image_xy_to_canvas_point HERE so callers
        never hold canvas coords (which go stale on zoom/pan/resize). Only the
        in-flight drag uses a Tk item — Tk items cannot do per-item alpha —
        and it is swapped for the exact PIL render at release.
        """
        self.clear_preview()
        disp = (self._display_width, self._display_height)
        csize = (self.canvas.winfo_width(), self.canvas.winfo_height())
        pts = [image_xy_to_canvas_point(p, disp, csize, self.zoom) for p in points]
        if len(pts) == 1:
            pts = pts * 2  # create_line needs two points; a click previews a dot
        flat = [coord for point in pts for coord in point]
        width = max(1, round(width_px * self.zoom))
        if kind in ("polyline", "line", "arrow"):
            # Head sized to mirror annotation_render.arrow_head's length rule.
            head = max(3.0 * width_px, 8.0) * self.zoom
            self._preview_id = self.canvas.create_line(
                *flat,
                fill=color,
                width=width,
                arrow=tk.LAST if kind == "arrow" else tk.NONE,
                arrowshape=(head, head, head / 2),
            )
        elif kind == "rect":
            self._preview_id = self.canvas.create_rectangle(*flat, outline=color, width=width)
        else:
            self._preview_id = self.canvas.create_oval(*flat, outline=color, width=width)

    def clear_preview(self) -> None:
        """Remove the transient drag-preview item, if any."""
        if self._preview_id is not None:
            self.canvas.delete(self._preview_id)
            self._preview_id = None
```

(e) In `_on_press` (post-Phase-1 ~line 303), the method currently begins:

```python
    def _on_press(self, event: tk.Event) -> None:
        # AIDEV-NOTE: Take keyboard focus on click so the root-bound shortcuts are
        # re-armed if focus was somehow lost (defense in depth alongside
        # PxvApp.restore_main_focus). A real click means the main window is
        # gaining focus anyway, so cooperative focus_set suffices here.
        self.canvas.focus_set()
        # AIDEV-NOTE: Pick mode consumes this click entirely — no rubber band,
```

Insert between `self.canvas.focus_set()` and the pick-mode AIDEV-NOTE:

```python
        # AIDEV-NOTE: Draw mode multiplexes ahead of pick mode and the rubber
        # band — the session consumes the whole press/drag/release stream.
        # cmd_annotate and cmd_enhancement_dialog gate each other, so pick
        # mode and a session can never be armed at once.
        if self._annotation_session is not None:
            self._annotation_session.on_press(self._event_image_xy(event))
            return
```

(f) At the top of `_on_drag` (currently `if self._rb_start is None: return` is its first line) insert:

```python
        if self._annotation_session is not None:
            self._annotation_session.on_drag(self._event_image_xy(event))
            return
```

(g) At the top of `_on_release` (currently `if self._rb_start is None: return` is its first line) insert:

```python
        if self._annotation_session is not None:
            self._annotation_session.on_release(self._event_image_xy(event))
            return
```

(h) At the top of `_on_mouse_wheel` (its first line is `"""Pan the view with the scroll wheel (Shift = horizontal)."""`), insert after the docstring:

```python
        # AIDEV-NOTE: The wheel is pxv's only pan input; a view change mid-drag
        # would shear the stroke, so wheel events are ignored while an
        # annotation drag is in flight (zoom KEYS are consumed in commands.py;
        # per-event coordinate conversion remains as defense in depth).
        if self._annotation_session is not None and self._annotation_session.is_dragging:
            return "break"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_canvas_geometry.py -v`
Expected: 4 + 11 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/canvas_view.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/canvas_view.py tests/test_annotation_mode.py
git commit -m "feat(draw): canvas session multiplexing, pencil cursor, drag preview

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `annotation_palette.py` + app session state + `bake_annotations`

The palette and the app-side state land together because they type-reference each other (`app.annotation_palette: AnnotationPalette | None`, palette calls `app.bake_annotations`) — splitting them would leave mypy red between commits.

**Files:** Create `src/pxv/annotation_palette.py`; modify `src/pxv/app.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotation_mode.py`:

```python
def _make_app(tmp_path, count=1):  # noqa: ANN001, ANN201 - Tk fixture helper
    """Real PxvApp over `count` synthetic 100x80 PNGs, first one loaded (zoom 1)."""
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    colors = [(0, 0, 255), (0, 200, 0), (200, 200, 0)]
    paths = []
    for i in range(count):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (100, 80), colors[i % 3]).save(p)
        paths.append(p)
    root = tk.Tk()
    app = PxvApp(root, FileList(paths))
    root.update()
    app.load_current()
    root.update()
    assert app.canvas_view.zoom == 1.0  # the coordinate math below relies on it
    return app, root, paths


def _open_palette(app):  # noqa: ANN001, ANN202
    """Construct the palette directly (cmd_annotate arrives in a later task)."""
    from pxv.annotation_palette import AnnotationPalette

    palette = AnnotationPalette(app)
    app.annotation_palette = palette
    return palette


def _draw_line(palette, y=10.0):  # noqa: ANN001, ANN202
    """One committed red line (10,y)-(40,y) through the session protocol."""
    palette.select_tool_key("3")
    palette.on_press((10.0, y))
    palette.on_drag((40.0, y))
    palette.on_release((40.0, y))


def test_palette_arms_canvas_and_tears_down_through_end_session(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        assert app.canvas_view._annotation_session is palette
        assert app.canvas_view.canvas.cget("cursor") == "pencil"
        assert palette.layer.shapes == () and palette.tool == "freehand"
        assert palette.protocol("WM_DELETE_WINDOW")  # window close = Done is wired
        palette._end_session(bake=False)
        assert app.canvas_view._annotation_session is None
        assert app.annotation_palette is None
        assert not palette.winfo_exists()
    finally:
        root.destroy()


def test_session_press_drag_release_adds_shape_and_sets_flag(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("3")  # line
        assert app.annotations_unsaved is False
        palette.on_press((10.0, 10.0))
        assert palette.is_dragging
        palette.on_drag((40.0, 30.0))
        assert app.canvas_view._preview_id is not None  # rubber-band preview live
        palette.on_release((40.0, 30.0))
        assert not palette.is_dragging
        assert app.canvas_view._preview_id is None  # swapped for the PIL render
        (shape,) = palette.layer.shapes
        assert shape.tool == "line"
        assert shape.points == ((10.0, 10.0), (40.0, 30.0))
        assert shape.color == palette.color and shape.width_px == palette.width_px
        assert app.annotations_unsaved is True  # set on the first shape
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_freehand_accumulates_points(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)  # default tool is freehand
        palette.on_press((5.0, 5.0))
        palette.on_drag((10.0, 5.0))
        palette.on_drag((15.0, 8.0))
        palette.on_release((20.0, 10.0))
        (shape,) = palette.layer.shapes
        assert shape.tool == "freehand"
        assert shape.points == ((5.0, 5.0), (10.0, 5.0), (15.0, 8.0), (20.0, 10.0))
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tiny_drag_is_discarded(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.on_press((10.0, 10.0))
        palette.on_drag((11.0, 11.0))
        palette.on_release((11.0, 11.0))  # ~1.4 image px * zoom 1.0 < 3 screen px
        assert palette.layer.shapes == ()
        assert app.annotations_unsaved is False
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_escape_cancels_drag_with_latch_until_physical_release(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.on_press((10.0, 10.0))
        palette.on_drag((40.0, 40.0))
        palette.on_escape()
        assert not palette.is_dragging
        assert app.canvas_view._preview_id is None
        palette.on_drag((60.0, 60.0))  # swallowed by the latch
        assert app.canvas_view._preview_id is None
        palette.on_release((60.0, 60.0))  # the physical release: consumed, no shape
        assert palette.layer.shapes == ()
        palette.on_press((10.0, 10.0))  # latch is reset: drawing works again
        palette.on_drag((40.0, 40.0))
        palette.on_release((40.0, 40.0))
        assert len(palette.layer.shapes) == 1
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_done_bakes_exactly_one_history_snapshot(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("5")  # rect (outline)
        palette.on_press((10.0, 10.0))
        palette.on_drag((40.0, 40.0))
        palette.on_release((40.0, 40.0))
        before = app.image_model.working_image
        palette._on_done()
        assert app.annotation_palette is None
        assert len(app.history._undo) == 1  # ONE ordinary snapshot edit
        working = app.image_model.working_image
        assert working is not None and working is not before
        assert working.getpixel((10, 25)) == (255, 0, 0)  # left edge of the rect
        assert working.getpixel((25, 25)) == (0, 0, 255)  # hollow interior untouched
        assert app.annotations_unsaved is True  # set on bake, awaiting a save
    finally:
        root.destroy()


def test_done_with_empty_layer_records_nothing(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        before = app.image_model.working_image
        palette._on_done()
        assert app.annotation_palette is None
        assert not app.history.can_undo  # no snapshot for an empty bake
        assert app.image_model.working_image is before
        assert app.annotations_unsaved is False
    finally:
        root.destroy()


def test_cancel_prompts_then_discards(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        monkeypatch.setattr(
            "pxv.annotation_palette.messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: False),
        )
        palette._on_cancel()  # declined: still open, shape kept
        assert app.annotation_palette is palette and palette.winfo_exists()
        assert len(palette.layer.shapes) == 1
        monkeypatch.setattr(
            "pxv.annotation_palette.messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: True),
        )
        palette._on_cancel()
        assert app.annotation_palette is None
        assert not app.history.can_undo  # Cancel bakes nothing
        assert app.annotations_unsaved is False  # confirmed discard clears the flag
        working = app.image_model.working_image
        assert working is not None and working.getpixel((25, 10)) == (0, 0, 255)
    finally:
        root.destroy()


def test_undo_keys_swallowed_with_hint_while_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        app.record_history()  # a fall-through to app history would be visible
        palette.on_undo_key()
        assert "Select tool" in root.title()
        palette.on_redo_key()
        assert len(app.history._undo) == 1  # untouched
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_tool_keys_two_through_six_select_and_others_inert(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        for char, tool in (
            ("2", "freehand"),
            ("3", "line"),
            ("4", "arrow"),
            ("5", "rect"),
            ("6", "ellipse"),
        ):
            palette.select_tool_key(char)
            assert palette.tool == tool
            assert palette._tool_var.get() == tool  # button row follows
        for char in ("1", "7", "8"):  # unshipped phases: stable numbers, inert keys
            palette.select_tool_key(char)
        assert palette.tool == "ellipse"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_color_and_size_controls_style_new_shapes(tmp_path) -> None:  # noqa: ANN001
    from pxv.annotations import size_presets

    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.set_color("#00ff00")
        palette._size_var.set("thick")
        palette._on_size_selected()
        _draw_line(palette)
        (shape,) = palette.layer.shapes
        assert shape.color == "#00ff00"
        assert shape.width_px == size_presets(100).widths[2]  # long side = 100
        assert palette._color_indicator.cget("bg") == "#00ff00"
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 11 new FAIL (`ModuleNotFoundError: No module named 'pxv.annotation_palette'`); the 4 Task-2 tests still PASS

- [ ] **Step 3: Modify `src/pxv/app.py` (session state + bake)**

(a) Add the runtime import after `from pxv import commands` (line 16):

```python
from pxv.annotation_render import render_overlay
```

and extend the TYPE_CHECKING block (lines 27–30) to:

```python
if TYPE_CHECKING:
    from collections.abc import Sequence

    from pxv.annotation_palette import AnnotationPalette
    from pxv.annotations import Shape
    from pxv.enhancement_dialog import EnhancementDialog
    from pxv.info_dialog import InfoDialog
    from pxv.thumbnail_browser import BrowserWindow
```

(b) In `__init__`, after line 98 (`self.enhancement_dialog: EnhancementDialog | None = None`), insert:

```python
        # Will be set if the drawing palette (draw mode) is open
        self.annotation_palette: AnnotationPalette | None = None
        # AIDEV-NOTE: Annotation-specific dirty flag (2026-06-10 design) — set
        # on the first shape and on bake; cleared by a successful save, a
        # confirmed discard prompt, and load_current. Other edits keep pxv's
        # historical silent-discard behavior.
        self.annotations_unsaved: bool = False
```

(c) In `load_current`, after line 266 (`self.history.clear()`), insert:

```python
        self.annotations_unsaved = False
```

(d) After `record_history` (ends line 330: `self.history.record(snap)`), insert:

```python
    # --- annotations (draw mode) -----------------------------------------

    def bake_annotations(self, shapes: Sequence[Shape]) -> None:
        """Rasterize shapes into the image pixels as ONE undoable edit.

        The crop/rotate command pattern: snapshot, mutate, refresh. An empty
        layer exits silently with no history snapshot (checked up front, so
        autocrop's conditional-snapshot dance is not needed).

        AIDEV-NOTE: The bake composites onto the PRE-enhancement working
        image, while the preview composited onto the post-enhancement display
        — parity holds exactly when EnhancementParams is identity (the common
        case). With live non-identity params the annotation pixels become
        subject to the enhancement pass from here on: colors visibly shift at
        Done and in the saved file. Accepted in the 2026-06-10 design — do
        NOT "fix" this by inverse-mapping colors.
        """
        working = self.image_model.working_image
        if working is None or not shapes:
            return
        self.record_history()
        overlay = render_overlay(shapes, working.size, 1.0)
        self.image_model.apply_overlay(overlay)
        self.annotations_unsaved = True
        self.refresh_display()
```

- [ ] **Step 4: Create `src/pxv/annotation_palette.py`**

```python
"""Drawing palette window: the draw-mode session controller.

AIDEV-NOTE: Palette open <=> draw mode active. Every path that ends the mode
funnels through _end_session(bake), which disarms the canvas FIRST (the
eyedropper _on_close pattern) and destroys this window — that single funnel
is what keeps stray events and orphaned overlays impossible. The shape model
lives in annotations.py (pure) and rasterization in annotation_render.py
(pure PIL); this module is only the Tk shell and session state.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from typing import TYPE_CHECKING, cast

from pxv.annotation_render import render_overlay
from pxv.annotations import AnnotationLayer, Shape, Tool, size_presets

if TYPE_CHECKING:
    from PIL import Image

    from pxv.app import PxvApp

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

_PREVIEW_KINDS: dict[Tool, str] = {
    "freehand": "polyline",
    "line": "line",
    "arrow": "arrow",
    "rect": "rect",
    "ellipse": "ellipse",
}

# Preset swatches: red, yellow, green, blue, white, black (spec order).
SWATCHES = ("#ff0000", "#ffff00", "#00ff00", "#0000ff", "#ffffff", "#000000")

# Drags shorter than this (screen px, Euclidean) are accidents, not shapes.
MIN_DRAG_SCREEN_PX = 3.0

_STALE_MESSAGE = "pxv: drawing cancelled — image changed"


class AnnotationPalette(tk.Toplevel):
    """Tool palette Toplevel owning the AnnotationLayer and the draw session."""

    def __init__(self, app: PxvApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Draw")
        self.resizable(False, False)
        self.transient(app.root)

        self.layer = AnnotationLayer()
        # AIDEV-NOTE: Stale-image guard anchor — the session draws against
        # THIS working_image object. Every model mutator replaces the object,
        # so an identity mismatch means the image changed under the session
        # through some unguarded path (the known paths are gated in
        # commands.py); checked before compositing and at bake start.
        self._session_image = app.image_model.working_image
        # (layer.revision, display_size) -> rendered RGBA display overlay.
        self._overlay_cache: tuple[tuple[int, tuple[int, int]], Image.Image] | None = None

        # Styling state for NEW shapes (restyling a selection arrives in Phase 3).
        self._presets = size_presets(max(app.image_model.get_working_size()))
        self.tool: Tool = "freehand"
        self.color: str = SWATCHES[0]
        self.width_px: float = self._presets.widths[1]  # medium

        # In-flight drag: accumulated image-space points, or None.
        self._drag_points: list[tuple[float, float]] | None = None
        # Escape latch: swallow motion/release until the physical ButtonRelease.
        self._cancel_latch = False

        self._tool_var = tk.StringVar(value=self.tool)
        self._size_var = tk.StringVar(value="medium")
        self._build_ui()
        self._bind_keys()

        # Window close is a deliberate Done (2026-06-10 design).
        self.protocol("WM_DELETE_WINDOW", self._on_done)

        # Arm the canvas LAST: everything the event stream needs exists now.
        app.canvas_view.set_annotation_session(self)

        # Position near the parent (enhancement-dialog convention).
        self.update_idletasks()
        px = app.root.winfo_x() + app.root.winfo_width() + 10
        py = app.root.winfo_y()
        self.geometry(f"+{px}+{py}")

    # --- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        tools = ttk.LabelFrame(main, text="Tools", padding=6)
        tools.pack(fill=tk.X)
        self._tool_buttons: dict[str, ttk.Radiobutton] = {}
        for key, label, shipped in (
            ("1", "Select", False),
            ("2", "Freehand", True),
            ("3", "Line", True),
            ("4", "Arrow", True),
            ("5", "Rect", True),
            ("6", "Ellipse", True),
            ("7", "Highlight", False),
            ("8", "Text", False),
        ):
            btn = ttk.Radiobutton(
                tools,
                text=f"{key} {label}",
                value=TOOL_KEYS.get(key, label.lower()),
                variable=self._tool_var,
                command=self._on_tool_selected,
            )
            if not shipped:
                btn.configure(state=tk.DISABLED)
            row, col = divmod(len(self._tool_buttons), 4)
            btn.grid(row=row, column=col, sticky=tk.W, padx=2, pady=2)
            self._tool_buttons[key] = btn

        colors = ttk.LabelFrame(main, text="Color", padding=6)
        colors.pack(fill=tk.X, pady=(6, 0))
        for col, swatch in enumerate(SWATCHES):
            tk.Button(
                colors,
                bg=swatch,
                activebackground=swatch,
                width=2,
                command=lambda c=swatch: self.set_color(c),
            ).grid(row=0, column=col, padx=2)
        ttk.Button(colors, text="Custom…", width=8, command=self._on_custom_color).grid(
            row=0, column=len(SWATCHES), padx=(8, 2)
        )
        self._color_indicator = tk.Frame(colors, bg=self.color, width=24, height=24)
        self._color_indicator.grid(row=0, column=len(SWATCHES) + 1, padx=(8, 2))

        sizes = ttk.LabelFrame(main, text="Size", padding=6)
        sizes.pack(fill=tk.X, pady=(6, 0))
        for col, key in enumerate(("thin", "medium", "thick")):
            ttk.Radiobutton(
                sizes,
                text=key.capitalize(),
                value=key,
                variable=self._size_var,
                command=self._on_size_selected,
            ).grid(row=0, column=col, padx=4)

        btns = ttk.Frame(main)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Done", command=self._on_done, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self._on_cancel, width=8).pack(
            side=tk.LEFT, padx=4
        )

    def _bind_keys(self) -> None:
        # AIDEV-NOTE: Root-bound keys only fire while the canvas holds focus
        # (the root-bindings note in app.py); after clicking a palette control
        # THIS window holds it, so the in-mode keys are mirrored here.
        # Navigation/save keys are intentionally NOT mirrored — they must keep
        # prompting through the root chokepoint in commands.py.
        for digit in "12345678":
            self.bind(f"<Key-{digit}>", self._on_tool_key_event)
        self.bind("<Key-u>", lambda _e: self.on_undo_key())
        self.bind("<Control-z>", lambda _e: self.on_undo_key())
        self.bind("<Control-y>", lambda _e: self.on_redo_key())
        self.bind("<Control-Shift-Z>", lambda _e: self.on_redo_key())
        self.bind("<Delete>", lambda _e: self.on_delete_key())
        self.bind("<Escape>", lambda _e: self.on_escape())

    def _on_tool_key_event(self, event: tk.Event) -> None:
        self.select_tool_key(event.char)

    # --- styling controls ---------------------------------------------------

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

    # --- session protocol (called by CanvasView and the app) ----------------

    @property
    def is_dragging(self) -> bool:
        return self._drag_points is not None

    def on_press(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            return
        self._drag_points = [image_xy]

    def on_drag(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch or self._drag_points is None:
            return
        if self.tool == "freehand":
            self._drag_points.append(image_xy)
        else:
            self._drag_points = [self._drag_points[0], image_xy]
        self.app.canvas_view.set_preview_shape(
            _PREVIEW_KINDS[self.tool],  # type: ignore[arg-type]
            self._drag_points,
            self.color,
            self.width_px,
        )

    def on_release(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            # The physical ButtonRelease of an Escape-cancelled drag re-arms us.
            self._cancel_latch = False
            return
        if self._drag_points is None:
            return
        points = self._drag_points
        self._drag_points = None
        self.app.canvas_view.clear_preview()
        if self.tool == "freehand":
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
            Shape(tool=self.tool, points=tuple(points), color=self.color, width_px=self.width_px)
        )
        self.app.annotations_unsaved = True  # set on the first shape (and kept)
        self.app.refresh_display()

    def render_display_overlay(self, target_size: tuple[int, int], scale: float) -> Image.Image:
        """The committed shapes rendered as an RGBA overlay at display size.

        AIDEV-NOTE: Cache key is (layer.revision, target_size) — revision
        bumps on every shape mutation. Only the OVERLAY is cached: the base
        display image changes under the same key (enhancement debounce,
        Compare, background toggle), so the app composites onto a fresh base
        every refresh (2026-06-10 design).
        """
        key = (self.layer.revision, target_size)
        if self._overlay_cache is None or self._overlay_cache[0] != key:
            self._overlay_cache = (key, render_overlay(self.layer.shapes, target_size, scale))
        return self._overlay_cache[1]

    # --- in-mode keys --------------------------------------------------------

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

    def on_delete_key(self) -> None:
        """Delete the selected shape (selection ships in Phase 3; no-op now)."""
        if self.layer.selected is None:
            return
        self.layer.delete_selected()
        self.app.refresh_display()

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

    # --- session end -----------------------------------------------------

    def image_is_current(self) -> bool:
        """Stale-image guard predicate (see _session_image)."""
        return self.app.image_model.working_image is self._session_image

    def cancel_stale(self) -> None:
        """Guard trip from the composite hook: discard the session, no prompt.

        AIDEV-NOTE: The guard trips INSIDE a display path; the OUTER
        refresh's trailing _update_title would clobber an immediate temp
        title, so the message is deferred until that render completes.
        """
        self._end_session(bake=False)
        self.app.root.after_idle(lambda: self.app.show_temp_title(_STALE_MESSAGE))

    def _on_done(self) -> None:
        self._end_session(bake=True)

    def _on_cancel(self) -> None:
        if self.layer.shapes:
            if not messagebox.askyesno("pxv", "Discard annotations?", parent=self):
                return
            # A confirmed discard clears the dirty flag (2026-06-10 lifecycle).
            self.app.annotations_unsaved = False
        self._end_session(bake=False)

    def _end_session(self, bake: bool) -> None:
        """The ONE teardown path — every way out of draw mode goes through here.

        Disarms the canvas FIRST (the eyedropper _on_close pattern) so no
        event can reach a dying session, then destroys the window, keeping the
        palette-open <=> mode-active invariant.
        """
        self.app.canvas_view.set_annotation_session(None)
        shapes = self.layer.shapes
        stale = bake and not self.image_is_current()
        if stale:
            # Stale-image guard at bake start: never bake against the wrong image.
            bake = False
        self.app.annotation_palette = None
        self.destroy()
        self.app.restore_main_focus()
        if bake and shapes:
            self.app.bake_annotations(shapes)  # refreshes the display itself
        else:
            # Drop the composited overlay (and any preview) from the screen.
            self.app.refresh_display()
        if stale:
            # AIDEV-NOTE: AFTER the refresh — _update_title at the end of the
            # display paths would clobber an earlier temp title.
            self.app.show_temp_title(_STALE_MESSAGE)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 15 PASS (4 + 11)

- [ ] **Step 6: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py src/pxv/app.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py src/pxv/app.py tests/test_annotation_mode.py
git commit -m "feat(draw): AnnotationPalette session window with bake-on-Done

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Shared display-composite hook in BOTH display paths + stale-image guard

**Files:** Modify `src/pxv/app.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotation_mode.py`:

```python
def test_overlay_composites_in_both_display_paths(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        shown: list[Image.Image] = []
        monkeypatch.setattr(app.canvas_view, "display", shown.append)
        app.refresh_display()
        assert shown[-1].getpixel((25, 10)) == (255, 0, 0)  # overlay on the preview
        shown.clear()
        app._update_display()  # the window-resize path: same shared hook
        assert shown[-1].getpixel((25, 10)) == (255, 0, 0)
        assert shown[-1].getpixel((25, 40)) == (0, 0, 255)  # base shows elsewhere
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_overlay_cache_keyed_on_revision_and_size(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        o1 = palette.render_display_overlay((100, 80), 1.0)
        assert palette.render_display_overlay((100, 80), 1.0) is o1  # cache hit
        o2 = palette.render_display_overlay((50, 40), 0.5)  # zoom change: new size
        assert o2 is not o1 and o2.size == (50, 40)
        _draw_line(palette, y=30.0)  # layer.revision bump invalidates
        assert palette.render_display_overlay((50, 40), 0.5) is not o2
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_stale_image_guard_cancels_session_at_composite(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        # An unguarded surprise replaces the image under the session:
        app.image_model.working_image = Image.new("RGB", (100, 80), (9, 9, 9))
        app.refresh_display()
        root.update()  # flush the deferred stale-message after_idle
        assert app.annotation_palette is None  # guard tore the session down
        assert not palette.winfo_exists()
        assert "image changed" in root.title()
        assert not app.history.can_undo  # and nothing was baked
    finally:
        root.destroy()


def test_stale_image_guard_blocks_bake_at_done(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette)
        app.image_model.working_image = Image.new("RGB", (100, 80), (9, 9, 9))
        palette._on_done()
        assert app.annotation_palette is None
        assert not app.history.can_undo
        working = app.image_model.working_image
        assert working is not None
        assert working.getpixel((25, 10)) == (9, 9, 9)  # never baked the wrong image
        assert "image changed" in root.title()
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: `test_overlay_composites_in_both_display_paths` and `test_stale_image_guard_cancels_session_at_composite` FAIL (no composite hook / no guard trip on refresh); the other two PASS already (Task 3 shipped the cache and the bake-start guard) — they pin that behavior here.

- [ ] **Step 3: Write the implementation**

All edits in `src/pxv/app.py`.

(a) Add `Image` to the TYPE_CHECKING block (extended in Task 3):

```python
    from PIL import Image
```

(b) Insert the hook after `_active_params` (ends line 372 pre-Task-3: `return EnhancementParams() if self._compare_active else self.enhancement_params`) and before `refresh_display`:

```python
    def _composite_annotations(self, display_img: Image.Image | None) -> Image.Image | None:
        """Composite the live annotation overlay onto a fresh display render.

        AIDEV-NOTE: The ONE composite hook shared by refresh_display and
        _update_display — without the resize path, shapes would vanish on
        window resize. Only the rendered overlay is cached (in the palette,
        keyed on (layer.revision, display size)); the composite happens fresh
        every call because the base changes under the same key (enhancement
        debounce, Compare, background toggle). Also the stale-image guard's
        first checkpoint: never composite against a replaced image.
        """
        palette = self.annotation_palette
        if display_img is None or palette is None or not palette.layer.shapes:
            return display_img
        if not palette.image_is_current():
            palette.cancel_stale()  # tears down + refreshes; skip the overlay
            return display_img
        overlay = palette.render_display_overlay(display_img.size, self.canvas_view.zoom)
        display_img.paste(overlay, (0, 0), overlay)
        return display_img
```

(c) In `refresh_display` (lines 374–393), after the `get_display_image(...)` call:

```python
        display_img = self.image_model.get_display_image(
            zoom=self.canvas_view.zoom,
            params=self._active_params(),
            bg_color=self._bg_color(),
        )
```

insert:

```python
        display_img = self._composite_annotations(display_img)
```

(d) In `_update_display` (lines 405–416), after its identical `get_display_image(...)` call, insert the same line:

```python
        display_img = self._composite_annotations(display_img)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 19 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/app.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/app.py tests/test_annotation_mode.py
git commit -m "feat(draw): shared overlay composite in both display paths with stale guard

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `cmd_annotate`, the `d` key, and root tool keys

**Files:** Modify `src/pxv/commands.py`; modify `src/pxv/app.py` (`_bind_keys`); modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotation_mode.py` (add `from pxv import commands` to the imports at the top of the file, after `from PIL import Image`):

```python
def test_cmd_annotate_opens_then_raises_never_closes(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        assert app.canvas_view._annotation_session is palette
        commands.cmd_annotate(app)  # `d` again: raise + focus, never close or bake
        assert app.annotation_palette is palette and palette.winfo_exists()
        assert not app.history.can_undo
        palette._on_done()
    finally:
        root.destroy()


def test_cmd_annotate_without_image_is_noop() -> None:
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    root = tk.Tk()
    try:
        app = PxvApp(root, FileList([]))
        commands.cmd_annotate(app)
        assert app.annotation_palette is None
    finally:
        root.destroy()


def test_cmd_annotate_gated_while_enhance_dialog_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_enhancement_dialog(app)
        assert app.enhancement_dialog is not None
        commands.cmd_annotate(app)
        assert app.annotation_palette is None  # pick mode and draw mode never coexist
        assert "Enhancements" in root.title()
        app.enhancement_dialog._on_close()
        commands.cmd_annotate(app)
        assert app.annotation_palette is not None
        app.annotation_palette._on_done()
    finally:
        root.destroy()


def test_cmd_annotate_stops_active_slideshow(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        app.start_slideshow()
        assert app.slideshow_active
        commands.cmd_annotate(app)
        assert not app.slideshow_active
        assert app.annotation_palette is not None
        app.annotation_palette._on_done()
    finally:
        root.destroy()


def test_root_tool_keys_route_to_palette_when_open(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        app._on_tool_key(types.SimpleNamespace(char="4"))  # closed: inert
        commands.cmd_annotate(app)
        app._on_tool_key(types.SimpleNamespace(char="4"))
        assert app.annotation_palette is not None
        assert app.annotation_palette.tool == "arrow"
        app.annotation_palette._on_done()
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 5 new FAIL (`AttributeError: module 'pxv.commands' has no attribute 'cmd_annotate'`)

- [ ] **Step 3: Write the implementation**

(a) In `src/pxv/commands.py`, after `cmd_enhancement_dialog` (ends line 450: `app.refresh_display()`), insert:

```python
def cmd_annotate(app: PxvApp) -> None:
    """Open the drawing palette (draw mode), or raise/focus it if already open.

    AIDEV-NOTE: `d` with the palette open never closes or bakes — it raises
    and focuses (the enhancement-dialog precedent). Draw mode and the Enhance
    dialog gate each other so eyedropper pick mode and the drawing session
    can never share the canvas. Opening stops an active slideshow.
    """
    if app.annotation_palette is not None:
        try:
            app.annotation_palette.deiconify()
            app.annotation_palette.lift()
            app.annotation_palette.focus_set()
            return
        except Exception:
            app.annotation_palette = None

    if app.image_model.working_image is None:
        return
    if app.enhancement_dialog is not None:
        app.show_temp_title("pxv: close the Enhancements dialog first")
        return

    from pxv.annotation_palette import AnnotationPalette

    app.stop_slideshow()  # a safe no-op when not running
    app.annotation_palette = AnnotationPalette(app)
```

(b) In `src/pxv/app.py` `_bind_keys` (lines 165–198), after line 180 (`self.root.bind("<Key-D>", lambda _: commands.cmd_toggle_background(self))`), insert:

```python
        self.root.bind("<Key-d>", lambda _: commands.cmd_annotate(self))
        # AIDEV-NOTE: 1-8 select drawing tools, gated to draw-mode-active here
        # (the palette mirrors them for when IT holds focus); inert otherwise.
        for digit in "12345678":
            self.root.bind(f"<Key-{digit}>", self._on_tool_key)
```

(c) Still in `app.py`, add the handler after `_bind_configure` (ends line 202: `self.canvas_view.canvas.bind("<Configure>", self._on_configure)`):

```python
    def _on_tool_key(self, event: tk.Event) -> None:
        """Root-level tool hotkeys (1-8): forwarded only while draw mode is active."""
        if self.annotation_palette is not None:
            self.annotation_palette.select_tool_key(event.char)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 24 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/commands.py src/pxv/app.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/commands.py src/pxv/app.py tests/test_annotation_mode.py
git commit -m "feat(draw): cmd_annotate on d with raise-focus, slideshow stop, tool hotkeys

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `annotation_gate` chokepoint — mutate/save hints, zoom-during-drag, undo/redo + Escape routing

**Files:** Modify `src/pxv/commands.py`; modify `tests/test_commands.py`; modify `tests/test_annotation_mode.py`; modify `tests/test_enhancement_dialog_ui.py` (one-line `_make_app` fix).

- [ ] **Step 1: Write the failing tests (pure)**

Append to `tests/test_commands.py`:

```python
# --- draw-mode command gating (annotation_gate) -------------------------------


class _StubPalette:
    def __init__(self, dragging: bool = False) -> None:
        self.is_dragging = dragging
        self.ended: list[bool] = []

    def _end_session(self, bake: bool) -> None:
        self.ended.append(bake)


def _gate_app(*, palette: object | None = None, unsaved: bool = False) -> SimpleNamespace:
    app = SimpleNamespace(
        annotation_palette=palette,
        annotations_unsaved=unsaved,
        titles=[],
    )
    app.show_temp_title = app.titles.append
    return app


def test_gate_mutate_consumes_with_hint_while_palette_open() -> None:
    app = _gate_app(palette=_StubPalette())
    assert commands.annotation_gate(app, "mutate") is False
    assert "drawing palette" in app.titles[0]
    assert commands.annotation_gate(_gate_app(), "mutate") is True


def test_gate_zoom_consumed_only_during_drag() -> None:
    assert commands.annotation_gate(_gate_app(palette=_StubPalette(dragging=True)), "zoom") is False
    assert commands.annotation_gate(_gate_app(palette=_StubPalette()), "zoom") is True
    assert commands.annotation_gate(_gate_app(), "zoom") is True


def test_gate_navigate_consumed_during_drag() -> None:
    app = _gate_app(palette=_StubPalette(dragging=True), unsaved=True)
    assert commands.annotation_gate(app, "navigate") is False
    assert app.annotations_unsaved is True  # no prompt, no teardown mid-drag


def test_gate_navigate_prompts_then_discards(monkeypatch: object) -> None:
    answers = iter([False, True])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        commands, "messagebox", SimpleNamespace(askyesno=lambda *a, **k: next(answers))
    )
    palette = _StubPalette()
    app = _gate_app(palette=palette, unsaved=True)
    assert commands.annotation_gate(app, "navigate") is False  # declined
    assert app.annotations_unsaved is True and palette.ended == []
    assert commands.annotation_gate(app, "navigate") is True  # confirmed
    assert app.annotations_unsaved is False
    assert palette.ended == [False]  # session cancelled, never baked


def test_gate_navigate_silently_ends_empty_session() -> None:
    palette = _StubPalette()
    app = _gate_app(palette=palette, unsaved=False)
    assert commands.annotation_gate(app, "navigate") is True  # nothing at stake
    assert palette.ended == [False]  # but no orphaned canvas state either


def test_gate_navigate_clears_post_bake_flag_without_session(monkeypatch: object) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        commands, "messagebox", SimpleNamespace(askyesno=lambda *a, **k: True)
    )
    app = _gate_app(palette=None, unsaved=True)  # baked, then closed the palette
    assert commands.annotation_gate(app, "navigate") is True
    assert app.annotations_unsaved is False  # no re-prompt on the next image
```

- [ ] **Step 2: Write the failing tests (DISPLAY-gated)**

Append to `tests/test_annotation_mode.py`:

```python
def test_gated_commands_show_hint_and_do_nothing(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        size_before = app.image_model.get_working_size()
        commands.cmd_rotate(app, 90)  # representative image-mutating command
        assert app.image_model.get_working_size() == size_before
        assert not app.history.can_undo
        assert "close the drawing palette" in root.title()
        commands.cmd_save_as(app)  # consumed before any dialog could open
        commands.cmd_enhancement_dialog(app)  # the e <-> d mutual gate, e side
        assert app.enhancement_dialog is None
        assert app.annotation_palette is not None
        app.annotation_palette._on_done()
    finally:
        root.destroy()


def test_undo_keys_route_to_palette_when_open_and_history_when_closed(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        app.record_history()
        commands.cmd_annotate(app)
        commands.cmd_undo(app)  # all entry points funnel through cmd_undo/cmd_redo
        assert "Select tool" in root.title()
        commands.cmd_redo(app)
        assert len(app.history._undo) == 1  # app history untouched while open
        app.annotation_palette._on_done()  # empty layer: silent exit
        commands.cmd_undo(app)  # closed: routes to app history again
        assert len(app.history._undo) == 0
    finally:
        root.destroy()


def test_zoom_consumed_during_drag_and_escape_never_leaves_mode(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        palette.on_press((10.0, 10.0))
        palette.on_drag((30.0, 30.0))
        zoom_before = app.canvas_view.zoom
        commands.cmd_zoom_increase(app)
        assert app.canvas_view.zoom == zoom_before  # consumed mid-drag
        palette.on_release((30.0, 30.0))
        commands.cmd_zoom_increase(app)
        assert app.canvas_view.zoom != zoom_before  # back to normal after release
        # Escape is consumed entirely by the session — never escape_action:
        app.start_slideshow()  # escape_action would stop it
        commands.cmd_escape(app)
        assert app.slideshow_active is True
        assert app.annotation_palette is palette  # and it never exits the mode
        app.stop_slideshow()
        palette._end_session(bake=False)  # not _on_cancel: one shape committed -> it would prompt
    finally:
        root.destroy()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_commands.py -v` → 6 new FAIL (`AttributeError: module 'pxv.commands' has no attribute 'annotation_gate'`)
Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v` → 3 new FAIL (rotate succeeds / undo hits history / zoom changes mid-drag)

- [ ] **Step 4: Write the implementation**

All edits in `src/pxv/commands.py`.

(a) Extend the typing import (line 13) to:

```python
from typing import TYPE_CHECKING, Literal
```

(b) Insert the chokepoint right after the `_OPEN_FILETYPES` block (ends line 53) and before `_resolve_save_format` (line 56):

```python
def annotation_gate(app: PxvApp, kind: Literal["mutate", "zoom", "navigate"]) -> bool:
    """Draw-mode chokepoint: may the calling command proceed?

    AIDEV-NOTE: ONE gate for the whole command surface (2026-06-10 design) —
    root keys and context-menu entries call the same cmd_* functions, so a
    single check at the top of each covers both. Kinds:
    - "mutate": image-mutating and save commands — consumed with a title hint
      while the palette is open.
    - "zoom": consumed only while an annotation drag is in flight.
    - "navigate": consumed during a drag; otherwise unsaved annotation work
      prompts "Discard annotations?" — confirming ends an active session,
      clears the flag, and proceeds. An open session with NOTHING at stake
      (empty layer, no unsaved bake) is silently torn down so navigation
      never orphans canvas state.
    Undo/redo and Escape do not come here: they route through the palette's
    on_undo_key/on_redo_key/on_escape (see cmd_undo/cmd_redo/cmd_escape).
    """
    palette = app.annotation_palette
    if kind == "mutate":
        if palette is not None:
            app.show_temp_title("pxv: close the drawing palette first")
            return False
        return True
    if palette is not None and palette.is_dragging:
        return False
    if kind == "zoom":
        return True
    # kind == "navigate"
    if app.annotations_unsaved:
        if not messagebox.askyesno("pxv", "Discard annotations?"):
            return False
        app.annotations_unsaved = False
    if palette is not None:
        palette._end_session(bake=False)
    return True
```

(c) Add the gate as the FIRST line of each mutate-class command body (after the docstring, before any other statement):

```python
    if not annotation_gate(app, "mutate"):
        return
```

into: `cmd_save_as` (line 119), `cmd_crop` (183), `cmd_resize` (196), `cmd_reset` (211), `cmd_rotate` (222), `cmd_flip_horizontal` (230), `cmd_flip_vertical` (237), `cmd_autocrop` (348), `cmd_enhancement_dialog` (435).

(d) Add the zoom gate as the FIRST line of each zoom command body:

```python
    if not annotation_gate(app, "zoom"):
        return
```

into: `cmd_zoom_normal` (302), `cmd_zoom_increase` (309), `cmd_zoom_reduce` (316), `cmd_zoom_double` (323), `cmd_zoom_halve` (330), `cmd_zoom_max` (337).

(e) Replace `cmd_undo` / `cmd_redo` (lines 365–372):

```python
def cmd_undo(app: PxvApp) -> None:
    """Undo the last destructive edit (crop, rotate, flip, resize, Apply).

    While draw mode is active, ALL undo entry points (u, Ctrl-z, context
    menu) land in the palette and never fall through to app history.
    """
    if app.annotation_palette is not None:
        app.annotation_palette.on_undo_key()
        return
    app.undo()


def cmd_redo(app: PxvApp) -> None:
    """Redo the last undone edit (palette-routed while draw mode is active)."""
    if app.annotation_palette is not None:
        app.annotation_palette.on_redo_key()
        return
    app.redo()
```

(f) Replace `cmd_escape` (lines 468–470):

```python
def cmd_escape(app: PxvApp) -> None:
    """Escape key: exit presentation modes if active, else clear the selection.

    While draw mode is active the session consumes Escape entirely (cancel an
    in-flight drag, never exit the mode) — leaving fullscreen mid-session is
    f/F11 (2026-06-10 design).
    """
    if app.annotation_palette is not None:
        app.annotation_palette.on_escape()
        return
    app.escape_action()
```

(g) In `tests/test_enhancement_dialog_ui.py`, `_make_app` (lines 68–93) builds a `SimpleNamespace` app double; `cmd_enhancement_dialog` now reads `app.annotation_palette` through the gate. Add one line to the `types.SimpleNamespace(` kwargs, after `enhancement_dialog=None,`:

```python
        annotation_palette=None,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_commands.py -v` → 10 PASS (4 existing + 6 new)
Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_enhancement_dialog_ui.py tests/test_undo_redo.py -v` → all PASS (27 + existing; `test_undo_redo` pins that gating leaves normal editing untouched)

- [ ] **Step 6: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/commands.py tests/test_commands.py tests/test_annotation_mode.py tests/test_enhancement_dialog_ui.py
uv run mypy src/pxv
git add src/pxv/commands.py tests/test_commands.py tests/test_annotation_mode.py tests/test_enhancement_dialog_ui.py
git commit -m "feat(draw): annotation_gate chokepoint — mutate/save hints, zoom and undo routing

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Navigation discard prompts, `cmd_save_as` success return, quit + root `WM_DELETE_WINDOW`

**Files:** Modify `src/pxv/commands.py`; modify `src/pxv/app.py`; modify `tests/test_commands.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests (pure)**

In `tests/test_commands.py`, first extend `_stub_app` (lines 12–21) — `cmd_show_index` and `cmd_next_image`/`cmd_prev_image` will consult the gate, so the double needs the attrs. Replace its `app = SimpleNamespace(...)` line with:

```python
    app = SimpleNamespace(
        file_list=fl,
        browser=None,
        load_current=load_current,
        annotation_palette=None,
        annotations_unsaved=False,
    )
```

Then append:

```python
def test_cmd_open_consumed_during_annotation_drag() -> None:
    app = SimpleNamespace(annotation_palette=_StubPalette(dragging=True), annotations_unsaved=False)
    # Must return before touching the file dialog — calling it headless would raise.
    commands.cmd_open(app)


def test_cmd_show_index_prompts_through_the_gate(monkeypatch: object) -> None:
    prompts: list[bool] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        commands, "messagebox", SimpleNamespace(askyesno=lambda *a, **k: prompts.append(True) or True)
    )
    app, loaded = _stub_app(3, load_ok=True)
    app.annotations_unsaved = True  # the Visual Schnauzer activation path is gated too
    commands.cmd_show_index(app, 2)
    assert prompts == [True]
    assert app.annotations_unsaved is False
    assert loaded == [2]
```

- [ ] **Step 2: Write the failing tests (DISPLAY-gated)**

Append to `tests/test_annotation_mode.py`:

```python
def test_navigation_prompts_discard_and_cancels_session(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        _draw_line(palette)
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: False)
        )
        commands.cmd_next_image(app)  # declined: fully consumed
        assert app.file_list.index == 0
        assert app.annotation_palette is palette and palette.winfo_exists()
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: True)
        )
        commands.cmd_next_image(app)  # confirmed: session cancelled, then proceed
        assert app.file_list.index == 1
        assert app.annotation_palette is None
        assert app.annotations_unsaved is False
        assert not app.history.can_undo  # cancelled, never baked
    finally:
        root.destroy()


def test_bake_navigate_confirm_then_navigate_does_not_reprompt(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=3)
    try:
        commands.cmd_annotate(app)
        _draw_line(app.annotation_palette)
        app.annotation_palette._on_done()  # bake sets annotations_unsaved
        prompts: list[bool] = []
        monkeypatch.setattr(
            commands,
            "messagebox",
            types.SimpleNamespace(askyesno=lambda *a, **k: prompts.append(True) or True),
        )
        commands.cmd_next_image(app)
        assert prompts == [True] and app.file_list.index == 1
        commands.cmd_next_image(app)  # flag cleared on confirm + load_current
        assert prompts == [True] and app.file_list.index == 2  # NO re-prompt
    finally:
        root.destroy()


def test_save_success_clears_flag_but_cancelled_dialog_keeps_it(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        _draw_line(app.annotation_palette)
        app.annotation_palette._on_done()
        assert app.annotations_unsaved is True
        # Cancelled Save As dialog: the flag must survive.
        monkeypatch.setattr(
            commands, "filedialog", types.SimpleNamespace(asksaveasfilename=lambda **k: "")
        )
        assert commands.cmd_save_as(app) is False
        assert app.annotations_unsaved is True
        # Real save (BMP: no options dialog in the way) clears it.
        out = tmp_path / "out.bmp"
        monkeypatch.setattr(
            commands, "filedialog", types.SimpleNamespace(asksaveasfilename=lambda **k: str(out))
        )
        assert commands.cmd_save_as(app) is True
        assert out.exists()
        assert app.annotations_unsaved is False
    finally:
        root.destroy()


def test_quit_prompts_when_annotations_unsaved(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        assert root.protocol("WM_DELETE_WINDOW")  # titlebar close routes via cmd_quit
        commands.cmd_annotate(app)
        _draw_line(app.annotation_palette)
        destroyed: list[bool] = []
        monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(True))
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: False)
        )
        commands.cmd_quit(app)  # declined: still running, session intact
        assert destroyed == [] and app.annotation_palette is not None
        monkeypatch.setattr(
            commands, "messagebox", types.SimpleNamespace(askyesno=lambda *a, **k: True)
        )
        commands.cmd_quit(app)
        assert destroyed == [True]
    finally:
        root.destroy()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_commands.py -v` → 2 new FAIL (no gate in `cmd_open`/`cmd_show_index`)
Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v` → 4 new FAIL (navigation proceeds without prompting; `cmd_save_as` returns None; quit never prompts)

- [ ] **Step 4: Write the implementation**

(a) In `src/pxv/commands.py`, add the navigate gate as the FIRST body line (after the docstring where present) of: `cmd_open` (line 84), `cmd_next_image` (375), `cmd_prev_image` (383), `cmd_show_index` (399), `cmd_toggle_slideshow` (458), `cmd_quit` (498):

```python
    if not annotation_gate(app, "navigate"):
        return
```

(For `cmd_next_image`, which has no docstring, it goes above the existing `# AIDEV-NOTE: Roll the cursor back...` comment.)

(b) Change `cmd_save_as` (line 119) to return success. Signature becomes:

```python
def cmd_save_as(app: PxvApp) -> bool:
    """Save the enhanced image via Save As dialog.

    Returns True only when a file was actually written — cancel (either
    dialog), failure, and the draw-mode gate all return False, so the
    annotations_unsaved flag survives everything short of a real save.
    """
```

Then change every early exit in the function to `return False` — there are five: the mutate gate added in Task 6 (`if not annotation_gate(app, "mutate"): return` → `return False`), `if app.image_model.working_image is None: return`, `if not path: return`, `if chosen is None: return`, and `if save_img is None: return`. Finally replace the trailing try/except (lines 177–180):

```python
    try:
        save_img.save(path, format=fmt, **save_kwargs)
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save image:\n{e}")
```

with:

```python
    try:
        save_img.save(path, format=fmt, **save_kwargs)
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save image:\n{e}")
        return False
    # AIDEV-NOTE: A successful save clears the annotation dirty flag (the
    # 2026-06-10 lifecycle); the bool return exists because None-on-everything
    # could not distinguish a cancelled dialog from a written file.
    app.annotations_unsaved = False
    return True
```

(c) In `src/pxv/app.py` `__init__`, after line 140 (`self._bind_configure()`), insert:

```python
        # AIDEV-NOTE: The titlebar close button otherwise bypasses cmd_quit —
        # and with it the unsaved-annotations prompt — entirely.
        root.protocol("WM_DELETE_WINDOW", lambda: commands.cmd_quit(self))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_commands.py -v` → 12 PASS
Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_thumbnail_browser.py -v` → all PASS (31 + existing; the browser file pins that gated `cmd_next_image`/`cmd_show_index`/`cmd_quit` still work with no palette open)

- [ ] **Step 6: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/commands.py src/pxv/app.py tests/test_commands.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/commands.py src/pxv/app.py tests/test_commands.py tests/test_annotation_mode.py
git commit -m "feat(draw): discard prompts on navigation/quit, save success clears the flag

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Full-suite verification + smoke

**Files:** none (verification only)

- [ ] **Step 1: Full suite under a display**

```bash
DISPLAY=:99 uv run pytest
```
Expected: 368 collected (324 after Phase 1 + 44 new: 5 image-model, 31 annotation-mode, 8 commands), 0 failures. If Phase 1's final count differed, reconcile against the +44 delta.

- [ ] **Step 2: Lint + typecheck**

```bash
uv run ruff format --check src tests
uv run mypy src/pxv
```
Expected: no reformats, mypy clean.

- [ ] **Step 3: Manual smoke under Xvfb — the full user flow**

```bash
DISPLAY=:99 uv run python - << 'EOF'
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from pxv import commands
from pxv.app import PxvApp
from pxv.file_list import FileList

p1, p2 = Path("/tmp/draw_smoke_1.png"), Path("/tmp/draw_smoke_2.png")
Image.new("RGB", (320, 240), (30, 30, 60)).save(p1)
Image.new("RGB", (320, 240), (60, 30, 30)).save(p2)

root = tk.Tk(className="pxv")
root.geometry("800x600")
app = PxvApp(root, FileList([p1, p2]))
root.update()
app.load_current()
root.update()

# Open the mode with `d`'s command, draw an arrow and an ellipse, change style.
commands.cmd_annotate(app)
palette = app.annotation_palette
assert palette is not None
palette.select_tool_key("4")
palette.on_press((40.0, 200.0)); palette.on_drag((200.0, 80.0)); palette.on_release((200.0, 80.0))
palette.set_color("#ffff00")
palette.select_tool_key("6")
palette.on_press((220.0, 60.0)); palette.on_drag((300.0, 140.0)); palette.on_release((300.0, 140.0))
assert len(palette.layer.shapes) == 2 and app.annotations_unsaved
root.update()

# Gated commands are consumed; Done bakes exactly one snapshot.
commands.cmd_rotate(app, 90)
assert app.image_model.get_working_size() == (320, 240)
palette._on_done()
assert app.annotation_palette is None and len(app.history._undo) == 1
working = app.image_model.working_image
assert working.getpixel((120, 140)) != (30, 30, 60)  # arrow shaft landed
assert working.getpixel((10, 10)) == (30, 30, 60)  # background untouched
working.save("/tmp/draw_smoke_baked.png")

# Navigation prompts once (flag set by the bake), then never re-prompts.
prompts = []
commands.messagebox = SimpleNamespace(askyesno=lambda *a, **k: prompts.append(True) or True)
commands.cmd_next_image(app)
commands.cmd_next_image(app)
assert prompts == [True], prompts

commands.cmd_prev_image(app)  # wraps from image 1 (index 0) to image 2 (freshly loaded, clean)
root.destroy()
print("smoke OK -> /tmp/draw_smoke_baked.png")
EOF
```

Expected: `smoke OK`. Visually inspect `/tmp/draw_smoke_baked.png` (red arrow with a filled head pointing up-right, yellow ellipse outline), then delete the three /tmp files. Report exact results.

---

## Out of scope (later phases)

- Select tool (key `1`): hit-test selection, dashed-bbox marker (`set_selection_marker`), move-drag, restyle-selection, `<Double-Button-1>` canvas binding, and routing `on_undo_key`/`on_redo_key` to `layer.undo()`/`layer.redo()` — Phase 3 (the bodies to replace are marked with AIDEV-NOTEs).
- Text labels (key `8`, entry popup, double-click re-edit), highlighter (key `7`), opacity slider, fill toggle — Phase 4.
- Context-menu "Draw / Annotate…" entry, `?` dialog `d` row (`KEYBINDINGS` in `dialogs.py`), README/CHANGELOG, per-tool cursor refinements — Phase 5.
- Transparent-image annotate→save-PNG→alpha-intact integration test — lands with Phase 4/5 polish (the `apply_overlay` lockstep unit tests cover the mechanism now).




