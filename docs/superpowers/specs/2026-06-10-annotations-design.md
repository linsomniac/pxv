# Image Annotations (Draw Mode) — Design

**Date:** 2026-06-10
**Ideas:** User-requested (not in Ideas.md): simple markup — freehand, arrows,
circles, squares — for pointing out parts of an image.

## Background

pxv has no way to mark up an image. The building blocks all exist: pure
canvas↔image geometry (`canvas_point_to_image_xy`, `selection_to_image_box` in
`canvas_view.py`), a bounded snapshot history (`history.py`, 20 levels, one
snapshot per edit), an interactive-canvas-mode precedent (the eyedropper pick
mode: cursor signaling, disarm-on-close, stale-image guard), and a non-modal
tool-window convention (the Enhance dialog).

This feature adds a **draw mode**: a palette window that, while open, turns
the canvas into a drawing surface with seven tools. Shapes stay editable
vector objects during the session and are baked into the image pixels when the
session ends — one undoable edit, following the crop/rotate command pattern.

## Decisions (from brainstorming)

- **Hybrid storage:** shapes are vector objects while draw mode is active
  (movable, deletable, restylable), then rasterized into `working_image` and,
  when present, `_save_rgba` on exit. The normal viewing path is untouched
  when the mode is off.
- **Tools (7 + Select):** freehand, straight line, arrow, rectangle, ellipse,
  highlighter, text labels — plus a Select tool for editing placed shapes.
- **Styling:** preset color swatches (red, yellow, green, blue, white, black)
  plus a custom color chooser; thin/medium/thick size presets (stroke widths,
  doubling as text sizes); filled-vs-outline toggle for rect/ellipse; opacity
  slider.
- **Sizes in image pixels:** the saved file is independent of the zoom you
  drew at; on screen strokes scale with zoom. Presets auto-scale from the
  image's longest side (formula under `size_presets` below).
- **Palette window UX:** a non-modal Toplevel (Enhance-dialog style) opened
  with `d` or the context menu. Palette open ⇔ draw mode active — every path
  that ends the mode goes through one `_end_session()` that destroys the
  window. **Done** (or closing the window — window close is treated as a
  deliberate Done) bakes; **Cancel** discards after confirmation. `d` with
  the palette already open raises and focuses it (enhancement-dialog
  precedent); it never closes or bakes.
- **Hybrid rendering:** committed shapes render via PIL into an RGBA overlay
  composited onto the display image — the same renderer and code path as the
  bake, so opacity/highlighter/anti-aliasing preview faithfully (geometry is
  equivalent across scales, not bit-identical; thin strokes at low zoom are
  clamped to 1 display px). Only the in-flight drag uses a lightweight Tk
  canvas item (Tk items cannot do per-item alpha), swapped for the PIL render
  at release.
- **Annotation-specific dirty flag:** navigation/quit with unsaved annotation
  work prompts "Discard annotations?". Other edits keep today's
  silent-discard behavior. Full lifecycle under *Dirty flag* below.
- **Geometry lives in image coordinates** as unclamped floats. Canvas coords
  go stale on every zoom/pan/resize; points are converted per event by a
  *new* pure helper (the existing `canvas_point_to_image_xy` truncates to int
  and returns None outside the image — it is the precedent, not the function
  used). Out-of-image points pass through unclamped; clipping happens at
  render time.
- **Enhancement interaction accepted:** during the mode the overlay
  composites on top of the *enhanced* display image. Preview/bake parity
  therefore holds exactly when `EnhancementParams` is identity (the common
  case). With non-identity live params, annotation pixels become subject to
  the enhancement pass at Done — colors visibly shift at that moment and in
  the saved file. Accepted and documented with an AIDEV-NOTE at the bake
  site; a smarter treatment is out of scope.

## Components

### `annotations.py` (new, pure — no Tk, no PIL)

