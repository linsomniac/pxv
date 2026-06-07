# Mouse-wheel zoom-to-cursor + drag-to-pan — design

**Idea #6** (Ideas.md): "Mouse-wheel zoom-to-cursor + drag-to-pan — biggest *feels-modern* gap."
Today the wheel only *pans* (`canvas_view.py:_on_mouse_wheel`) and zoom is keyboard-only,
always growing the window to the image and re-centering. This makes the wheel feel dated and
gives no cursor-anchored zoom. This design adds modern wheel-zoom-to-cursor and Shift+drag
panning while leaving the keyboard zoom and the xv-style window behavior intact.

## Goals

- Plain mouse-wheel zooms the image, anchored on the pointer, inside a **fixed window**.
- `Shift`+left-drag pans the image when it is larger than the viewport.
- Leave left-drag region selection, right/middle-click context menu, and all keyboard
  bindings exactly as they are today.

## Decisions (settled during brainstorming)

1. **Fixed viewport for the wheel only.** Wheel-zoom keeps the current window size, zooms the
   image toward the pointer, and lets the image overflow the viewport so it can be panned.
   Keyboard zoom (`. , < > n M`) is **unchanged**: it still grows the window to fit the zoomed
   image and re-centers (xv-style). This is the lowest-risk option; the only wart is that
   pressing a keyboard-zoom key after wheel-zooming snaps the window back to fit the image.
   That is accepted, expected behavior.
2. **Pan = `Shift`+left-drag only.** No middle-drag: `Button-2` is already bound to the context
   menu on every platform (it exists for macOS right-click emulation but fires on
   Linux/Windows too), so middle-drag would collide with that and need click-vs-drag
   disambiguation. `Shift`+left-drag has no conflict and is identical cross-platform.
3. **Wheel-panning is removed**, replaced by drag-to-pan per the idea.

## Background: how zoom is rendered today

Zoom is **baked into the bitmap**, not applied by the canvas:

- `ImageModel.get_display_image(zoom, params, bg)` physically resizes the working image to
  `size × zoom` pixels (NEAREST above 2×, else LANCZOS) and applies enhancements.
- `PxvApp.refresh_display()` then (unless fullscreen) calls `_resize_window_to_image()` to size
  the OS window to the zoomed bitmap (capped at the monitor), and `CanvasView.display()`
  re-centers the image whenever its pixel size changed.
- `CanvasView` is otherwise a centered bitmap on a `tk.Canvas` whose `scrollregion` is
  `max(canvas, display)` on each axis; panning/scrolling only does anything once the bitmap
  exceeds the viewport.

Consequence: in windowed mode the window grows to fit the image, so there is normally nothing
to pan and "zoom to cursor" has no visible effect. Cursor-anchored zoom is only meaningful when
the image is larger than the viewport — which is exactly what a **fixed** window during
wheel-zoom produces.

## Behavior

| Gesture | Action |
|---|---|
| Wheel up / down (any modifier) | Zoom in / out by `WHEEL_ZOOM_FACTOR` per notch, anchored on the pointer, window fixed |
| `Shift` + left-drag | Pan (cursor `crosshair` → `fleur`, restored on release) |
| Left-drag | Region selection (unchanged) |
| Right-click / middle-click | Context menu (unchanged) |
| `. , < > n M` (keyboard) | Zoom, growing the window + re-centering (unchanged) |

Notes:
- Zooming out below the viewport degrades naturally to a centered image (no scroll room).
- The rubber-band selection rectangle is a canvas item, so it pans with the content and stays
  anchored to its image region; panning does **not** clear an existing selection.
- In fullscreen the window is already monitor-sized and fixed, so wheel-zoom-to-cursor behaves
  identically there with no special-casing.

## Input bindings (`CanvasView._bind_mouse`)

- **Keep:** `<ButtonPress-1>` / `<B1-Motion>` / `<ButtonRelease-1>` (selection);
  `<Button-2>` / `<Button-3>` (context menu).
- **Add:** `<Shift-ButtonPress-1>`, `<Shift-B1-Motion>`, `<Shift-ButtonRelease-1>` → pan
  handlers. These are more specific than the plain Button-1 bindings, so when Shift is held at
  press time Tk dispatches the pan handlers and selection never starts.
- **Repoint to the zoom handler:** `<MouseWheel>` (Windows/macOS), `<Button-4>` / `<Button-5>`
  (X11). **Remove** the `<Shift-MouseWheel>` / `<Shift-Button-4>` / `<Shift-Button-5>` pan
  bindings. With no Shift-specific wheel binding present, the plain `<MouseWheel>` /
  `<Button-4/5>` bindings still fire while a modifier is held, so Shift/Ctrl+wheel also zoom —
  there is no wheel gesture that pans.

## Zoom-to-cursor geometry (pure, unit-tested)

A module-level pure function in `canvas_view.py`, mirroring the existing
`selection_to_image_box` pattern so the math is testable without a live Tk display. Per axis:

```python
def zoom_view_fraction(
    pointer: float,     # event.x (or event.y): pointer offset within the widget
    canvas_pt: float,   # canvas.canvasx(event.x): canvas-space coord under the pointer now
    working: int,       # working-image dimension on this axis (px)
    canvas: int,        # canvas (viewport) dimension on this axis (px)
    zoom_old: float,
    zoom_new: float,
) -> float:
    """xview/yview fraction that keeps the image pixel under the pointer fixed."""
```

Math (per axis):

