# Polish (Phase 5 of Image Annotations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the annotations feature for release: a "Draw / Annotate..." context-menu entry, `d` plus the in-mode keys in the `?` shortcuts table, README/CHANGELOG documentation, a per-tool cursor refinement (I-beam for the text tool), and two end-to-end integration tests (full session bake→save→reload, and the transparent-PNG alpha-preservation variant).

**Architecture:** No new modules — this phase is surface polish over Phases 1–4. The cursor refinement widens Phase 3's `CanvasView.set_annotation_cursor(select_tool: bool)` into a per-tool-name lookup (`_TOOL_CURSORS`: Select → default arrow, text → `xterm` I-beam, everything else → `pencil`); the context-menu entry and the help-table rows route through the existing `cmd_annotate` and `KEYBINDINGS` single-sources-of-truth, so no new behavior paths exist to gate or guard. The integration tests drive the real `PxvApp` through the session protocol, `cmd_save_as`, and a PNG round-trip — pinning the whole stack the unit tests covered piecewise.

**Decisions where the spec leaves internals open (BINDING):**

- `set_annotation_cursor` takes the palette's tool name as a plain `str` (a `PaletteTool` value at every call site) — `canvas_view.py` keeps zero imports from the palette module, the same reasoning as the `AnnotationSession` Protocol. Cursor map: `_TOOL_CURSORS = {"select": "", "text": "xterm"}`, default `"pencil"` (covers all six drawing tools; `xterm` is in Tk's portable cursor set).
- The menu label is `"Draw / Annotate..."` — ASCII three-dot ellipsis to match every existing entry in `context_menu.py` (`"Open..."`, `"Enhancements..."`), not the spec's typographic `…`.
- The `KEYBINDINGS` table grows a draw-mode section as ordinary rows: an empty-key spacer, an empty-key header row (`("", "— While the drawing palette is open —")`), then the in-mode keys. `help_dialog` renders rows generically, so no renderer change is needed.

**Tech Stack:** Python 3.10+, Pillow + tkinter/ttk, pytest, uv, ruff, mypy strict.

**Spec:** docs/superpowers/specs/2026-06-10-annotations-design.md · **Branch:** `annotations` (Phases 1–4 must already be merged on it: `annotations.py`/`annotation_render.py`, the palette + gating, the Select tool, text/highlight/opacity/fill).

---

## Environment notes for the executor

- Pure tests: `uv run pytest <file> -v`. DISPLAY-gated tests need Xvfb on :99 → `DISPLAY=:99 uv run pytest <file> -v`. If `:99` is not already up: `Xvfb :99 -screen 0 1280x1024x24 &` (there is no `xvfb-run` on this machine).
- After writing Python: `uv run ruff format <files>` and `uv run mypy src/pxv` (strict).
- Never remove existing `AIDEV-NOTE` comments.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Line numbers for `context_menu.py`, `dialogs.py`, `README.md`, and `CHANGELOG.md` are exact — Phases 1–4 never touched those files. `canvas_view.py` and `annotation_palette.py` line numbers shifted across Phases 1–4, so for those, match on the quoted code, not a number.
- Test-count baseline after Phase 4: `tests/test_annotation_mode.py` = 62, `tests/test_commands.py` = 12, full suite = 405 collected. If a baseline differs, reconcile against this plan's deltas (+4 mode, +2 commands).

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/pxv/canvas_view.py` | modify | `_TOOL_CURSORS` map; `set_annotation_cursor(tool: str)` (signature widened from Phase 3's bool) |
| `src/pxv/annotation_palette.py` | modify | `_update_canvas_cursor` passes the tool name instead of a Select bool |
| `src/pxv/context_menu.py` | modify | "Draw / Annotate..." entry → `cmd_annotate` |
| `src/pxv/dialogs.py` | modify | `KEYBINDINGS`: `d` row + draw-mode section rows |
| `README.md` | modify | `d` in the shortcut table (plus undo/redo row sync), "## Annotations" section, Features bullet, Pillow 10.1+ |
| `CHANGELOG.md` | modify | `[Unreleased]` entry; link refs brought current |
| `tests/test_annotation_mode.py` | modify | Cursor test rewrite + I-beam test, context-menu test, two end-to-end integration tests |
| `tests/test_commands.py` | modify | Pure `KEYBINDINGS` table tests |

---

### Task 1: Per-tool canvas cursors — I-beam for the text tool

Phase 3 shipped pencil-vs-arrow via `set_annotation_cursor(select_tool: bool)`; a bool can't express the text tool's I-beam. Widen it to take the tool name. Every caller and test is updated in this same task, so the suite is green at the commit.

**Files:** Modify `src/pxv/canvas_view.py`; modify `src/pxv/annotation_palette.py`; modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing tests**

(a) In `tests/test_annotation_mode.py`, Phase 3's `test_annotation_cursor_switches_arrow_for_select` drives the old bool signature. Replace that entire test function with:

```python
def test_annotation_cursor_per_tool() -> None:
    root = tk.Tk()
    try:
        view = _canvas_view(root)
        view.set_annotation_cursor("select")  # disarmed: a no-op
        assert view.canvas.cget("cursor") == "crosshair"
        view.set_annotation_session(_RecordingSession())
        view.set_annotation_cursor("select")
        assert view.canvas.cget("cursor") == ""  # the default arrow
        view.set_annotation_cursor("text")
        assert view.canvas.cget("cursor") == "xterm"  # I-beam: click-to-type surface
        view.set_annotation_cursor("freehand")
        assert view.canvas.cget("cursor") == "pencil"
        view.set_annotation_cursor("highlight")
        assert view.canvas.cget("cursor") == "pencil"  # unlisted tools fall back
    finally:
        root.destroy()