```python
Tool = Literal["freehand", "line", "arrow", "rect", "ellipse",
               "highlight", "text"]

@dataclass(frozen=True)
class Shape:
    tool: Tool
    points: tuple[tuple[float, float], ...]  # image coords; freehand/highlight: many,
                                             # line/arrow/rect/ellipse: 2, text: 1 anchor
    color: str                               # "#rrggbb"
    width_px: float                          # stroke width in image pixels
    fill: bool = False                       # rect/ellipse only
    opacity: float = 1.0                     # 0.0–1.0
    text: str = ""                           # text tool only
    font_px: float = 0.0                     # text tool only

    def translated(self, dx: float, dy: float) -> "Shape": ...
    def bbox(self) -> tuple[float, float, float, float]: ...

class AnnotationLayer:
    """Ordered shapes (z = insertion order), selection, in-mode undo/redo."""
    shapes: tuple[Shape, ...]
    selected: int | None
    revision: int   # monotonically increasing; bumped by every mutator
                    # (the overlay cache key)

    def add(self, shape: Shape) -> None: ...
    def delete_selected(self) -> None: ...
    def replace_selected(self, shape: Shape) -> None: ...   # restyle / move / edit text
    def select_at(self, xy: tuple[float, float], tol: float) -> int | None: ...
    def undo(self) -> bool: ...   # each mutator pushes the prior shapes-tuple
    def redo(self) -> bool: ...   # onto a state stack; redo clears on new action

def hit_test(shapes: Sequence[Shape], xy: tuple[float, float],
             tol: float) -> int | None:
    """Topmost hit: distance-to-polyline for freehand/highlight/line/arrow,
    border (or interior when filled) for rect/ellipse, bbox for text.
    tol is in image pixels; the caller computes it as
    max(shape-independent 6.0 / zoom, width_px / 2). select_at delegates here."""

@dataclass(frozen=True)
class SizePresets:
    widths: tuple[float, float, float]   # thin, medium, thick
    fonts: tuple[float, float, float]    # small, medium, large

def size_presets(image_long_side: int) -> SizePresets:
    """medium width = max(2.0, long_side/400); thin = max(1.0, medium/2);
    thick = medium*2. medium font = max(12.0, long_side/40);
    small = medium/1.5; large = medium*1.5."""
```

Frozen shapes give the undo stack the same alias-safety the history snapshots
get by deep-copying buffers — without the copies. Consecutive
`replace_selected` calls on the same shape index **coalesce** into one undo
state (so dragging the opacity slider, or moving a shape, is one undo step,
not dozens). Text `bbox()` is a pure heuristic — width `0.6 × font_px ×
len(text)`, height `1.2 × font_px`, anchored top-left at the click point —
accepted as approximate for hit-testing and the selection marker (PIL font
metrics are forbidden in this module).

### `annotation_render.py` (new, pure PIL — no Tk)

```python
def render_overlay(shapes: Sequence[Shape], target_size: tuple[int, int],
                   scale: float) -> Image.Image:
    """RGBA image of EXACTLY target_size; scale only transforms image-space
    coordinates and widths into target space. Preview passes the actual
    display image's .size and zoom (never a derived size — get_display_image
    rounds independently); the bake passes working_image.size and 1.0.
    Same code path both ways."""

def arrow_head(p0, p1, width_px) -> tuple[tuple[float, float], ...]:
    """Filled triangular head at p1, length max(3.0 × width_px, 8.0) image px,
    oriented along p0→p1. Pure geometry, unit-testable."""

def scalable_font_available() -> bool: ...
```

Per-tool drawing via `ImageDraw` on the RGBA overlay: opacity becomes the
alpha of the drawn color; highlighter is a round-joint stroke at `4 × width_px`
wide and `0.4 × opacity` alpha; text draws top-left-anchored. Stroke widths
become `max(1, round(width_px × scale))`. Coordinates are scaled before
drawing (never render full-res and downscale). Text uses Pillow's scalable
embedded font (`ImageFont.load_default(size=...)`) — **this bumps the
pyproject floor to `pillow>=10.1`**, the "concrete API need" its AIDEV-NOTE
anticipates. A `try/except ImportError` fallback to the bitmap default covers
FreeType-less Pillow builds; this module stays silent about it (pure) — the
palette consults `scalable_font_available()` and shows a one-time title-bar
hint via `show_temp_title`.

### `annotation_palette.py` (new)

`AnnotationPalette(tk.Toplevel)` — owns the `AnnotationLayer` and the session.
The app holds it as `app.annotation_palette` (None when closed), exactly like
`app.enhancement_dialog`.

- Tool buttons (Select + 7 tools), color swatches + custom chooser
  (`tkinter.colorchooser`), size presets, fill checkbox, opacity slider,
  **Done** / **Cancel**. Styling controls set the defaults for new shapes;
  with a selection they restyle it live (coalesced to one undo step).
- Tool numbering is stable across phases: `1` Select, `2` freehand, `3` line,
  `4` arrow, `5` rect, `6` ellipse, `7` highlighter, `8` text — keys for
  not-yet-shipped tools are inert in earlier phases.