```
disp_old   = working * zoom_old
region_old = max(canvas, disp_old)
off_old    = (region_old - disp_old) / 2          # centering offset
img_coord  = (canvas_pt - off_old) / zoom_old      # image-space pixel under the cursor

disp_new   = working * zoom_new
region_new = max(canvas, disp_new)
off_new    = (region_new - disp_new) / 2
canvas_new = off_new + img_coord * zoom_new        # where that pixel lands at zoom_new
scroll_new = canvas_new - pointer                  # canvas coord to place at widget x=0
fraction   = clamp(scroll_new / region_new, 0.0, 1.0) if region_new else 0.0
```

When `disp_new <= canvas` (image smaller than the viewport) `region_new == canvas`, there is no
scroll room, and the fraction collapses to the centered position — the desired degradation.

`CanvasView.compute_zoom_fractions(pointer_xy, working_size, zoom_old, zoom_new) -> (fx, fy)`
reads the live canvas sizes and `canvasx`/`canvasy` and calls the helper once per axis. It must
be called **before** the zoom changes / the bitmap is re-rendered, since it depends on the
current scroll position.

## Pan implementation (`CanvasView`)

Tk's `scan_mark` / `scan_dragto` is the idiomatic canvas drag-pan and respects `scrollregion`:

- `_on_pan_start(event)`: `self.canvas.config(cursor="fleur")`,
  `self.canvas.scan_mark(event.x, event.y)`, `self._panning = True`. Does **not** clear the
  selection.
- `_on_pan_motion(event)`: if `_panning`, `self.canvas.scan_dragto(event.x, event.y, gain=1)`
  (default gain 10 is too fast).
- `_on_pan_end(event)`: `self._panning = False`, restore `cursor="crosshair"`.
- **Shift-released-mid-drag guard:** if Shift is released before the button, the plain
  `<ButtonRelease-1>` / `<B1-Motion>` fire instead. They already early-return when
  `_rb_start is None` (it is — the plain press handler never ran), so no stray selection is
  created; the plain release handler additionally resets the pan cursor / `_panning` flag if a
  pan was in progress.

When the image fits entirely in the viewport there is no scroll room, so panning is a no-op —
matching modern viewers.

## Rendering-path changes

- `CanvasView.display(pil_image, recenter: bool = True)` — add a `recenter` flag. When `False`
  it skips `_center_view()` even though the bitmap size changed. Existing callers
  (`refresh_display`, `_update_display`, load) keep the default `True` and are unchanged.
- `PxvApp._on_wheel_zoom(event, direction)` — new orchestration, wired into `CanvasView` via an
  `on_wheel_zoom` callback (the same injection pattern as `on_right_click`). Sequence:
  1. guard: no image / `(0,0)` working size → return `"break"`.
  2. `zoom_old = canvas_view.zoom`; `zoom_new = clamp(zoom_old * factor)` where
     `factor = WHEEL_ZOOM_FACTOR` for zoom-in, `1 / WHEEL_ZOOM_FACTOR` for zoom-out, using the
     existing `[0.01, 64.0]` clamp. If `zoom_new == zoom_old`, return `"break"`.
  3. `fx, fy = canvas_view.compute_zoom_fractions((event.x, event.y), working_size, zoom_old, zoom_new)`
     (captures the *old* scroll state).
  4. set `canvas_view.zoom = zoom_new`.
  5. `img = image_model.get_display_image(zoom_new, params, bg)`.
  6. `canvas_view.display(img, recenter=False)` (sets the new scrollregion + positions the
     image, no re-center).
  7. `canvas_view.apply_view_fraction(fx, fy)` (`xview_moveto` / `yview_moveto`).
  8. `app._update_title()` (the title shows the zoom %).
  9. return `"break"`.
- `CanvasView.apply_view_fraction(fx, fy)` — thin wrapper over `xview_moveto` / `yview_moveto`.
- `CanvasView._on_mouse_wheel` → renamed/refocused to parse wheel direction
  (`Button-4`/`delta>0` = in, `Button-5`/`delta<0` = out) and invoke the `on_wheel_zoom`
  callback, returning `"break"`.
- **`WHEEL_ZOOM_FACTOR = 1.25`** per notch (snappier than the keyboard's 1.1; a single tunable
  constant).

## Performance — simple first, throttling deferred

Each notch re-runs `get_display_image` (a full Pillow resize + the enhancement pipeline) — the
*same* work the keyboard zoom already does per keypress and which performs acceptably. Fast
wheels and trackpads can burst events, so a very large photo could lag. Decision: **ship the
straightforward per-notch re-render** (reuses the proven path, stays maintainable per "boring
over clever") and add `after()`-coalescing/throttling only if it proves janky in practice. This
is recorded as a deferred optimization, not built now.

## Tests

Pure unit tests (no Tk) for `zoom_view_fraction`, alongside `test_canvas_geometry.py`:

- Cursor at the viewport center → center stays centered after zoom in/out.
- Cursor off-center → the image pixel under the cursor stays anchored (fraction places it back
  under the pointer).
- Zoom-out below the viewport → fraction clamps to the centered position.
- `region == canvas` edge (image exactly fills viewport).

Optionally, a couple of Xvfb-gated handler tests (per the project's display-gated Tk test setup)
exercising the wheel and pan bindings end to end.

## Documentation to update

- `dialogs.py` help dialog — add a **Mouse** section: wheel = zoom to cursor; `Shift`+drag =
  pan; left-drag = select region; right-click = menu.
- `README.md` — add the mouse controls to the controls table.
- `canvas_view.py` module docstring + `AIDEV-NOTE` anchors — currently describe wheel-*pan*;
  update to wheel-*zoom* + `Shift`-drag pan.

## Out of scope (YAGNI)

- Keyboard zoom behavior (unchanged).
- Middle-drag panning (Button-2 conflict).
- Trackpad pinch-zoom (no native gesture events under X11 Tk). Trackpad two-finger scroll emits
  wheel events and will therefore zoom — a known, accepted minor caveat.
- Wheel-event throttling (deferred; see Performance).
