# Full Kit — Text, Highlighter, Opacity, Fill (Phase 4 of Image Annotations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the tool kit: text labels (key `8`) via an overrideredirect entry popup with Select-double-click re-edit, the highlighter (key `7`), an opacity slider, and a fill toggle — making every styling field of `Shape` reachable from the palette.

**Architecture:** Everything renders and hit-tests already (Phase 1 shipped `highlight`/`text` drawing, opacity alpha, and fill in `annotation_render.py`/`annotations.py`) — this phase is UI wiring in `annotation_palette.py`. The text popup is a child Toplevel of the palette (outside root's bindtag chain, so typing can never fire root shortcuts) with one dismissal funnel `cancel_text_popup()` called from every view-changing or session-ending path; `canvas_view.py` gains a `<Double-Button-1>` forwarding binding plus an image→screen helper for popup placement, and the app's shared display-composite hook becomes the popup's view-change chokepoint (wheel-pan, the one view change with no re-render behind it, notifies the session directly via `on_view_scrolled`).

**Decisions where the spec leaves internals open (BINDING on later phases):**

- Palette styling state grows `opacity: float = 1.0`, `fill: bool = False`, `font_px: float` (medium preset); UI internals `_opacity_var` (`tk.DoubleVar`, 0–100), `_fill_var` (`tk.BooleanVar`), `_opacity_scale` (`tk.Scale`); handlers `_on_opacity_changed(value: str)` / `_on_fill_toggled()`. Both restyle a live selection through Phase 3's `_restyle_selection` (coalesced — a whole slider drag is ONE undo step); the fill toggle restyles only rect/ellipse selections (no junk undo steps on other tools), and the size presets restyle `font_px` for a selected text label, `width_px` otherwise.
- Text-popup names: `_open_text_popup(anchor_xy, edit_index)` (edit_index `None` = new label), `cancel_text_popup()` (the ONE dismissal path, public because the app's composite hook calls it), `_on_text_popup_return`/`_on_text_popup_escape` (both return `"break"`), state `_text_popup`/`_text_entry`/`_text_anchor`/`_text_edit_index`, one-shot `_font_hint_shown`. Hint text: `"pxv: no scalable font — text renders at a fixed size"`, shown at first popup open when `scalable_font_available()` is False.
- The popup is `tk.Toplevel(self)` — a child of the PALETTE, so the Entry's bindtag chain is `(entry, "Entry", popup, "all")`: root is not in it (the spec's keystroke confinement falls out of Tk's bindtag rules), and destroying the palette reaps any stray popup.
- **View-change cancellation is a conservative superset of the spec's list:** `app._composite_annotations` (the hook both display paths share) calls `cancel_text_popup()` on EVERY re-render — zoom, resize, background toggle, a selection restyle/move. The popup's screen position is derived from canvas coords, which any re-render can strand; one chokepoint beats enumerating triggers. The ONE view change with no re-render behind it is a wheel pan (`_on_mouse_wheel` scrolls the canvas directly — and the wheel is pxv's only pan input), so the non-drag wheel branch notifies the session via a new Protocol method `on_view_scrolled()`, which the palette implements as `cancel_text_popup()`. Done/Cancel/navigation/stale-guard funnel through `_end_session`, which cancels first; Escape cancels the popup before anything else.
- Uncommitted popup text is NOT "unsaved work": the layer is untouched until Enter, so navigating away with an open popup and an empty layer silently ends the session (no discard prompt).
- A text-tool click with a popup already open cancels it (typed text discarded) and opens a fresh popup at the new point. Empty Enter on a RE-EDIT cancels with no change — it does not delete the label (the spec defines empty-Enter only for new labels; deleting is `Delete`'s job).
- The re-edit commit guards against the label changing under the open popup (deleted via canvas/palette while the Entry has focus): a stale `edit_index` drops the edit silently.
- `CanvasView.image_xy_to_screen(xy) -> tuple[int, int]` (new, beside the other coordinate helpers) converts an image point to absolute screen coords for popup placement, so the palette never touches the canvas's private display fields.
- `<Double-Button-1>`: within one bind tag Tk fires only the MOST specific pattern, so the second press of a double-click reaches `_on_double_click` and never `_on_press`. With a session armed it forwards `on_double_click(image_xy)` (added to the `AnnotationSession` Protocol); with NO session it delegates to `_on_press(event)` so pre-draw-mode behavior is byte-for-byte unchanged.
- `AnnotationPalette.on_double_click`: for the Select tool it sets Phase 2's `_cancel_latch` (swallowing everything until the physical ButtonRelease — the latch "wins over the second press's select/drag interpretation"), re-picks via `select_at`, and reopens the popup pre-filled when the hit is a text shape (popup placed at the shape's anchor). For drawing/text tools a double is just a fast second press and delegates to `on_press`, so rapid strokes are never lost.
- The highlighter previews as an outline-only Tk polyline at the NOMINAL `width_px` (the stroke's path) — Tk items cannot do per-item alpha, so the true 4×-wide translucent stroke appears only at release. `_PREVIEW_KINDS` gains `"highlight": "polyline"`; the highlighter accumulates points exactly like freehand.
- `TOOL_KEYS` reaches its final form `"1"`–`"8"`; nothing is inert anymore. Test renames: Phase 3's `test_tool_keys_select_and_others_inert` keeps its name through Task 1 (key `8` still inert) and becomes `test_tool_keys_all_select` in Task 3.

**Tech Stack:** Python 3.10+, Pillow + tkinter/ttk, pytest, uv, ruff, mypy strict.

**Spec:** docs/superpowers/specs/2026-06-10-annotations-design.md · **Branch:** `annotations` (Phases 1–3 — the engine, the palette/gating, and the Select tool — must already be merged on it).

---

## Environment notes for the executor

- Pure tests: `uv run pytest <file> -v`. DISPLAY-gated tests need Xvfb on :99 → `DISPLAY=:99 uv run pytest <file> -v`. If `:99` is not already up: `Xvfb :99 -screen 0 1280x1024x24 &` (there is no `xvfb-run` on this machine).
- After writing Python: `uv run ruff format <files>` and `uv run mypy src/pxv` (strict; ruff line length is 99).
- Never remove existing `AIDEV-NOTE` comments. Exception, sanctioned here: Tasks 1 and 3 REPLACE the `TOOL_KEYS` note whose own text tracks which keys ship per phase — replace it with the updated note given in each task, never with nothing.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Code snippets quoted from `annotation_palette.py`, `canvas_view.py`, and `app.py` show their **post-Phase-3** state (those files were created/heavily edited by Phases 2–3, so current-`main` line numbers do not apply). **Always match on the quoted code, not a number.**
- Test-count expectations assume Phase 3 left `tests/test_annotation_mode.py` at 45 tests, `tests/test_annotation_render.py` at 17, and the full suite at 385 collected. If they differ, reconcile against the per-task deltas.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/annotation_palette.py` | modify | Highlighter (key 7), opacity slider + fill toggle, `font_px`, text popup (open/commit/cancel), `on_double_click`, Escape/`_end_session` popup ordering |
| `src/pxv/canvas_view.py` | modify | `image_xy_to_screen` helper; `<Double-Button-1>` binding + `_on_double_click`; `on_double_click` + `on_view_scrolled` on the `AnnotationSession` Protocol; wheel-pan popup notification |
| `src/pxv/app.py` | modify | `_composite_annotations` cancels an open text popup on every display re-render |
| `tests/test_annotation_mode.py` | modify | DISPLAY-gated: highlighter, opacity/fill, popup lifecycle, keystroke confinement, double-click re-edit |
| `tests/test_annotation_render.py` | modify | Pure pixel pins: highlight×opacity alpha, filled-rect opacity, text scaling |

---

### Task 1: Highlighter tool (key `7`)

The renderer (`annotation_render._draw_shape`) and hit-testing (`annotations._shape_hit`) have handled `tool="highlight"` since Phase 1 — this task only wires the palette: tool key, button, freehand-style point accumulation, and the outline-only drag preview.

**Files:** Modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

(a) Phase 3's `test_tool_keys_select_and_others_inert` asserts key `7` is inert — this task ships it. Replace that entire test function with (key `8` stays inert until Task 3, so the name still fits):

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
            ("7", "highlight"),
        ):
            palette.select_tool_key(char)
            assert palette.tool == tool
            assert palette._tool_var.get() == tool  # button row follows
        palette.select_tool_key("8")  # text lands later in this phase: still inert
        assert palette.tool == "highlight"
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

(b) Append the new test:

```python
def test_highlight_tool_accumulates_and_bakes_translucent(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("7")
        assert palette.tool == "highlight"
        palette.on_press((10.0, 40.0))
        palette.on_drag((30.0, 40.0))
        # Outline-only Tk polyline preview (per-item alpha is impossible in Tk).
        assert app.canvas_view._preview_id is not None
        palette.on_drag((50.0, 40.0))
        palette.on_release((70.0, 40.0))
        (shape,) = palette.layer.shapes
        assert shape.tool == "highlight"
        assert shape.points == ((10.0, 40.0), (30.0, 40.0), (50.0, 40.0), (70.0, 40.0))
        palette._on_done()
        working = app.image_model.working_image
        assert working is not None
        # The TRUE translucent render: 0.4-alpha red over the blue base
        # -> (102, 0, 153); the stroke is 4 x width_px = 8 px tall around y=40.
        r, g, b = working.getpixel((40, 40))
        assert 100 <= r <= 104 and g == 0 and 151 <= b <= 155
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 2 FAIL (`AssertionError` — key `7` is inert, so `palette.tool` never becomes `"highlight"`); the other 44 PASS

- [ ] **Step 3: Write the implementation**

All edits in `src/pxv/annotation_palette.py`.

(a) Replace the `TOOL_KEYS` note + dict (post-Phase-3 state):

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

with:

```python
# AIDEV-NOTE: Tool numbering is stable across phases (2026-06-10 design):
# 1 Select, 2 freehand, 3 line, 4 arrow, 5 rect, 6 ellipse, 7 highlighter,
# 8 text. 1-7 ship; the 8 key stays inert until the text tool lands later
# in Phase 4.
TOOL_KEYS: dict[str, PaletteTool] = {
    "1": "select",
    "2": "freehand",
    "3": "line",
    "4": "arrow",
    "5": "rect",
    "6": "ellipse",
    "7": "highlight",
}
```

(b) Replace the `_PREVIEW_KINDS` dict (Phase 2 state):

```python
_PREVIEW_KINDS: dict[Tool, str] = {
    "freehand": "polyline",
    "line": "line",
    "arrow": "arrow",
    "rect": "rect",
    "ellipse": "ellipse",
}
```

with:

```python
_PREVIEW_KINDS: dict[Tool, str] = {
    "freehand": "polyline",
    "line": "line",
    "arrow": "arrow",
    "rect": "rect",
    "ellipse": "ellipse",
    # AIDEV-NOTE: The highlighter previews as an outline-only polyline at the
    # NOMINAL width — Tk items cannot do per-item alpha, so the true 4x-wide
    # translucent stroke appears only at release (the PIL render).
    "highlight": "polyline",
}
```

(c) In `_build_ui`, the tools tuple contains `("7", "Highlight", False),` — flip it to shipped:

```python
            ("7", "Highlight", True),
```

(d) In `on_drag` (post-Phase-3 state), the drawing branch reads:

```python
        tool = cast(Tool, self.tool)  # the select branch returned above
        if tool == "freehand":
            self._drag_points.append(image_xy)
        else:
            self._drag_points = [self._drag_points[0], image_xy]
```

Change the condition to:

```python
        if tool in ("freehand", "highlight"):
```

(e) In `on_release` (post-Phase-3 state), the same shape appears:

```python
        if tool == "freehand":
            points.append(image_xy)
        else:
            points = [points[0], image_xy]
```

Change the condition to:

```python
        if tool in ("freehand", "highlight"):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 46 PASS (45 + 1 new; the rewritten tool-keys test passes too)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): highlighter tool — key 7, outline preview, translucent render

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Opacity slider + fill toggle

**Files:** Modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`; modify `tests/test_annotation_render.py`.

- [ ] **Step 1: Write the failing tests (DISPLAY-gated)**

Append to `tests/test_annotation_mode.py`:

```python
def test_opacity_slider_styles_new_shapes_and_restyles_selection(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette._opacity_var.set(50.0)
        palette._on_opacity_changed("50.0")  # the tk.Scale command callback
        assert palette.opacity == 0.5
        _draw_line(palette, y=10.0)
        (shape,) = palette.layer.shapes
        assert shape.opacity == 0.5
        # With a live selection the slider restyles it — coalesced, so a whole
        # slider walk is ONE undo step (2026-06-10 design).
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 0
        for v in (40.0, 30.0, 20.0):
            palette._opacity_var.set(v)
            palette._on_opacity_changed(str(v))
        assert palette.layer.shapes[0].opacity == 0.2
        assert palette.layer.undo() is True
        assert palette.layer.shapes[0].opacity == 0.5  # one step back past the walk
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_fill_toggle_styles_new_rects_and_restyles_only_rect_ellipse(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette._fill_var.set(True)
        palette._on_fill_toggled()
        assert palette.fill is True
        palette.select_tool_key("5")  # rect
        palette.on_press((10.0, 10.0))
        palette.on_drag((40.0, 40.0))
        palette.on_release((40.0, 40.0))
        assert palette.layer.shapes[0].fill is True
        _draw_line(palette, y=60.0)
        assert palette.layer.shapes[1].fill is False  # fill is rect/ellipse-only
        # A selected LINE ignores the toggle (no junk undo step)...
        palette.select_tool_key("1")
        palette.on_press((25.0, 60.0))
        palette.on_release((25.0, 60.0))
        assert palette.layer.selected == 1
        palette._fill_var.set(False)
        palette._on_fill_toggled()
        assert palette.layer.shapes[1].fill is False
        # No junk undo step: the toggle on a line interposed nothing, so one
        # undo removes the line-add itself (a no-change replace would not).
        assert palette.layer.undo() is True
        assert len(palette.layer.shapes) == 1
        assert palette.layer.redo() is True  # restore the line for the rect part
        assert len(palette.layer.shapes) == 2
        # ...but a selected rect restyles live (picked by its filled interior;
        # undo/redo cleared the selection, so this re-picks from scratch).
        palette.on_press((25.0, 25.0))
        palette.on_release((25.0, 25.0))
        assert palette.layer.selected == 0
        palette._fill_var.set(False)
        palette._on_fill_toggled()
        assert palette.layer.shapes[0].fill is False
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Write the behavior pins (pure)**

Append to `tests/test_annotation_render.py` — these pin Phase 1 renderer behavior the new controls now expose end-to-end, so they PASS immediately (the pin precedent from Phase 2 Task 4):

```python
def test_highlight_alpha_composes_with_opacity() -> None:
    s = Shape(
        tool="highlight",
        points=((2.0, 10.0), (28.0, 10.0)),
        color="#ffff00",
        width_px=2.0,
        opacity=0.5,
    )
    overlay = render_overlay([s], (30, 20), 1.0)
    # alpha = round(0.4 * 0.5 * 255) = 51; the width stays 4 x width_px.
    assert overlay.getpixel((15, 10)) == (255, 255, 0, 51)
    assert _column_alpha_count(overlay, 15) == 8


def test_filled_rect_respects_opacity() -> None:
    s = Shape(
        tool="rect",
        points=((2.0, 2.0), (17.0, 17.0)),
        color="#ff0000",
        width_px=1.0,
        fill=True,
        opacity=0.25,
    )
    overlay = render_overlay([s], (20, 20), 1.0)
    assert overlay.getpixel((10, 10)) == (255, 0, 0, 64)  # round(0.25 * 255)
```

- [ ] **Step 3: Run tests to verify the right ones fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_annotation_render.py -v`
Expected: the 2 new mode tests FAIL (`AttributeError: 'AnnotationPalette' object has no attribute '_opacity_var'`); the 2 render pins PASS already; everything else PASSES

- [ ] **Step 4: Write the implementation**

All edits in `src/pxv/annotation_palette.py`.

(a) In `__init__`, the styling block (post-Phase-3 state) reads:

```python
        # Styling state for NEW shapes; with a live selection the controls
        # also restyle it (see _restyle_selection).
        self._presets = size_presets(max(app.image_model.get_working_size()))
        self.tool: PaletteTool = "freehand"
        self.color: str = SWATCHES[0]
        self.width_px: float = self._presets.widths[1]  # medium
```

Append directly below the `width_px` line:

```python
        self.opacity: float = 1.0
        self.fill: bool = False
```

(b) Still in `__init__`, after the Tk-variable pair:

```python
        self._tool_var = tk.StringVar(value=self.tool)
        self._size_var = tk.StringVar(value="medium")
```

append:

```python
        self._opacity_var = tk.DoubleVar(value=100.0)
        self._fill_var = tk.BooleanVar(value=False)
```

(c) In `_build_ui`, the sizes block ends and the button row begins (Phase 2 state):

```python
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
```

Insert between them (before `btns = ttk.Frame(main)`):

```python
        style = ttk.LabelFrame(main, text="Style", padding=6)
        style.pack(fill=tk.X, pady=(6, 0))
        ttk.Checkbutton(
            style, text="Fill", variable=self._fill_var, command=self._on_fill_toggled
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(style, text="Opacity").pack(side=tk.LEFT)
        self._opacity_scale = tk.Scale(
            style,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self._opacity_var,
            command=self._on_opacity_changed,
            length=140,
        )
        self._opacity_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
```

(d) After `_on_size_selected` (post-Phase-3 state ends with `self._restyle_selection(width_px=self.width_px)`), insert:

```python
    def _on_fill_toggled(self) -> None:
        """Filled-vs-outline default for new rect/ellipse; restyles a selection.

        Only a rect/ellipse selection restyles — fill means nothing to the
        other tools, and a no-change replace would still cost an undo step.
        """
        self.fill = self._fill_var.get()
        sel = self.layer.selected
        if sel is not None and self.layer.shapes[sel].tool in ("rect", "ellipse"):
            self._restyle_selection(fill=self.fill)

    def _on_opacity_changed(self, _value: str) -> None:
        """Slider motion: opacity default for new shapes; restyles a selection.

        AIDEV-NOTE: Fires per motion event during a slider drag — the restyle
        coalesces in AnnotationLayer.replace_selected, so a whole slider drag
        is ONE undo step (2026-06-10 design).
        """
        self.opacity = float(self._opacity_var.get()) / 100.0
        self._restyle_selection(opacity=self.opacity)
```

(e) In `on_release`, the shape creation (post-Phase-3 state) reads:

```python
        self.layer.add(
            Shape(tool=tool, points=tuple(points), color=self.color, width_px=self.width_px)
        )
```

Replace it with:

```python
        self.layer.add(
            Shape(
                tool=tool,
                points=tuple(points),
                color=self.color,
                width_px=self.width_px,
                fill=self.fill if tool in ("rect", "ellipse") else False,
                opacity=self.opacity,
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_annotation_render.py -v`
Expected: 48 + 19 PASS (Phase 2's `test_color_and_size_controls_style_new_shapes` and the bake tests must stay green — the defaults are identity: opacity 1.0, fill False)

- [ ] **Step 6: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py tests/test_annotation_mode.py tests/test_annotation_render.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py tests/test_annotation_mode.py tests/test_annotation_render.py
git commit -m "feat(draw): opacity slider and fill toggle with live coalesced restyle

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Text tool (key `8`) — entry popup, placement, font sizing, one-time font hint

**Files:** Modify `src/pxv/annotation_palette.py`; modify `src/pxv/canvas_view.py` (one new helper); modify `tests/test_annotation_mode.py`; modify `tests/test_annotation_render.py`.

- [ ] **Step 1: Write the failing tests (DISPLAY-gated)**

(a) Task 1's `test_tool_keys_select_and_others_inert` asserts key `8` is inert — this task ships it, leaving nothing inert. Replace that entire test function with:

```python
def test_tool_keys_all_select(tmp_path) -> None:  # noqa: ANN001
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
            ("7", "highlight"),
            ("8", "text"),
        ):
            palette.select_tool_key(char)
            assert palette.tool == tool
            assert palette._tool_var.get() == tool  # button row follows
        palette.select_tool_key("9")  # not a tool key: inert
        assert palette.tool == "text"
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

(b) Append the new tests:

```python
def test_image_xy_to_screen_accounts_for_centering() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        sx, sy = view.image_xy_to_screen((50.0, 50.0))
        # Image (50,50) -> canvas (150,150) via the centering offset; no scroll.
        assert sx == view.canvas.winfo_rootx() + 150
        assert sy == view.canvas.winfo_rooty() + 150
    finally:
        root.destroy()


def test_text_click_opens_popup_and_return_places_label(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        assert palette.tool == "text"
        palette.on_press((20.0, 30.0))
        root.update()
        assert palette._text_popup is not None and palette._text_popup.winfo_exists()
        assert palette._text_popup.overrideredirect()  # undecorated, outside the WM
        assert palette._text_edit_index is None
        assert not palette.is_dragging  # a text click is a click, not a drag
        entry = palette._text_entry
        assert entry is not None
        entry.insert(0, "hello")
        assert palette._on_text_popup_return(types.SimpleNamespace()) == "break"
        assert palette._text_popup is None
        (shape,) = palette.layer.shapes
        assert shape.tool == "text"
        assert shape.points == ((20.0, 30.0),)  # top-left anchor at the click point
        assert shape.text == "hello"
        assert shape.font_px == palette.font_px
        assert shape.color == palette.color and shape.opacity == palette.opacity
        assert app.annotations_unsaved is True
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_text_popup_empty_enter_or_escape_cancels(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._on_text_popup_return(types.SimpleNamespace()) == "break"
        assert palette._text_popup is None
        assert palette.layer.shapes == ()  # empty Enter: no shape
        assert app.annotations_unsaved is False
        palette.on_press((20.0, 30.0))
        entry = palette._text_entry
        assert entry is not None
        entry.insert(0, "doomed")
        assert palette._on_text_popup_escape(types.SimpleNamespace()) == "break"
        assert palette._text_popup is None
        assert palette.layer.shapes == ()  # Escape: typed text discarded
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_text_popup_is_outside_root_bindtag_chain(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path, count=2)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        entry = palette._text_entry
        assert entry is not None
        # The Entry's bindtag chain ends at the POPUP Toplevel, never root —
        # typing space/q/BackSpace cannot fire the root-bound shortcuts.
        assert str(root) not in entry.bindtags()
        root.update()
        entry.focus_force()
        entry.event_generate("<space>")  # the next-image key, typed in the Entry
        root.update()
        assert app.file_list.index == 0  # never navigated
        assert app.annotation_palette is palette  # session intact
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_text_click_on_existing_label_starts_a_new_label(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._text_entry is not None
        palette._text_entry.insert(0, "first")
        palette._on_text_popup_return(types.SimpleNamespace())
        # Click right on the placed label: a NEW empty popup, not a re-edit
        # (re-editing is Select-double-click only, 2026-06-10 design).
        palette.on_press((22.0, 32.0))
        entry = palette._text_entry
        assert entry is not None
        assert entry.get() == "" and palette._text_edit_index is None
        entry.insert(0, "second")
        palette._on_text_popup_return(types.SimpleNamespace())
        assert len(palette.layer.shapes) == 2
        assert palette.layer.shapes[1].text == "second"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_size_preset_restyles_selected_text_font(tmp_path) -> None:  # noqa: ANN001
    from pxv.annotations import size_presets

    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._text_entry is not None
        palette._text_entry.insert(0, "hi")
        palette._on_text_popup_return(types.SimpleNamespace())
        palette.select_tool_key("1")
        palette.on_press((22.0, 32.0))
        palette.on_release((22.0, 32.0))
        assert palette.layer.selected == 0  # picked via the heuristic text bbox
        palette._size_var.set("thick")
        palette._on_size_selected()
        presets = size_presets(100)  # image long side = 100
        assert palette.layer.shapes[0].font_px == presets.fonts[2]  # large
        assert palette.layer.shapes[0].width_px == 2.0  # stroke width untouched
        assert palette.font_px == presets.fonts[2]  # new-label default follows
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_bitmap_font_hint_shown_once(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        monkeypatch.setattr("pxv.annotation_palette.scalable_font_available", lambda: False)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert "fixed size" in root.title()  # the one-time hint
        assert palette._font_hint_shown is True
        palette._on_text_popup_escape(types.SimpleNamespace())
        app.root.title("pxv: sentinel")
        palette.on_press((40.0, 30.0))  # second popup: hint NOT repeated
        assert root.title() == "pxv: sentinel"
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Write the pure render pin**

Append to `tests/test_annotation_render.py` (`scalable_font_available` is already imported there from Phase 1):

```python
def test_text_scales_with_render_scale() -> None:
    s = Shape(
        tool="text",
        points=((2.0, 2.0),),
        color="#000000",
        width_px=1.0,
        text="Hello",
        font_px=16.0,
    )
    small = render_overlay([s], (120, 60), 1.0).getchannel("A").getbbox()
    big = render_overlay([s], (240, 120), 2.0).getchannel("A").getbbox()
    assert small is not None and big is not None
    if scalable_font_available():
        # The glyph footprint roughly doubles with the scale (scalable font).
        assert (big[2] - big[0]) > 1.5 * (small[2] - small[0])
        assert (big[3] - big[1]) > 1.5 * (small[3] - small[1])
```

- [ ] **Step 3: Run tests to verify the right ones fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_annotation_render.py -v`
Expected: 7 new mode tests FAIL (`AttributeError: 'CanvasView' object has no attribute 'image_xy_to_screen'` / `'AnnotationPalette' object has no attribute '_text_popup'`, and the tool-keys rewrite fails on inert `8`); the render pin PASSES already

- [ ] **Step 4: Implement `CanvasView.image_xy_to_screen`**

In `src/pxv/canvas_view.py`, insert after `set_annotation_cursor` (Phase 3 state, ends `self.canvas.config(cursor="" if select_tool else "pencil")`):

```python
    def image_xy_to_screen(self, xy: tuple[float, float]) -> tuple[int, int]:
        """Image-space point -> absolute SCREEN coords (text-popup placement).

        AIDEV-NOTE: Canvas coords live in scrollregion space; subtracting
        canvasx/y(0) converts to widget space (scroll-aware), and the widget's
        root position lifts that to screen space. The result goes stale on any
        zoom/pan/resize — the caller (the text popup) is CANCELLED on view
        changes, never repositioned (2026-06-10 design).
        """
        cx, cy = image_xy_to_canvas_point(
            xy,
            (self._display_width, self._display_height),
            (self.canvas.winfo_width(), self.canvas.winfo_height()),
            self.zoom,
        )
        wx = cx - self.canvas.canvasx(0)  # type: ignore[no-untyped-call]
        wy = cy - self.canvas.canvasy(0)  # type: ignore[no-untyped-call]
        return (self.canvas.winfo_rootx() + int(wx), self.canvas.winfo_rooty() + int(wy))
```

- [ ] **Step 5: Implement the text tool in `src/pxv/annotation_palette.py`**

(a) Extend the imports. The post-Phase-3 block reads:

```python
from pxv.annotation_render import render_overlay
from pxv.annotations import AnnotationLayer, Shape, Tool, hit_tolerance, size_presets
```

Replace with:

```python
from pxv.annotation_render import render_overlay, scalable_font_available
from pxv.annotations import AnnotationLayer, Shape, Tool, hit_tolerance, size_presets
```

(b) Replace the `TOOL_KEYS` note + dict (Task 1 state) with the final form:

```python
# AIDEV-NOTE: Tool numbering is stable across phases (2026-06-10 design):
# 1 Select, 2 freehand, 3 line, 4 arrow, 5 rect, 6 ellipse, 7 highlighter,
# 8 text. All eight tools ship as of Phase 4.
TOOL_KEYS: dict[str, PaletteTool] = {
    "1": "select",
    "2": "freehand",
    "3": "line",
    "4": "arrow",
    "5": "rect",
    "6": "ellipse",
    "7": "highlight",
    "8": "text",
}
```

(`_PREVIEW_KINDS` stays without a `"text"` entry — the text branch returns from `on_press` before any preview lookup, and a click is never a drag.)

(c) In `__init__`, after the Task 2 styling lines (`self.opacity` / `self.fill`), append:

```python
        self.font_px: float = self._presets.fonts[1]  # medium
```

and after the Phase 3 Select-drag state block:

```python
        # In-flight Select-tool move: (press_xy, shape AS PRESSED), plus
        # whether the 3-screen-px gate opened (a click with jitter ≠ a move).
        self._select_drag: tuple[tuple[float, float], Shape] | None = None
        self._select_moved = False
```

append:

```python
        # Text-entry popup (None = closed): the Toplevel, its Entry, the
        # image-space anchor of a NEW label, and the shape index being
        # re-edited (None = placing a new label).
        self._text_popup: tk.Toplevel | None = None
        self._text_entry: tk.Entry | None = None
        self._text_anchor: tuple[float, float] | None = None
        self._text_edit_index: int | None = None
        # One-shot hint when Pillow lacks the scalable embedded font.
        self._font_hint_shown = False
```

(d) In `_build_ui`, the tools tuple contains `("8", "Text", False),` — flip it to shipped:

```python
            ("8", "Text", True),
```

(e) Replace `on_press` (post-Phase-3 state):

```python
    def on_press(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            return
        if self.tool == "select":
            self._select_press(image_xy)
            return
        self._drag_points = [image_xy]
```

with:

```python
    def on_press(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            return
        if self.tool == "select":
            self._select_press(image_xy)
            return
        if self.tool == "text":
            # A click opens the entry popup; a click on an EXISTING label
            # starts a new overlapping label (re-editing is Select-double-click
            # only, 2026-06-10 design). No drag state: text is a click.
            self._open_text_popup(image_xy, edit_index=None)
            return
        self._drag_points = [image_xy]
```

(f) Replace `_on_size_selected` (post-Phase-3 state):

```python
    def _on_size_selected(self) -> None:
        idx = {"thin": 0, "medium": 1, "thick": 2}[self._size_var.get()]
        self.width_px = self._presets.widths[idx]
        self._restyle_selection(width_px=self.width_px)
```

with:

```python
    def _on_size_selected(self) -> None:
        idx = {"thin": 0, "medium": 1, "thick": 2}[self._size_var.get()]
        self.width_px = self._presets.widths[idx]
        self.font_px = self._presets.fonts[idx]
        # Size presets double as text sizes (2026-06-10 design): a selected
        # text label restyles its font_px, anything else its stroke width.
        sel = self.layer.selected
        if sel is not None and self.layer.shapes[sel].tool == "text":
            self._restyle_selection(font_px=self.font_px)
            return
        self._restyle_selection(width_px=self.width_px)
```

(g) Insert the text-tool section after `_refresh_selection_marker` (the last method of Phase 3's Select section) and before `render_display_overlay`:

```python
    # --- text tool (key 8) --------------------------------------------------

    def _open_text_popup(self, anchor_xy: tuple[float, float], edit_index: int | None) -> None:
        """Open the text-entry popup at the image-space anchor point.

        AIDEV-NOTE: An overrideredirect Toplevel parented to the PALETTE: the
        Entry's bindtag chain is (entry, "Entry", popup, "all") — root is not
        in it, so typing space/q/BackSpace can never fire the root-bound
        shortcuts (2026-06-10 design), and parenting to the palette means a
        palette destroy reaps a stray popup. Its screen position derives from
        canvas coords that go stale on any view change, so every display
        re-render cancels it (app._composite_annotations) instead of
        repositioning.
        """
        self.cancel_text_popup()  # a second click replaces any open popup
        if not self._font_hint_shown and not scalable_font_available():
            # One-time hint: Pillow lacks FreeType, text renders bitmap-sized.
            self._font_hint_shown = True
            self.app.show_temp_title("pxv: no scalable font — text renders at a fixed size")
        sx, sy = self.app.canvas_view.image_xy_to_screen(anchor_xy)
        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.geometry(f"+{sx}+{sy}")
        entry = tk.Entry(popup, width=24)
        entry.pack()
        if edit_index is not None:
            entry.insert(0, self.layer.shapes[edit_index].text)
        # The handlers return "break": nothing may propagate past the Entry.
        entry.bind("<Return>", self._on_text_popup_return)
        entry.bind("<KP_Enter>", self._on_text_popup_return)
        entry.bind("<Escape>", self._on_text_popup_escape)
        entry.focus_set()
        self._text_popup = popup
        self._text_entry = entry
        self._text_anchor = anchor_xy
        self._text_edit_index = edit_index

    def _on_text_popup_return(self, _event: object) -> str:
        """Enter in the popup: place/edit the label (non-empty) or cancel (empty)."""
        if self._text_entry is None or self._text_anchor is None:
            return "break"
        text = self._text_entry.get()
        anchor = self._text_anchor
        edit_index = self._text_edit_index
        self.cancel_text_popup()
        if not text.strip():
            return "break"  # empty Enter cancels: no shape, no edit
        if edit_index is not None:
            # Select-double-click re-edit. AIDEV-NOTE: Guard against the label
            # changing under the open popup (deleted via the canvas or the
            # palette while the Entry held focus): a stale index drops the
            # edit rather than touching the wrong shape.
            shapes = self.layer.shapes
            if edit_index >= len(shapes) or shapes[edit_index].tool != "text":
                return "break"
            self.layer.selected = edit_index
            self.layer.replace_selected(replace(shapes[edit_index], text=text))
            self._refresh_selection_marker()
        else:
            self.layer.add(
                Shape(
                    tool="text",
                    points=(anchor,),
                    color=self.color,
                    width_px=self.width_px,
                    opacity=self.opacity,
                    text=text,
                    font_px=self.font_px,
                )
            )
            self.app.annotations_unsaved = True
        self.app.refresh_display()
        return "break"

    def _on_text_popup_escape(self, _event: object) -> str:
        """Escape in the popup: cancel with no shape and no edit."""
        self.cancel_text_popup()
        return "break"

    def cancel_text_popup(self) -> None:
        """Dismiss an open text popup, committing nothing (no-op when closed).

        AIDEV-NOTE: The ONE dismissal path. Callers: a new text-tool click
        (replace), Escape (on_escape and the popup's own binding), every
        display re-render (app._composite_annotations — zoom/resize/restyle),
        a wheel pan (on_view_scrolled — the one view change with no re-render
        behind it), and _end_session (Done/Cancel/navigation/stale guard) —
        the latter call sites land in the next task.
        """
        popup = self._text_popup
        self._text_popup = None
        self._text_entry = None
        self._text_anchor = None
        self._text_edit_index = None
        if popup is not None and popup.winfo_exists():
            popup.destroy()
```

(`from dataclasses import replace` is already imported — Phase 3 Task 5 added it for `_restyle_selection`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py tests/test_annotation_render.py -v`
Expected: 55 + 20 PASS

- [ ] **Step 7: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py src/pxv/canvas_view.py tests/test_annotation_mode.py tests/test_annotation_render.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py src/pxv/canvas_view.py tests/test_annotation_mode.py tests/test_annotation_render.py
git commit -m "feat(draw): text labels — key 8 entry popup with bindtag-confined keystrokes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Popup lifecycle — cancelled by zoom/resize, wheel-pan, Escape, and every session end

**Files:** Modify `src/pxv/annotation_palette.py`; modify `src/pxv/app.py`; modify `src/pxv/canvas_view.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

(a) Extend the `_RecordingSession` helper (Phase 2, top of the file) — after its `on_release` method, add the no-op the extended Protocol demands (Step 3(d) makes the canvas call it on every non-drag wheel event, and Phase 2's `test_wheel_ignored_while_session_drag_in_flight` drives `_on_mouse_wheel` with this stand-in armed):

```python
    def on_view_scrolled(self) -> None:
        pass
```

(b) Append to `tests/test_annotation_mode.py`:

```python
def test_zoom_or_resize_render_cancels_open_text_popup(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._text_popup is not None
        commands.cmd_zoom_increase(app)  # not a drag: the zoom gate lets it through...
        assert app.canvas_view.zoom != 1.0
        assert palette._text_popup is None  # ...and the stale-positioned popup dies
        assert palette.layer.shapes == ()  # uncommitted text never places a shape
        palette.on_press((20.0, 30.0))
        assert palette._text_popup is not None
        app._update_display()  # the window-resize path shares the chokepoint
        assert palette._text_popup is None
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_wheel_pan_cancels_open_text_popup(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._text_popup is not None
        # A wheel pan scrolls the canvas with NO re-render behind it, so the
        # composite chokepoint never fires — the canvas notifies the session.
        app.canvas_view._on_mouse_wheel(types.SimpleNamespace(num=4, delta=0, state=0))
        assert palette._text_popup is None
        assert palette.layer.shapes == ()  # uncommitted text never places a shape
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_end_session_paths_cancel_open_text_popup(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=10.0)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._text_entry is not None
        palette._text_entry.insert(0, "never placed")
        popup = palette._text_popup
        palette._on_done()  # Done bakes committed shapes; the popup just dies
        assert app.annotation_palette is None
        assert popup is not None and not popup.winfo_exists()
        assert len(app.history._undo) == 1  # the line baked...
        working = app.image_model.working_image
        assert working is not None
        assert working.getpixel((25, 10)) == (255, 0, 0)
        assert working.getpixel((25, 35)) == (0, 0, 255)  # ...the typed text did not
    finally:
        root.destroy()


def test_escape_cancels_popup_before_anything_else(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        assert palette.layer.selected == 0
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))  # opens a popup; selection untouched
        assert palette._text_popup is not None
        palette.on_escape()  # first Escape: ONLY the popup dies
        assert palette._text_popup is None
        assert palette.layer.selected == 0  # selection survives
        palette.on_escape()  # second Escape: the deselect step
        assert palette.layer.selected is None
        assert app.annotation_palette is palette  # never exits the mode
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 3 new FAIL (`AssertionError` — the zoom/`_update_display` renders and the wheel pan leave `_text_popup` set, and the first `on_escape` deselects instead of dismissing the popup). `test_end_session_paths_cancel_open_text_popup` PASSES already — the popup is a child Toplevel of the palette, so `_end_session`'s `self.destroy()` already reaps it; the test pins that teardown contract here (the explicit `cancel_text_popup()` added in Step 3(b) clears the palette's popup state before the bake rather than changing observable behavior). The other 55 PASS.

- [ ] **Step 3: Write the implementation**

(a) In `src/pxv/app.py`, `_composite_annotations` (added by Phase 2 Task 4) begins:

```python
        palette = self.annotation_palette
        if display_img is None or palette is None or not palette.layer.shapes:
            return display_img
```

Replace those three lines with:

```python
        palette = self.annotation_palette
        if display_img is None or palette is None:
            return display_img
        # AIDEV-NOTE: Every display re-render is a view change as far as the
        # text-entry popup is concerned — its screen position derived from
        # canvas coords that are now stale (zoom/resize/background/restyle) —
        # so it is dismissed here, the one chokepoint both display paths share
        # (2026-06-10 design: zoom/navigation/Done/stale guard all cancel it).
        palette.cancel_text_popup()
        if not palette.layer.shapes:
            return display_img
```

(The rest of the method — the stale-image guard and the overlay paste — is unchanged.)

(b) In `src/pxv/annotation_palette.py`, `_end_session` (Phase 2 state, unchanged by Phase 3) begins:

```python
    def _end_session(self, bake: bool) -> None:
        """The ONE teardown path — every way out of draw mode goes through here.

        Disarms the canvas FIRST (the eyedropper _on_close pattern) so no
        event can reach a dying session, then destroys the window, keeping the
        palette-open <=> mode-active invariant.
        """
        self.app.canvas_view.set_annotation_session(None)
```

Replace that opening with:

```python
    def _end_session(self, bake: bool) -> None:
        """The ONE teardown path — every way out of draw mode goes through here.

        Disarms the canvas FIRST (the eyedropper _on_close pattern) so no
        event can reach a dying session, then destroys the window, keeping the
        palette-open <=> mode-active invariant. An open text popup is
        dismissed before anything else — uncommitted text is never baked.
        """
        self.cancel_text_popup()
        self.app.canvas_view.set_annotation_session(None)
```

(The rest of the method body is unchanged.)

(c) Still in `annotation_palette.py`, `on_escape` (post-Phase-3 state) begins:

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
```

Replace that opening (docstring through the first `if` line) with:

```python
    def on_escape(self) -> None:
        """Escape: dismiss the popup, else cancel a drag, else deselect, else nothing.

        AIDEV-NOTE: Never exits the mode (no accidental bakes) and never
        falls through to app.escape_action — leaving fullscreen during a
        session is f/F11. The latch swallows the cancelled drag's remaining
        motion events until the physical ButtonRelease (see on_release).
        A cancelled MOVE rolls back through layer.undo(): the move run is one
        coalesced undo state, so one undo restores the pre-move shape exactly
        (the aborted move parks on the redo stack — accepted quirk). The text
        popup outranks everything: its own Escape binding covers the
        focused-Entry case, and this branch covers Escape arriving from the
        canvas or the palette while a popup is open.
        """
        if self._text_popup is not None:
            self.cancel_text_popup()
            return
        if self._drag_points is not None:
```

(The drag-cancel, move-cancel, and deselect branches below stay exactly as Phase 3 left them.)

(d) In `src/pxv/canvas_view.py`, extend the `AnnotationSession` Protocol (Phase 2 state — its last line is `def on_release(self, image_xy: tuple[float, float]) -> None: ...`). Append:

```python
    def on_view_scrolled(self) -> None: ...
```

Then in `_on_mouse_wheel`, replace the Phase 2 session guard (directly after the docstring):

```python
        # AIDEV-NOTE: The wheel is pxv's only pan input; a view change mid-drag
        # would shear the stroke, so wheel events are ignored while an
        # annotation drag is in flight (zoom KEYS are consumed in commands.py;
        # per-event coordinate conversion remains as defense in depth).
        if self._annotation_session is not None and self._annotation_session.is_dragging:
            return "break"
```

with:

```python
        if self._annotation_session is not None:
            # AIDEV-NOTE: The wheel is pxv's only pan input; a view change
            # mid-drag would shear the stroke, so wheel events are ignored
            # while an annotation drag is in flight (zoom KEYS are consumed
            # in commands.py; per-event coordinate conversion remains as
            # defense in depth).
            if self._annotation_session.is_dragging:
                return "break"
            # A pan is a view change with NO re-render behind it, so the
            # composite chokepoint (app._composite_annotations) never sees it
            # — notify the session so an open text popup (screen-positioned)
            # is dismissed, not stranded (2026-06-10 design).
            self._annotation_session.on_view_scrolled()
```

(e) Back in `src/pxv/annotation_palette.py`, implement the notification — insert directly after `cancel_text_popup` (the end of Task 3's text-tool section):

```python
    def on_view_scrolled(self) -> None:
        """Wheel pan: a view change that bypasses the display re-render
        chokepoint — dismiss an open text popup (no-op otherwise)."""
        self.cancel_text_popup()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 59 PASS (Phase 2's stale-guard, navigation-prompt, and wheel-during-drag tests must stay green — `cancel_text_popup` is a no-op when no popup is open, and `_RecordingSession` grew its `on_view_scrolled` no-op in Step 1)

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/annotation_palette.py src/pxv/app.py src/pxv/canvas_view.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/annotation_palette.py src/pxv/app.py src/pxv/canvas_view.py tests/test_annotation_mode.py
git commit -m "feat(draw): text popup cancelled by view changes, Escape, and session end

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Select-double-click re-edit — `<Double-Button-1>` forwarding + the latch

**Files:** Modify `src/pxv/canvas_view.py`; modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

(a) In `tests/test_annotation_mode.py`, extend the `_RecordingSession` helper (Phase 2, top of the file) — after the `on_view_scrolled` no-op Task 4 added, add:

```python
    def on_double_click(self, image_xy: tuple[float, float]) -> None:
        self.events.append(("double", image_xy))
```

(b) Append the new tests:

```python
def test_canvas_double_click_forwards_to_session_or_falls_back() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        session = _RecordingSession()
        view.set_annotation_session(session)
        view._on_double_click(types.SimpleNamespace(x=150, y=150))
        assert session.events == [("double", (50.0, 50.0))]
        view.set_annotation_session(None)
        view._on_double_click(types.SimpleNamespace(x=10, y=10))
        assert view._rb_start is not None  # disarmed: behaves like a plain press
    finally:
        root.destroy()


def test_select_double_click_reedits_text_prefilled(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        palette.on_press((20.0, 30.0))
        assert palette._text_entry is not None
        palette._text_entry.insert(0, "old")
        palette._on_text_popup_return(types.SimpleNamespace())
        palette.select_tool_key("1")
        # The physical event stream: press, release, double (press#2), release
        # (Tk routes the second press to <Double-Button-1>, never the plain press).
        palette.on_press((22.0, 32.0))
        palette.on_release((22.0, 32.0))
        palette.on_double_click((22.0, 32.0))
        entry = palette._text_entry
        assert entry is not None
        assert entry.get() == "old"  # pre-filled
        assert palette._text_edit_index == 0
        palette.on_release((22.0, 32.0))  # the trailing physical release: latched
        assert palette._text_popup is not None  # the release must NOT cancel it
        entry.delete(0, tk.END)
        entry.insert(0, "new")
        palette._on_text_popup_return(types.SimpleNamespace())
        assert palette.layer.shapes[0].text == "new"
        assert palette.layer.shapes[0].points == ((20.0, 30.0),)  # anchor kept
        assert palette.layer.undo() is True  # the edit is ONE undo step
        assert palette.layer.shapes[0].text == "old"
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_double_click_on_non_text_latches_until_release(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        _draw_line(palette, y=10.0)
        palette.select_tool_key("1")
        palette.on_press((25.0, 10.0))
        palette.on_release((25.0, 10.0))
        palette.on_double_click((25.0, 10.0))
        assert palette._text_popup is None  # only text shapes re-edit
        assert palette.layer.selected == 0  # still picked
        palette.on_drag((60.0, 60.0))  # between double and physical release
        assert palette.layer.shapes[0].points == ((10.0, 10.0), (40.0, 10.0))  # swallowed
        palette.on_release((60.0, 60.0))  # the physical release re-arms
        palette.on_press((25.0, 10.0))
        palette.on_drag((35.0, 20.0))
        palette.on_release((35.0, 20.0))
        assert palette.layer.shapes[0].points == ((20.0, 20.0), (50.0, 20.0))  # moves again
        palette._end_session(bake=False)
    finally:
        root.destroy()


def test_double_click_with_drawing_tool_is_a_fast_second_press(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)  # default tool: freehand
        palette.on_double_click((5.0, 5.0))  # Tk swallowed the plain second press
        assert palette.is_dragging  # the stroke still starts
        palette.on_drag((25.0, 5.0))
        palette.on_release((45.0, 5.0))
        (shape,) = palette.layer.shapes
        assert shape.points == ((5.0, 5.0), (25.0, 5.0), (45.0, 5.0))
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 4 new FAIL (`AttributeError: 'CanvasView' object has no attribute '_on_double_click'` / `'AnnotationPalette' object has no attribute 'on_double_click'`); the other 59 PASS

- [ ] **Step 3: Implement the canvas side (`src/pxv/canvas_view.py`)**

(a) Extend the `AnnotationSession` Protocol (post-Task-4 state — its last line is `def on_view_scrolled(self) -> None: ...`). Append a fifth method:

```python
    def on_double_click(self, image_xy: tuple[float, float]) -> None: ...
```

(b) In `_bind_mouse`, after the three primary-button bindings:

```python
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
```

insert:

```python
        # AIDEV-NOTE: Within one bind tag Tk fires only the MOST SPECIFIC
        # pattern, so the second press of a double-click triggers this and
        # never <ButtonPress-1> — _on_double_click delegates to _on_press
        # when no annotation session is armed, keeping old behavior intact.
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
```

(c) Insert the handler after `_on_release` (its last lines normalize `self._selection = (min(x0, x1), ...)`) and before `_on_mouse_wheel`:

```python
    def _on_double_click(self, event: tk.Event) -> None:
        """Second press of a double-click (replaces the plain press — see _bind_mouse)."""
        if self._annotation_session is not None:
            self._annotation_session.on_double_click(self._event_image_xy(event))
            return
        # No session: delegate to the plain press so pre-draw-mode behavior
        # (the second press restarting the rubber band) is unchanged.
        self._on_press(event)
```

- [ ] **Step 4: Implement the palette side (`src/pxv/annotation_palette.py`)**

Insert `on_double_click` directly after `on_release` (which ends with `self.app.refresh_display()` after the `layer.add` call) and before the `# --- Select tool (key 1) ---` section:

```python
    def on_double_click(self, image_xy: tuple[float, float]) -> None:
        """Second press of a double-click (Tk suppresses the plain press).

        AIDEV-NOTE: With the Select tool the double-click WINS over the second
        press's select/drag interpretation: the same cancelled-until-release
        latch Escape uses swallows motion/release until the physical
        ButtonRelease. A double on a text shape reopens the entry popup
        pre-filled — the ONLY re-edit path (2026-06-10 design). For the
        drawing/text tools a double is just a fast second press and delegates
        to on_press, so rapid successive strokes are never lost.
        """
        if self._cancel_latch:
            return
        if self.tool != "select":
            self.on_press(image_xy)
            return
        self._cancel_latch = True
        self._select_drag = None
        self._select_moved = False
        tol = hit_tolerance(self.app.canvas_view.zoom, self.width_px)
        index = self.layer.select_at(image_xy, tol)
        self._refresh_selection_marker()
        if index is not None and self.layer.shapes[index].tool == "text":
            # Popup at the label's own anchor, pre-filled (select_at above
            # broke replace-coalescing, so the commit is one clean undo step).
            self._open_text_popup(self.layer.shapes[index].points[0], edit_index=index)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 63 PASS (Phase 2/3's press/drag/release and Escape-latch tests must stay green — the plain-press paths are untouched)

- [ ] **Step 6: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/canvas_view.py src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/canvas_view.py src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): Select-double-click re-edits text labels via the entry popup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Full-suite verification + smoke

**Files:** none (verification only)

- [ ] **Step 1: Full suite under a display**

```bash
DISPLAY=:99 uv run pytest
```
Expected: 406 collected (385 after Phase 3 + 21 new: 18 annotation-mode, 3 render), 0 failures. If Phase 3's final count differed, reconcile against the +21 delta.

- [ ] **Step 2: Lint + typecheck**

```bash
uv run ruff format --check src tests
uv run mypy src/pxv
```
Expected: no reformats, mypy clean.

- [ ] **Step 3: Manual smoke under Xvfb — the full-kit flow**

```bash
DISPLAY=:99 uv run python - << 'EOF'
import tkinter as tk
import types
from pathlib import Path

from PIL import Image

from pxv import commands
from pxv.app import PxvApp
from pxv.file_list import FileList

p = Path("/tmp/fullkit_smoke.png")
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

# Highlighter stroke across the top (default red, medium width).
palette.select_tool_key("7")
palette.on_press((40.0, 40.0)); palette.on_drag((200.0, 40.0)); palette.on_release((280.0, 40.0))

# Half-opacity filled yellow rect.
palette.set_color("#ffff00")
palette._fill_var.set(True); palette._on_fill_toggled()
palette._opacity_var.set(50.0); palette._on_opacity_changed("50.0")
palette.select_tool_key("5")
palette.on_press((60.0, 100.0)); palette.on_drag((180.0, 180.0)); palette.on_release((180.0, 180.0))

# Text label via the popup (full opacity, white).
palette._opacity_var.set(100.0); palette._on_opacity_changed("100.0")
palette.set_color("#ffffff")
palette.select_tool_key("8")
palette.on_press((200.0, 200.0))
root.update()
assert palette._text_popup is not None
palette._text_entry.insert(0, "helo")
palette._on_text_popup_return(types.SimpleNamespace())

# Select-double-click re-edit fixes the typo.
palette.select_tool_key("1")
palette.on_press((205.0, 205.0)); palette.on_release((205.0, 205.0))
palette.on_double_click((205.0, 205.0))
assert palette._text_entry is not None and palette._text_entry.get() == "helo"
palette._text_entry.delete(0, tk.END); palette._text_entry.insert(0, "hello")
palette._on_text_popup_return(types.SimpleNamespace())
palette.on_release((205.0, 205.0))  # trailing physical release
assert palette.layer.shapes[-1].text == "hello"

# Zoom cancels an open popup without touching the layer.
palette.select_tool_key("8")
palette.on_press((40.0, 200.0))
n_shapes = len(palette.layer.shapes)
commands.cmd_zoom_increase(app)
assert palette._text_popup is None and len(palette.layer.shapes) == n_shapes
commands.cmd_zoom_normal(app)
root.update()

palette._on_done()
assert app.annotation_palette is None and len(app.history._undo) == 1
working = app.image_model.working_image
r, g, b = working.getpixel((120, 40))   # highlighter: 0.4-alpha red over (30,30,60)
assert 115 <= r <= 125 and 30 <= b <= 42, (r, g, b)
r, g, b = working.getpixel((120, 140))  # 50% yellow fill over (30,30,60)
assert 135 <= r <= 150 and 135 <= g <= 150 and 25 <= b <= 35, (r, g, b)
assert working.getpixel((10, 230)) == (30, 30, 60)  # background untouched
working.save("/tmp/fullkit_baked.png")
root.destroy()
print("smoke OK -> /tmp/fullkit_baked.png")
EOF
```

Expected: `smoke OK`. Visually inspect `/tmp/fullkit_baked.png` (translucent red band, half-transparent yellow square, white "hello"), then delete both /tmp files. Report exact results.

---

## Out of scope (Phase 5)

- Context-menu "Draw / Annotate…" entry; `?` dialog rows for `d` and the tool keys (`KEYBINDINGS` in `dialogs.py` — untouched this phase); README/CHANGELOG.
- Per-tool cursor refinements beyond Phase 3's Select arrow (e.g. an I-beam for the text tool).
- Transparent-image annotate→save-PNG→alpha-intact integration test (lands with Phase 5 polish; `apply_overlay` lockstep unit tests cover the mechanism).
- Resize/endpoint handles, sidecar persistence, custom fonts — out of scope for the feature.




