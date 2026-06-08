# Visual Schnauzer (Thumbnail Browser) — Design

**Date:** 2026-06-07
**Ideas:** Ideas.md #2 (Thumbnail browser — the "Visual Schnauzer", L)

## Background

Navigation today is **blind**: the only cue to where you are in the file list is the
title bar's `[3/10]` (`app.py:_update_title`). `FileList` (`file_list.py`) holds an ordered
list of `Path`s with `next()`/`prev()`/`current()` and an `index` property; `PxvApp.load_current()`
loads `file_list.current()` into the single-image `ImageModel` and redraws the one `CanvasView`
that fills the root window.

This adds xv's signature feature: a standalone window showing a scrollable grid of cached
thumbnails so you can **see** every image in the list and **jump** to any of them.

## Decisions (from brainstorming)

- **Form: a separate `Toplevel` grid window** (not a docked filmstrip). The main window
  auto-resizes to fit every image on navigation (`_resize_window_to_image`), which fights a
  strip docked into that same window — it would jolt and reflow on every Space/arrow. A
  separate window also matches xv's real Visual Schnauzer and reuses pxv's existing non-modal
  `Toplevel` pattern (`InfoDialog`, `EnhancementDialog`).
- **Scope: navigate-only for v1.** See thumbnails; click/arrow to jump the viewer. No
  editing, delete, multi-select, or batch ops from the grid (those are a later "grid manager"
  iteration, overlapping the separate in-viewer file-management idea).
- **Interaction: live — pick = load.** Single-click / arrow-keys / Enter / double-click all
  load the picked image into the viewer immediately (same cost as pressing Space). The grid
  highlight and the viewer stay in sync **both** directions; the grid scrolls to keep the
  current tile visible. `Esc` or the toggle key closes the window.
- **Tile: medium 128 px, with filename.** Each tile is a square 128×128 cell holding the
  thumbnail (aspect-preserved, centered/letterboxed) with the filename beneath it. Columns
  reflow to the window width.
- **Fixed size for v1.** Ship one default tile size; leave a clean hook (the single
  `THUMBNAIL_SIZE` constant) to add runtime S/M/L switching later. No size keys in v1.
- **Loading: incremental on the main thread.** Tk's `PhotoImage` must be built on the main
  thread, so thumbnails are decoded in small batches via a self-rescheduling `root.after()`
  loop. Tiles show a placeholder until their thumbnail swaps in. Decoded thumbnails are cached
  per resolved path for the session. v1 decodes **all** files in list order; visible-first /
  virtualized generation is a noted future upgrade for very large folders.
- **Toggle key: `b`** (mnemonic *browse*), currently unbound, plus a context-menu entry and a
  help-dialog line.

## Components

### `thumbnails.py` (new, pure — no Tk)

I/O and pixel math only; unit-testable with temp image files, no display.

```python
THUMBNAIL_SIZE = 128          # default tile size; the single tuning knob for v1
CELL_BG = (30, 30, 30)        # dark neutral for the cell, letterbox, and transparency
                              # flatten; the single place to theme thumbnails later

def fit_thumbnail(img: Image.Image, size: int) -> Image.Image:
    """Return a copy scaled to fit within size×size, aspect ratio preserved."""

def pad_to_square(img: Image.Image, size: int, bg: tuple[int, int, int] = CELL_BG) -> Image.Image:
    """Center a (already-fit) image on a size×size bg cell, so every tile is uniform."""

def load_thumbnail(
    path: Path, size: int, bg: tuple[int, int, int] = CELL_BG
) -> Image.Image:
    """Open path, apply EXIF orientation, flatten transparency onto bg, fit + pad to square.

    Raises on an unreadable / non-image file — the caller maps that to a 'broken' tile.
    """

def columns_for_width(width: int, cell: int, gap: int, pad: int) -> int:
    """How many tile columns fit in a viewport of the given width (>= 1)."""

class ThumbnailCache:
    """Maps resolved Path -> decoded PIL thumbnail. Survives browser open/close."""
    def __contains__(self, path: Path) -> bool: ...
    def get(self, path: Path) -> Image.Image | None: ...
    def put(self, path: Path, img: Image.Image) -> None: ...
    def clear(self) -> None: ...
```