- **Session protocol** (called by `CanvasView` and the app):
  `on_press(image_xy)`, `on_drag(image_xy)`, `on_release(image_xy)`,
  `is_dragging` (property), `render_display_overlay(target_size, scale)`.
- Drag tools (2–7): rubber-band preview during the drag (the highlighter's
  preview is an outline-only Tk polyline, since translucency is impossible in
  Tk — the true translucent render appears at release), exact PIL render on
  release; drags under 3.0 screen px (Euclidean) are discarded.
- Text tool: click opens a small **overrideredirect Toplevel** holding an
  Entry at the click point — outside the root window's bindtag chain, so
  typing space/q/BackSpace cannot trigger root bindings; its Return/Escape
  handlers `return "break"`. Enter with non-empty text places the label
  (top-left anchor at the click point); empty Enter or Escape cancels with no
  shape. A text-tool click on an existing label starts a *new* overlapping
  label; re-editing is Select-double-click only. Any session-ending or
  view-changing event (zoom, navigation, Done, stale-image guard) cancels an
  open popup.
- Select tool: click selects topmost hit (dashed-bbox marker), drag moves,
  click on empty deselects, double-click on a text shape reopens the entry
  popup pre-filled.
- Window close (`WM_DELETE_WINDOW`) = **Done**. Cancel with a non-empty layer
  asks for confirmation. Both tear down via a single `_end_session(bake:
  bool)` that disarms the canvas first (eyedropper `_on_close` pattern).
- **Stale-image guard** (last-resort net; normal flows are gated/prompted —
  see key gating): identity of `working_image` is checked at two points — in
  the overlay hook before compositing, and at bake start before
  `apply_overlay`. On a trip: `_end_session(bake=False)`, shapes discarded
  without a prompt (the image they referenced is gone), title-bar message
  "drawing cancelled — image changed". The palette-open ⇔ mode-active
  invariant survives because the guard destroys the window.

### `canvas_view.py` — changes

- Two new pure helpers alongside the existing geometry functions, both
  exercised in `test_canvas_geometry.py`: `canvas_point_to_image_xy_f`
  (unclamped floats, no None case — same centering/zoom math; the annotation
  session's converter) and its inverse `image_xy_to_canvas_point` (for
  drawing transient items from image-space truth).
- `set_annotation_session(session | None)`: while set, drawing tools show the
  `pencil` cursor and Select shows the default arrow (the canvas is *already*
  `crosshair` normally, so the mode is visually distinct); any existing
  rubber-band selection is cleared on entry and selection handling is
  suspended; `_on_press`/`_on_drag`/`_on_release` forward image coords (via
  the float helper) to the session — multiplexed ahead of selection handling,
  the way pick mode already short-circuits `_on_press`. A new
  `<Double-Button-1>` binding forwards `on_double_click(image_xy)`; the
  double-click handler wins over the second press's select/drag
  interpretation via the same cancelled-until-release latch Escape uses.
- Transient-item helpers, all taking **image-space** geometry and converting
  internally: `set_preview_shape(...)` / `clear_preview()` (one Tk item) and
  `set_selection_marker(bbox | None)` (dashed rectangle). Items are re-derived
  whenever the display re-renders at a new zoom/size.
- `_on_mouse_wheel` consults `session.is_dragging` and ignores wheel events
  while a drag is in flight (the wheel is pxv's only pan input, so view
  changes mid-drag reduce to zoom keys — see key gating; per-event coordinate
  conversion is retained as defense in depth).

### `image_model.py` — changes

`apply_overlay(overlay: Image.Image) -> None`: alpha-composite a full-
resolution RGBA overlay onto `working_image` (RGB paste-with-mask) and, when
`_save_rgba` is present, onto it too (proper RGBA `alpha_composite`) — in
lockstep, so annotations survive alpha-preserving saves of transparent
images.

### `commands.py` / `app.py` / `context_menu.py` — changes

- `cmd_annotate` opens the palette (no-op with no image; gated while the
  Enhance dialog is open, and vice versa — `e` is gated during draw mode so
  pick mode and draw mode can never share the canvas). Opening the mode stops
  an active slideshow.
- **Display compositing:** the overlay composite moves into one shared helper
  used by *both* display paths — `refresh_display()` and the resize path
  `_update_display()` — otherwise shapes vanish on window resize. If a
  session is active and the layer non-empty it calls
  `session.render_display_overlay(display_img.size, zoom)` and composites
  before `CanvasView.display()`. Only the rendered RGBA overlay is cached,
  keyed on `(layer.revision, display_size)`; it composites onto the fresh
  base image every refresh (the base changes under the same key via
  enhancement debounce, Compare, background toggle).