```

(b) Append the palette-level test (the `_make_app`/`_open_palette` helpers are in this file from Phase 2):

```python
def test_text_tool_key_shows_ibeam_cursor(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        palette = _open_palette(app)
        palette.select_tool_key("8")
        assert app.canvas_view.canvas.cget("cursor") == "xterm"
        palette.select_tool_key("1")
        assert app.canvas_view.canvas.cget("cursor") == ""  # Select: arrow
        palette.select_tool_key("7")
        assert app.canvas_view.canvas.cget("cursor") == "pencil"  # drawing tools
        palette._end_session(bake=False)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 2 FAIL with `AssertionError` — the old implementation treats any truthy argument as "Select", so `set_annotation_cursor("text")` yields `""` (not `"xterm"`), `"freehand"` yields `""` (not `"pencil"`), and key `8` via the palette yields `"pencil"` (not `"xterm"`). The other 61 PASS (63 collected: 62 baseline with one rewritten in place, plus 1 appended).

- [ ] **Step 3: Write the implementation**

(a) In `src/pxv/canvas_view.py`, Phase 3 added this module-level constant (after `image_xy_to_canvas_point`, before `class AnnotationSession(Protocol):`):

```python
# Canvas-px padding around the Select tool's dashed selection marker, so a
# zero-height bbox (a horizontal line, a 2-point shape) still reads as a box.
_MARKER_PAD = 3.0
```

Append directly below it:

```python
# Per-tool draw-mode cursors, keyed by the palette's tool name. The Select
# tool gets the platform default arrow and the text tool an I-beam over its
# click-to-type surface; anything else (all six drawing tools) falls back to
# the pencil. xterm/pencil are in Tk's portable cursor set.
_TOOL_CURSORS: dict[str, str] = {"select": "", "text": "xterm"}
```

(b) Still in `src/pxv/canvas_view.py`, replace the whole Phase 3 method:

```python
    def set_annotation_cursor(self, select_tool: bool) -> None:
        """Default arrow for the Select tool, pencil for the drawing tools.

        A no-op while disarmed, so a late tool-change callback can never
        repaint the cursor after the session ended.
        """
        if self._annotation_session is not None:
            self.canvas.config(cursor="" if select_tool else "pencil")
```

with:

```python
    def set_annotation_cursor(self, tool: str) -> None:
        """Per-tool draw-mode cursor (see _TOOL_CURSORS); pencil is the default.

        Takes the palette's tool name (a PaletteTool value) as a plain str so
        this module never imports the palette — the AnnotationSession Protocol
        exists for the same reason. A no-op while disarmed, so a late
        tool-change callback can never repaint the cursor after the session
        ended.
        """
        if self._annotation_session is not None:
            self.canvas.config(cursor=_TOOL_CURSORS.get(tool, "pencil"))
```

(c) In `src/pxv/annotation_palette.py`, replace the Phase 3 method:

```python
    def _update_canvas_cursor(self) -> None:
        """Arrow for Select, pencil for drawing tools (no-op once disarmed)."""
        self.app.canvas_view.set_annotation_cursor(self.tool == "select")
```

with:

```python
    def _update_canvas_cursor(self) -> None:
        """Per-tool canvas cursor — arrow/I-beam/pencil (no-op once disarmed)."""
        self.app.canvas_view.set_annotation_cursor(self.tool)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 63 PASS (62 with one rewritten + 1 new). Phase 3's `test_key_1_selects_select_tool_with_arrow_cursor` must stay green — it goes through `select_tool_key`, whose `""`/`"pencil"` results are unchanged.

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/canvas_view.py src/pxv/annotation_palette.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/canvas_view.py src/pxv/annotation_palette.py tests/test_annotation_mode.py
git commit -m "feat(draw): per-tool canvas cursors — I-beam for the text tool

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Context-menu "Draw / Annotate..." entry

The entry calls the existing `cmd_annotate` (commands.py, added in Phase 2), so every gate — no image, Enhance-dialog mutual exclusion, raise-don't-reopen, slideshow stop — applies automatically.

**Files:** Modify `src/pxv/context_menu.py` (entry after "Enhancements...", line 58–60); modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_annotation_mode.py` (the real `PxvApp` from `_make_app` builds its own `ContextMenu` as `app.context_menu` — app.py:128):

```python
def test_context_menu_draw_entry_opens_palette(tmp_path) -> None:  # noqa: ANN001
    app, root, _ = _make_app(tmp_path)
    try:
        menu = app.context_menu.menu
        end = menu.index("end")
        assert end is not None
        labels = {
            menu.entrycget(i, "label"): i for i in range(end + 1) if menu.type(i) == "command"
        }
        assert "Draw / Annotate..." in labels
        menu.invoke(labels["Draw / Annotate..."])
        palette = app.annotation_palette
        assert palette is not None  # the entry routes through cmd_annotate...
        assert app.canvas_view._annotation_session is palette
        menu.invoke(labels["Draw / Annotate..."])  # ...so a second invoke raises,
        assert app.annotation_palette is palette and palette.winfo_exists()  # never closes
        palette._on_done()
    finally:
        root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 1 new FAIL (`AssertionError` on `"Draw / Annotate..." in labels`); the other 63 PASS.

- [ ] **Step 3: Write the implementation**

In `src/pxv/context_menu.py`, the menu currently has (lines 58–61):

```python
        self.menu.add_command(
            label="Enhancements...", command=lambda: commands.cmd_enhancement_dialog(app)
        )
        self.menu.add_command(label="About", command=lambda: commands.cmd_about(app))
```

Insert between the Enhancements entry and the About entry:

```python
        self.menu.add_command(
            label="Draw / Annotate...", command=lambda: commands.cmd_annotate(app)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 64 PASS

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/context_menu.py tests/test_annotation_mode.py
uv run mypy src/pxv
git add src/pxv/context_menu.py tests/test_annotation_mode.py
git commit -m "feat(draw): Draw / Annotate entry in the context menu

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `?` shortcuts table — `d` row and the draw-mode section

`KEYBINDINGS` in `dialogs.py` is the single source of truth for the `?` help dialog (its AIDEV-NOTE, dialogs.py:14–16, requires this update). `help_dialog` (dialogs.py:268–304) renders each `(key, description)` row as two labels, so empty-key rows work as a spacer and a section header without touching the renderer.

**Files:** Modify `src/pxv/dialogs.py` (the `KEYBINDINGS` list, lines 17–44); modify `tests/test_commands.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commands.py` (display-free — same import style as the existing `test_keybindings_table_lists_browse`, line 46):

```python
def test_keybindings_lists_draw_key_distinct_from_background_toggle() -> None:
    from pxv.dialogs import KEYBINDINGS

    by_key = {k: desc for k, desc in KEYBINDINGS if k}
    assert "draw" in by_key["d"].lower()  # KeyError here = the d row is missing
    assert "background" in by_key["D"].lower()  # D keeps its own, distinct row


def test_keybindings_has_draw_mode_section() -> None:
    from pxv.dialogs import KEYBINDINGS

    descriptions = [desc for _key, desc in KEYBINDINGS]
    assert any("drawing palette is open" in d for d in descriptions)  # section header
    by_key = {k: desc for k, desc in KEYBINDINGS if k}
    assert "1-8" in by_key  # the stable tool numbering
    assert "Delete / Backspace" in by_key
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_commands.py -v`
Expected: 2 new FAIL (`KeyError: 'd'` and `AssertionError` on the section header); the existing 12 PASS.

- [ ] **Step 3: Write the implementation**

All edits inside the `KEYBINDINGS` list in `src/pxv/dialogs.py` (lines 17–44).

(a) After line 25, `("e", "Open enhancements dialog"),`, insert:

```python
    ("d", "Draw / annotate (drawing palette)"),
```

(b) The list currently ends (lines 42–44):

```python
    ("Escape", "Exit slideshow/fullscreen, or clear selection"),
    ("Right-click", "Context menu"),
]
```

Replace those three lines with:

```python
    ("Escape", "Exit slideshow/fullscreen, or clear selection"),
    ("Right-click", "Context menu"),
    # AIDEV-NOTE: Empty-key rows render as a spacer / section header in
    # help_dialog. The block below documents draw mode (the annotation
    # palette) — these keys only act while the palette is open.
    ("", ""),
    ("", "— While the drawing palette is open —"),
    ("1-8", "Tools: Select, freehand, line, arrow, rect, ellipse, highlight, text"),
    ("u / Ctrl+Z / Ctrl+Y", "Undo / redo shapes"),
    ("Delete / Backspace", "Delete the selected shape"),
    ("Escape", "Cancel drag, close text popup, or deselect"),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_commands.py -v`
Expected: 14 PASS. Also spot-check the dialog renders under a display: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -q` (no regressions expected — 64 PASS).

- [ ] **Step 5: Format, typecheck, commit**

```bash
uv run ruff format src/pxv/dialogs.py tests/test_commands.py
uv run mypy src/pxv
git add src/pxv/dialogs.py tests/test_commands.py
git commit -m "feat(draw): d and the draw-mode keys in the shortcuts help table

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: End-to-end integration tests — full session, and transparent-PNG alpha preservation

Tests only — they pin the integrated behavior Phases 1–4 shipped (open → draw arrow + rect → select + move → text label → Done → `cmd_save_as` → reload → pixels present; plus the spec's "Transparent images" edge case: annotate → save PNG → alpha intact). They are EXPECTED TO PASS on first run; a failure here is a real integration bug — debug it (superpowers:systematic-debugging), do not weaken the test.

**Files:** Modify `tests/test_annotation_mode.py`.

- [ ] **Step 1: Write the tests**

Append to `tests/test_annotation_mode.py`:

```python
def test_full_session_end_to_end_bake_save_reload(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """The whole user flow on one 100x80 blue PNG at zoom 1 (see _make_app)."""
    app, root, _ = _make_app(tmp_path)
    try:
        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None

        # Arrow (tool 4) along y=60 — default red, medium width (2.0 at 100px).
        palette.select_tool_key("4")
        palette.on_press((10.0, 60.0))
        palette.on_drag((40.0, 60.0))
        palette.on_release((40.0, 60.0))

        # Outline rect (tool 5) at the top right.
        palette.select_tool_key("5")
        palette.on_press((50.0, 10.0))
        palette.on_drag((80.0, 30.0))
        palette.on_release((80.0, 30.0))

        # Select (tool 1) the rect by its left border, move it down-right 10,10.
        palette.select_tool_key("1")
        palette.on_press((50.0, 20.0))
        palette.on_drag((60.0, 30.0))
        palette.on_release((60.0, 30.0))
        assert palette.layer.shapes[1].points == ((60.0, 20.0), (90.0, 40.0))

        # Text label (tool 8) at the top left, committed through the popup.
        palette.select_tool_key("8")
        palette.on_press((10.0, 10.0))
        root.update()
        assert palette._text_entry is not None
        palette._text_entry.insert(0, "Hi")
        palette._on_text_popup_return(types.SimpleNamespace())
        assert len(palette.layer.shapes) == 3

        # Done bakes all three shapes as ONE undoable edit.
        palette._on_done()
        assert app.annotation_palette is None
        assert len(app.history._undo) == 1

        # Save As -> PNG (file and options dialogs stubbed), then reload.
        out = tmp_path / "annotated.png"
        monkeypatch.setattr(
            commands, "filedialog", types.SimpleNamespace(asksaveasfilename=lambda **k: str(out))
        )
        monkeypatch.setattr(
            "pxv.dialogs.save_options_dialog", lambda *a, **k: (app.save_options, False)
        )
        assert commands.cmd_save_as(app) is True
        assert app.annotations_unsaved is False  # the save cleared the flag

        reloaded = Image.open(out)
        assert reloaded.size == (100, 80)
        assert reloaded.getpixel((25, 60)) == (255, 0, 0)  # arrow shaft
        assert reloaded.getpixel((60, 30)) == (255, 0, 0)  # MOVED rect's left edge
        assert reloaded.getpixel((50, 25)) == (0, 0, 255)  # pre-move spot never baked
        assert reloaded.getpixel((75, 30)) == (0, 0, 255)  # outline rect stays hollow
        label_area = list(reloaded.crop((10, 10, 25, 25)).getdata())
        assert any(px != (0, 0, 255) for px in label_area)  # glyph pixels landed
    finally:
        root.destroy()


def test_transparent_png_annotation_preserves_alpha(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Spec edge case: apply_overlay paints both buffers — alpha survives the save."""
    from pxv.app import PxvApp
    from pxv.file_list import FileList

    src = tmp_path / "alpha.png"
    Image.new("RGBA", (60, 50), (0, 200, 0, 120)).save(src)
    root = tk.Tk()
    try:
        app = PxvApp(root, FileList([src]))
        root.update()
        app.load_current()
        root.update()
        assert app.image_model._save_rgba is not None  # transparency detected at load

        commands.cmd_annotate(app)
        palette = app.annotation_palette
        assert palette is not None
        _draw_line(palette, y=25.0)  # red line (10,25)-(40,25), width 2
        palette._on_done()

        out = tmp_path / "alpha_out.png"
        monkeypatch.setattr(
            commands, "filedialog", types.SimpleNamespace(asksaveasfilename=lambda **k: str(out))
        )
        monkeypatch.setattr(
            "pxv.dialogs.save_options_dialog", lambda *a, **k: (app.save_options, False)
        )
        assert commands.cmd_save_as(app) is True

        reloaded = Image.open(out).convert("RGBA")
        assert reloaded.size == (60, 50)
        assert reloaded.getpixel((5, 5)) == (0, 200, 0, 120)  # alpha intact off-stroke
        assert reloaded.getpixel((25, 25)) == (255, 0, 0, 255)  # opaque stroke pixel
    finally:
        root.destroy()
```

Notes for the executor (why each stub/assert is shaped this way — all pinned by earlier phases):

- `"pxv.dialogs.save_options_dialog"` must be patched on the *module* — `cmd_save_as` imports it inside the function body (commands.py:144), so the module attribute is read at call time. It returns `(SaveOptions, keep_metadata)`; passing `app.save_options` straight through keeps the session defaults.
- `cmd_save_as(app) is True` and the flag-clear are the Phase 2 contract (`-> bool`, success clears `annotations_unsaved`).
- The Select move asserts `translated()` semantics from Phase 3: press (50,20) → release (60,30) moves the shape AS PRESSED by (+10,+10).
- The shaft/edge pixel asserts reuse Phase 2's precedent (a width-2 stroke covers the row/column through its endpoints — `test_done_bakes_exactly_one_history_snapshot` pinned the same geometry).
- The label assert is deliberately loose (any non-background pixel in the heuristic bbox region): glyph coverage differs between Pillow's scalable and bitmap fallback fonts, and the one-shot "no scalable font" hint (Phase 4) is harmless here.
- The transparent variant reuses the Phase 2 helper `_draw_line(palette, y=25.0)`; on a 60-px-long side the medium preset is still `max(2.0, 60/400) = 2.0`.

- [ ] **Step 2: Run the tests**

Run: `DISPLAY=:99 uv run pytest tests/test_annotation_mode.py -v`
Expected: 66 PASS (64 + 2 new). If either new test fails, STOP and debug the integration (do not adjust the asserted pixels without understanding why they moved).

- [ ] **Step 3: Format, typecheck, commit**

```bash
uv run ruff format tests/test_annotation_mode.py
uv run mypy src/pxv
git add tests/test_annotation_mode.py
git commit -m "test(draw): end-to-end session and transparent-PNG integration tests

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: README + CHANGELOG

Docs only — no tests. Markdown files are not run through ruff/mypy.

**Files:** Modify `README.md`; modify `CHANGELOG.md`.

- [ ] **Step 1: README — keyboard table**

(a) Line 88 is stale (1.0.4 made `u` a general undo; the in-app table already says "Undo"). Replace:

```markdown
| `u` | Uncrop (undo last crop) |
```

with:

```markdown
| `u` / `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |
```

(b) After line 95, `| `e` | Enhancement dialog |`, insert:

```markdown
| `d` | Draw / annotate (drawing palette) |
```

- [ ] **Step 2: README — Annotations section, Features bullet, Pillow floor**

(a) The Enhancements section ends at line 119 (`bakes the adjustments into the working image (undoable with `u`/Ctrl+Z).`) and `## Features` starts at line 121. Insert between them (blank line above and below):

```markdown
## Annotations

Draw mode (`d`, or right-click → Draw / Annotate...) opens a tool palette and
turns the canvas into a drawing surface:

- **Tools** (keys `1`–`8`) — Select, freehand, line, arrow, rectangle,
  ellipse, highlighter, and text labels
- **Styling** — six color swatches plus a custom chooser, thin/medium/thick
  size presets (auto-scaled to the image size), filled-vs-outline toggle, and
  an opacity slider; with a shape selected, the controls restyle it live
- **Editing** — the Select tool picks the topmost shape: drag to move,
  `Delete`/`Backspace` to remove, `u`/`Ctrl+Z`/`Ctrl+Y` for in-mode
  undo/redo; double-click a text label to re-edit it

Shapes stay editable vector objects while the palette is open, and their
sizes are in image pixels — the saved file is independent of the zoom you
drew at. **Done** (or closing the palette window) bakes them into the image
as a single undoable edit; **Cancel** discards them after confirmation.
Navigating away or quitting with unsaved annotation work prompts first.
```

(b) In the `## Features` list (first bullet currently at line 123: `- Histogram, levels, and curves in the enhancement dialog ...`), insert a new first bullet above it:

```markdown
- Image annotations / draw mode: freehand, lines, arrows, boxes, ellipses, highlighter, and text labels — editable vectors during the session, baked as one undoable edit
```

(c) In `## Requirements` (line 137), replace:

```markdown
- Pillow 10+
```

with (Phase 1 raised the pyproject floor for `ImageFont.load_default(size=...)`):

```markdown
- Pillow 10.1+
```

- [ ] **Step 3: CHANGELOG — Unreleased entry and link refs**

(a) After line 6 (`and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/).`) and before `## [1.0.5] - 2026-06-10` (line 8), insert:

```markdown
## [Unreleased]

### Added
- Image annotations (draw mode): press `d` (or right-click → Draw / Annotate...)
  for a tool palette with freehand, line, arrow, rectangle, ellipse,
  highlighter, and text-label tools, plus a Select tool for moving, restyling,
  and deleting placed shapes. Color swatches with a custom chooser,
  thin/medium/thick size presets that scale with the image, a fill toggle, an
  opacity slider, and in-mode undo/redo. Shapes stay editable vectors during
  the session and bake into the image as a single undoable edit on Done;
  annotations survive alpha-preserving saves of transparent images, and
  navigating or quitting with unsaved annotation work prompts first.
```

(b) The link block at the bottom (lines 127–131) is missing 1.0.4/1.0.5 and points Unreleased at v1.0.3. Replace:

```markdown
[Unreleased]: https://github.com/linsomniac/pxv/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/linsomniac/pxv/compare/v1.0.2...v1.0.3
```

with:

```markdown
[Unreleased]: https://github.com/linsomniac/pxv/compare/v1.0.5...HEAD
[1.0.5]: https://github.com/linsomniac/pxv/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/linsomniac/pxv/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/linsomniac/pxv/compare/v1.0.2...v1.0.3
```

(the `[1.0.2]`, `[1.0.1]`, `[1.0.0]` lines below stay as they are).

- [ ] **Step 4: Sanity-check and commit**

Verify the suite is untouched: `uv run pytest tests/test_commands.py -q` (14 pass). Then:

```bash
git add README.md CHANGELOG.md
git commit -m "docs(draw): README annotations section and shortcut rows; CHANGELOG entry

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Full-suite verification + smoke

**Files:** none (verification only)

- [ ] **Step 1: Full suite under a display**

```bash
DISPLAY=:99 uv run pytest
```
Expected: 411 collected (405 after Phase 4 + 4 annotation-mode + 2 commands), 0 failures. If Phase 4's final count differed, reconcile against the +6 delta.

- [ ] **Step 2: Lint + typecheck**

```bash
uv run ruff format --check src tests
uv run mypy src/pxv
```
Expected: no reformats, mypy clean.

- [ ] **Step 3: Manual smoke under Xvfb — the released surface**

```bash
DISPLAY=:99 uv run python - << 'EOF'
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from pxv import commands
from pxv.app import PxvApp
from pxv.file_list import FileList

src = Path("/tmp/polish_smoke.png")
Image.new("RGB", (320, 240), (30, 30, 60)).save(src)

root = tk.Tk(className="pxv")
root.geometry("800x600")
app = PxvApp(root, FileList([src]))
root.update()
app.load_current()
root.update()

# 1. The context-menu entry exists and opens the palette through cmd_annotate.
menu = app.context_menu.menu
end = menu.index("end")
labels = {menu.entrycget(i, "label"): i for i in range(end + 1) if menu.type(i) == "command"}
assert "Draw / Annotate..." in labels, labels
menu.invoke(labels["Draw / Annotate..."])
palette = app.annotation_palette
assert palette is not None

# 2. Per-tool cursors: Select arrow, drawing pencil, text I-beam.
cursors = {}
for key in ("1", "2", "8"):
    palette.select_tool_key(key)
    cursors[key] = app.canvas_view.canvas.cget("cursor")
assert cursors == {"1": "", "2": "pencil", "8": "xterm"}, cursors

# 3. Draw, edit, label, Done — the full session.
palette.select_tool_key("4")
palette.on_press((40.0, 200.0)); palette.on_drag((200.0, 80.0)); palette.on_release((200.0, 80.0))
palette.select_tool_key("5")
palette.on_press((220.0, 60.0)); palette.on_drag((300.0, 140.0)); palette.on_release((300.0, 140.0))
palette.select_tool_key("1")
palette.on_press((220.0, 100.0)); palette.on_drag((230.0, 110.0)); palette.on_release((230.0, 110.0))
palette.select_tool_key("8")
palette.on_press((20.0, 20.0))
root.update()
assert palette._text_entry is not None
palette._text_entry.insert(0, "smoke")
palette._on_text_popup_return(SimpleNamespace())
assert len(palette.layer.shapes) == 3
palette._on_done()
assert app.annotation_palette is None and len(app.history._undo) == 1

# 4. Save As writes the annotated PNG and clears the dirty flag.
out = "/tmp/polish_smoke_out.png"
commands.filedialog = SimpleNamespace(asksaveasfilename=lambda **k: out)
import pxv.dialogs as dialogs
dialogs.save_options_dialog = lambda *a, **k: (app.save_options, False)
assert commands.cmd_save_as(app) is True
assert app.annotations_unsaved is False

# 5. The help table carries the new rows.
from pxv.dialogs import KEYBINDINGS
keys = [k for k, _d in KEYBINDINGS]
assert "d" in keys and "1-8" in keys

root.destroy()
print("smoke OK ->", out)
EOF
```

Expected: `smoke OK`. Visually inspect `/tmp/polish_smoke_out.png` (red arrow pointing up-right, a red outline rectangle shifted 10px down-right of (220,60), the word "smoke" near the top-left), then delete `/tmp/polish_smoke.png` and `/tmp/polish_smoke_out.png`. Report exact results.

---

## Out of scope (feature complete after this phase)

- Resize/endpoint handles on placed shapes; annotations persisting across navigation or after bake; sidecar files; blur/redaction/stamp tools; custom fonts; enhancement-compensated bake colors — all permanently out of scope per the spec.
- Version bump / release (`gh release create`) — Sean handles the release flow after merge.