`load_thumbnail` reuses the viewer's transparency rule (composite onto the cell background
so thumbnails match how the image displays) and `ImageOps.exif_transpose` so orientation
matches the viewer. The cache stores **PIL** images (not `PhotoImage`): tile widgets hold the
`PhotoImage` refs while open; reopening rewraps from cache with no disk I/O.

### `thumbnail_browser.py` (new) — `BrowserWindow(tk.Toplevel)`

Modeled on `InfoDialog`: held as `app.browser`, transient, positioned beside the main window;
`_on_close` nulls the ref and calls `restore_main_focus()` (the focus dance documented in
`PxvApp.restore_main_focus`).

Layout is the standard Tk scrollable-frame: a `tk.Canvas` + vertical `ttk.Scrollbar`, with an
inner `ttk.Frame` (`create_window`) holding the tiles in a `grid()`. Each **tile** is a
classic `tk.Frame` (not `ttk` — the selection border uses `highlightthickness=3`, a classic-Tk
option: `highlightcolor`/`highlightbackground` = yellow when current, `CELL_BG` otherwise)
containing an image `Label` and a filename `Label`; clicks on the tile or its children
activate it.

State & methods:

```python
self._tiles: list[Tile]          # parallel to file_list, each knows its index + widgets
self._columns: int               # current column count (for Up/Down arrow math)
self._selected: int              # highlighted index
self._load_queue: list[int]      # indices awaiting thumbnail decode
self._loader_after_id: str | None
self._configure_after_id: str | None

def sync_selection(self, index: int) -> None:
    """Highlight `index` and scroll it into view. Does NOT load (main->grid direction)."""

def _activate(self, index: int) -> None:
    """User picked a tile: delegate to commands.cmd_show_index; the resulting
       load_current() calls back into sync_selection (grid<-viewer)."""

def rebuild(self) -> None:
    """Tear down + rebuild tiles from the current file_list (used after cmd_open adds files,
       and on first open). Cheap re-decode thanks to ThumbnailCache."""

def _pump_loader(self) -> None:
    """Decode a small batch (e.g. 3) of queued thumbnails via the cache, swap each onto its
       tile, reschedule via after() until the queue drains. Cancelled on close."""
```

Own key bindings on the Toplevel (root's bindings don't reach a separate window): `<Left>`
`<Right>` `<Up>`/`<Down>` move the selection (±1, ±`_columns`, clamped) and `_activate` it
live; `<Return>` activates the current tile; `<Escape>`, `<Key-b>`, and `<Key-q>` close.
Mouse-wheel scrolls the canvas. A debounced `<Configure>` handler recomputes
`columns_for_width` and re-grids only when the column count changes. Empty file list → a
centered "No images" label instead of a grid. The window takes keyboard focus on open so
arrows work immediately.

Activation/sync avoids recursion by splitting responsibilities: `_activate` only calls
`cmd_show_index`; the load path calls `sync_selection`, which never loads.

### `app.py` — changes

- `__init__`: `self.browser: BrowserWindow | None = None` and
  `self.thumbnail_cache = ThumbnailCache()` (cache lives on the app so it persists across
  browser toggles and navigation).
- `_bind_keys`: `self.root.bind("<Key-b>", lambda _: commands.cmd_toggle_browser(self))`.
- `load_current()`: on the success path (after `refresh_display()`), add
  `if self.browser is not None: self.browser.sync_selection(self.file_list.index)`. This is
  the viewer→grid sync covering every load path (Space/arrows, jumps, Open).

### `commands.py` — new commands