- **Bake** (invoked by Done; owner: `app.bake_annotations(shapes)`, called
  from `_end_session(bake=True)`): empty layer → exit silently, no snapshot.
  Otherwise the crop/rotate pattern — `record_history()` →
  `render_overlay(shapes, working_image.size, 1.0)` →
  `model.apply_overlay(...)` → set `annotations_unsaved` →
  `refresh_display()`. (The empty check happens up front, so autocrop's
  conditional snapshot dance is not needed.)
- **Key/command gating while the mode is active** — one helper checked at the
  top of the affected `cmd_*` functions. Root-level keys and context-menu
  entries call the same `cmd_*` functions, so a single chokepoint covers
  both:
  - *Undo/redo* — all entry points (`u`, `Ctrl-z`, `Ctrl-y`, `Ctrl-Shift-Z`,
    context-menu Undo/Redo) route to the layer's undo/redo. When the layer
    stack is empty the key is consumed and does nothing — it never falls
    through to app history while the mode is active.
  - *Image-mutating commands* (crop, autocrop, rotate, flip, resize, reset,
    enhance) — consumed with a title-bar hint via `show_temp_title` ("close
    the drawing palette first").
  - *Save* (`Ctrl-s`, context-menu Save As…) — consumed with the same hint.
  - *Navigation/replacement* (space, arrows, BackSpace with no selection,
    slideshow toggle, `cmd_open`, and the Visual Schnauzer's activation path
    `cmd_show_index`) — triggers the discard prompt; confirming cancels the
    session and proceeds.
  - *While a drag is in flight* (`session.is_dragging`), zoom and navigation
    commands are consumed outright.
- **Focus split** (the root-bindings AIDEV-NOTE in `app.py`): root-bound keys
  fire when the canvas has focus (it takes focus on click). The palette
  Toplevel additionally mirrors the in-mode keys onto itself — `1`–`8`,
  `Ctrl-z`/`Ctrl-y`/`Ctrl-Shift-Z`, `u`, `Delete`, `Escape` — so they work
  right after clicking a palette control. Navigation/save keys are
  intentionally *not* mirrored. `1`–`8` are also bound on root, gated to
  mode-active.
- `Escape` is consumed entirely by the session while the mode is active:
  cancel an in-flight drag (setting a latch that swallows motion/release
  events until the physical ButtonRelease), else deselect, else nothing — it
  never exits the mode (no accidental bakes) and never reaches
  `escape_action`, so exiting fullscreen during a session requires `f`/F11.
  `Delete` (and `BackSpace` with a selection) deletes the selected shape.
- **Dirty flag lifecycle** (`annotations_unsaved`): set on the first shape
  added and on bake; cleared by (a) a successful save — `cmd_save_as` gains a
  success return, since today it returns None on save, cancel, and failure
  alike, and the flag must survive a cancelled save-dialog — (b) the user
  confirming a discard prompt, and (c) completion of an image load
  (`load_current`), so the flag never follows you to the next image.
- **Quit:** `q` / context-menu Quit check the flag and prompt. The root
  window gains a `WM_DELETE_WINDOW` protocol handler routing through the same
  prompt-then-quit path (today the titlebar close button bypasses `cmd_quit`
  entirely).
- Context menu gains "Draw / Annotate…"; the `?` keyboard-shortcuts dialog
  (`KEYBINDINGS` table in `dialogs.py`) and README gain `d` ("draw /
  annotate" — distinct from the existing `D`, background toggle).

### History / undo

**No changes to `history.py`.** A bake is one ordinary snapshot edit: undo
after exiting removes that whole annotation session. In-mode granular
undo/redo lives entirely in `AnnotationLayer`.

## Phasing (each independently shippable)

1. **Core engine** — `annotations.py` + `annotation_render.py` (including the
   two new pure geometry helpers in `canvas_view.py`), pure, fully tested.
   Pillow floor bump. No UI.
2. **Draw mode MVP** — palette, canvas session plumbing, freehand / line /
   arrow / rect / ellipse (keys `2`–`6`), color + sizes, bake, full
   key/command gating, dirty-flag prompts, root `WM_DELETE_WINDOW` handler.
   Usable end-to-end here. In-mode undo/redo keys are swallowed with a
   title-bar hint ("undo arrives with the Select tool") — layer routing
   arrives in Phase 3.
3. **Editing** — Select tool (key `1`): hit-test selection, move, delete,
   restyle, in-mode undo/redo (incl. coalescing).
4. **Full kit** — text labels (key `8`, entry popup, double-click re-edit),
   highlighter (key `7`), opacity slider, fill toggle.
5. **Polish** — context-menu entry, `?` dialog + README/CHANGELOG, per-tool
   cursor refinements.

## Edge cases

- **Transparent images:** `apply_overlay` paints both buffers in lockstep;
  an integration test covers annotate→save-PNG→alpha intact.
- **Zoom/pan/resize mid-session:** geometry is image-space; the overlay
  re-renders at the new scale (both display paths share the composite
  helper) and transient Tk items are re-derived from image-space truth.
- **Drag interruptions:** wheel ignored during a drag; zoom/nav commands
  consumed during a drag; Escape's cancel latch swallows events until the
  physical release.
- **Mid-session navigation/quit:** discard prompt; confirming cancels the
  session (and clears the flag) before proceeding — no orphaned canvas state,
  and no re-prompt on the next image.
- **Image replaced under the session:** can only happen through unguarded
  surprises (the gating covers every known path) — the stale-image guard
  cancels the session with a title-bar message rather than crashing or baking
  against the wrong image.
- **Empty bake:** Done with no shapes exits without recording history.
- **Shape moved partly/fully outside the image:** allowed; coordinates are
  unclamped and rendering clips at the overlay edges.
- **Tiny accidental drags** (< 3 screen px): discarded, no shape.
- **Enhancement params at bake:** see Decisions — parity at identity params;
  shift at Done otherwise. AIDEV-NOTE at the bake site.
- **Undo past the bake:** `annotations_unsaved` stays set conservatively; the
  prompt may fire once with nothing visibly at stake. Accepted.
- **Performance:** committed-overlay re-render happens per layer revision and
  per zoom/size change, not per motion event; drags move one Tk item. Full-res
  bake render happens once, at Done.

## Testing

Pure logic display-free; Tk wiring DISPLAY-gated (Xvfb, existing convention).

- **`tests/test_annotations.py`** (new, pure): `Shape.translated`/`bbox`
  (incl. the text-bbox heuristic formula); layer add/delete/replace/selection;
  undo/redo state-stack semantics (mutate→undo→redo round-trips, redo cleared
  on new action, `replace_selected` coalescing = one step); `revision`
  monotonicity; `hit_test` topmost-wins, per-tool hit geometry, tolerance
  formula, filled-vs-outline interior hits; `size_presets` formulas and
  minimums.
- **`tests/test_annotation_render.py`** (new, pure): pixel asserts on small
  canvases — line/rect/ellipse coverage, arrowhead orientation and length via
  `arrow_head`, opacity alpha values, highlighter width multiplier and alpha,
  fill vs outline, text renders non-empty, exact `target_size` honored;
  **scale equivalence**: the same shapes rendered at `(N, scale=1.0)` vs
  `(2N, scale=2.0)` compared by IoU of drawn masks (widths ≥ 4 px so the 1-px
  clamp can't skew it); clipping of out-of-bounds shapes.
- **`tests/test_canvas_geometry.py`** (extend, pure):
  `canvas_point_to_image_xy_f` float/unclamped behavior incl. out-of-image
  points; `image_xy_to_canvas_point` round-trips with it.
- **`tests/test_image_model.py`** (extend): `apply_overlay` mutates RGB and
  RGBA buffers in lockstep; opaque image keeps `_save_rgba is None`.
- **DISPLAY-gated** (new `tests/test_annotation_mode.py`): palette opens and
  arms the canvas; `event_generate` press/drag/release creates a shape and
  the overlay composite appears (incl. after a simulated resize through
  `_update_display`); Select-click/move/Delete; undo keys route to the layer
  while open (consumed when its stack is empty) and to app history when
  closed; gated commands show the hint and do nothing; Done bakes exactly one
  history snapshot and Cancel bakes none; close-window = Done; navigation key
  triggers the discard prompt, and bake→navigate-confirm→navigate again does
  NOT re-prompt; `e`/`d` mutual gating; text popup confines keystrokes
  (space in the Entry must not navigate).

## Out of scope

- Resize/endpoint handles on placed shapes (undo and redraw instead).
- Annotations persisting across image navigation, sidecar files, or any
  re-editability after bake.
- Full app-wide dirty tracking for crop/rotate/enhance (annotations only).
- Blur/pixelate/redaction tools, stamps, or numbered callout badges.
- Custom fonts or font selection for text labels (Pillow's embedded font).
- Compensating annotation colors for non-identity enhancement params at bake
  (e.g. inverse-mapping the colors); documented as accepted instead.