```python
def cmd_toggle_browser(app: PxvApp) -> None:
    """Open the Visual Schnauzer, or close it if already open."""
    if app.browser is not None:
        app.browser._on_close()
        return
    from pxv.thumbnail_browser import BrowserWindow
    app.browser = BrowserWindow(app)

def cmd_show_index(app: PxvApp, index: int) -> None:
    """Jump the viewer to file-list position `index` (no-op if out of range)."""
    if not (0 <= index < app.file_list.count()):
        return
    prev = app.file_list.index
    app.file_list.index = index
    if not app.load_current():           # rolls back like cmd_next_image on a failed load
        app.file_list.index = prev
        if app.browser is not None:
            app.browser.sync_selection(app.file_list.index)  # re-sync highlight after rollback
```

`cmd_open` gains one line: after a successful add/load, if `app.browser is not None`, call
`app.browser.rebuild()` so a newly opened file appears in the grid.

### `context_menu.py` — change

Add a `"Browse thumbnails…"` command bound to `commands.cmd_toggle_browser`.

### `dialogs.py` `KEYBINDINGS` — change

Add `("b", "Browse thumbnails (Visual Schnauzer)")`.

### `README.md` — change

Add the `b` row to the Keyboard Shortcuts table.

`FileList` is unchanged — `cmd_show_index` sets a valid `index` through the existing setter.

## Edge cases

- **Empty file list:** the window shows "No images"; `b` still toggles it.
- **Broken / unreadable file:** `load_thumbnail` raises; the loader catches it, paints a
  "broken" placeholder tile, and continues to the next item (one bad file never stalls the grid).
- **Non-square / portrait / landscape images:** letterboxed, centered in the square cell.
- **EXIF orientation:** thumbnails honor `exif_transpose`, matching the viewer.
- **File added via Open while open:** `rebuild()` re-syncs tiles; the cache keeps it cheap.
- **Jump whose full-res load fails:** `cmd_show_index` rolls the index back (as
  `cmd_next_image` does) and re-syncs the highlight to the still-current image.
- **Close / focus:** `_on_close` cancels the loader `after`, nulls `app.browser`, destroys,
  then `restore_main_focus()` (focus reclaim must follow `destroy()` — see the existing note).
- **Large folders:** all thumbnails are decoded incrementally and held in memory
  (~48 KB each → ~240 MB at 5k images). Acceptable for typical folders; visible-first /
  virtualized rendering is the future upgrade (see Out of scope).

## Testing

Mirrors the suite's split: pure logic is display-free; Tk wiring is `DISPLAY`-gated (Xvfb).

- **`tests/test_thumbnails.py`** (new, pure): `fit_thumbnail` keeps aspect and stays within
  bounds for portrait/landscape/square inputs; `pad_to_square` yields exact size×size with the
  image centered; `columns_for_width` math across widths (and never < 1); `load_thumbnail`
  honors an EXIF-orientation tag and flattens transparency, and raises on a non-image file;
  `ThumbnailCache` get/put/contains/clear.
- **DISPLAY-gated browser test** (new, pattern from `test_dialog_focus.py`): opening builds a
  tile per file; clicking tile *i* sets `file_list.index == i` and loads it; arrow navigation
  moves the selection and index; a main-window `cmd_next_image` updates the grid highlight via
  `sync_selection`; `cmd_toggle_browser` opens then closes; close nulls `app.browser` and
  restores canvas focus; an empty file list renders the "No images" state.

## Out of scope

- Editing from the grid: delete, rename, rotate, multi-select, batch ops (later "grid manager").
- Runtime S/M/L tile-size switching (the `THUMBNAIL_SIZE` hook is left in place).
- A persistent on-disk thumbnail cache and LRU/size-bounded eviction.
- Visible-first / virtualized rendering and canvas-drawn (non-widget) tiles for very large
  folders.
- Sorting / reordering controls; following directory changes on disk.
