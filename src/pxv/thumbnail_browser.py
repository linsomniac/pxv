"""The Visual Schnauzer: a Toplevel grid of thumbnails over the file list.

AIDEV-NOTE: A standalone non-modal window (modeled on info_dialog.InfoDialog) showing
one tile per FileList entry. Picking a tile (click / arrow+Enter) loads that image
into the viewer via commands.cmd_show_index; conversely every viewer load calls
sync_selection() so the grid highlight tracks the viewer. The two directions never
recurse: _activate only loads, load_current only highlights.

Tk constraint: PhotoImage must be built on the main thread, so thumbnails decode in
small batches via a self-rescheduling after() loop (_pump_loader). Decoded PIL images
live in app.thumbnail_cache so reopening is cheap.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

from pxv import commands, thumbnails
from pxv.thumbnails import CELL_BG, THUMBNAIL_SIZE

if TYPE_CHECKING:
    from pxv.app import PxvApp

# Tile/grid geometry. BORDER doubles as the selection-highlight thickness, so the
# tile footprint (TILE_W) used for column math includes it on both sides.
BORDER = 3
GAP = 10
PAD = 10
TILE_W = THUMBNAIL_SIZE + 2 * BORDER  # 134
_NAME_MAXLEN = 18
_NAME_FG = "#aab8d0"
_SELECT_FG = "yellow"


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _truncate(name: str, maxlen: int) -> str:
    return name if len(name) <= maxlen else name[: maxlen - 1] + "…"


class _Tile:
    """One grid cell: its file-list index, source path, and its widgets."""

    __slots__ = ("index", "path", "frame", "image_label", "name_label", "photo", "loaded")

    def __init__(
        self,
        index: int,
        path: Path,
        frame: tk.Frame,
        image_label: tk.Label,
        name_label: tk.Label,
    ) -> None:
        self.index = index
        self.path = path
        self.frame = frame
        self.image_label = image_label
        self.name_label = name_label
        self.photo: ImageTk.PhotoImage | None = None
        self.loaded = False


class BrowserWindow(tk.Toplevel):
    """Scrollable thumbnail grid that mirrors and drives the file-list cursor."""

    def __init__(self, app: PxvApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("pxv: Browse")
        self.transient(app.root)

        self._cell_hex = _hex(CELL_BG)
        self.configure(bg=self._cell_hex)

        self._tiles: list[_Tile] = []
        self._columns: int = 1
        self._selected: int | None = None
        self._load_queue: list[int] = []
        self._loader_after_id: str | None = None
        self._configure_after_id: str | None = None
        self._empty_label: tk.Label | None = None

        # Shared placeholder shown until a tile's real thumbnail decodes, so every
        # tile has its final footprint immediately and the grid never jumps.
        self._placeholder = ImageTk.PhotoImage(
            Image.new("RGB", (THUMBNAIL_SIZE, THUMBNAIL_SIZE), CELL_BG)
        )

        self._build_scaffold()
        self.rebuild()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_keys()

        self.geometry(self._initial_geometry())
        self.focus_force()

    # --- construction ----------------------------------------------------

    def _build_scaffold(self) -> None:
        """Build the canvas + scrollbar + inner frame that holds the tile grid."""
        self._canvas = tk.Canvas(self, bg=self._cell_hex, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self._canvas, bg=self._cell_hex)
        self._inner_id = self._canvas.create_window((0, 0), window=self._inner, anchor=tk.NW)
        self._inner.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    def _initial_geometry(self) -> str:
        """A 4-column default size, positioned just right of the main window."""
        width = 2 * PAD + 4 * TILE_W + 3 * GAP
        height = 640
        self.update_idletasks()
        px = self.app.root.winfo_x() + self.app.root.winfo_width() + 10
        py = self.app.root.winfo_y()
        return f"{width}x{height}+{px}+{py}"

    def _bind_keys(self) -> None:
        # Root bindings don't reach a separate Toplevel, so the grid owns its keys.
        self.bind("<Left>", lambda _e: self._nav(-1))
        self.bind("<Right>", lambda _e: self._nav(1))
        self.bind("<Up>", lambda _e: self._nav(-self._columns))
        self.bind("<Down>", lambda _e: self._nav(self._columns))
        self.bind("<Return>", lambda _e: self._activate_selected())
        self.bind("<Escape>", lambda _e: self._on_close())
        self.bind("<Key-b>", lambda _e: self._on_close())
        self.bind("<Key-q>", lambda _e: self._on_close())
        # Mouse-wheel / trackpad scrolling. Tk delivers <MouseWheel> to the widget under
        # the pointer but runs it up that widget's bindtags, which include this Toplevel
        # — so one binding here catches the wheel over the tiles, the canvas, and the
        # empty margins alike (verified on macOS/aqua Tk 8.6 with a binding probe).
        # <Button-4>/<Button-5> are the X11 equivalents.
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", self._on_wheel)
        self.bind("<Button-5>", self._on_wheel)
        # AIDEV-NOTE: Tk 8.7+/9.0 deliver TRACKPAD gestures as <TouchpadScroll>, not
        # <MouseWheel> — so on the Tk 9 that uv-managed Pythons bundle, the trackpad is
        # silent without this. Older Tk has no such event; guard the bind.
        try:
            self.bind("<TouchpadScroll>", self._on_touchpad_scroll)
        except tk.TclError:
            pass

    # --- (re)building the grid -------------------------------------------

    def rebuild(self) -> None:
        """Tear down and rebuild every tile from the current file list.

        Used on first open and after cmd_open adds a file. The ThumbnailCache keeps
        the re-decode cheap.
        """
        self._cancel_loader()
        # A pending _configure_after_id reflow is intentionally left: it re-guards on
        # winfo_exists()/_tiles and recomputes from scratch, so a late fire is harmless.
        for tile in self._tiles:
            tile.frame.destroy()
        self._tiles.clear()
        self._load_queue.clear()
        self._selected = None
        if self._empty_label is not None:
            self._empty_label.destroy()
            self._empty_label = None

        paths = self.app.file_list.paths()
        if not paths:
            self._empty_label = tk.Label(
                self._inner, text="No images", bg=self._cell_hex, fg=_NAME_FG, padx=40, pady=40
            )
            self._empty_label.grid(row=0, column=0)
            return

        for i, path in enumerate(paths):
            self._tiles.append(self._build_tile(i, path))
            self._load_queue.append(i)

        self._columns = 0  # force the first _reflow to lay tiles out
        self._reflow()
        self.sync_selection(self.app.file_list.index)
        self._kick_loader()

    def _build_tile(self, index: int, path: Path) -> _Tile:
        frame = tk.Frame(
            self._inner,
            bg=self._cell_hex,
            highlightthickness=BORDER,
            highlightbackground=self._cell_hex,
            highlightcolor=self._cell_hex,
        )
        image_label = tk.Label(frame, image=self._placeholder, bg=self._cell_hex, bd=0)
        image_label.pack()
        name_label = tk.Label(
            frame,
            text=_truncate(path.name, _NAME_MAXLEN),
            bg=self._cell_hex,
            fg=_NAME_FG,
            font=("TkDefaultFont", 8),
        )
        name_label.pack()

        def _on_click(_e: tk.Event, i: int = index) -> None:
            self._activate(i)

        for widget in (frame, image_label, name_label):
            widget.bind("<Button-1>", _on_click)
            widget.bind("<Double-Button-1>", _on_click)
        return _Tile(index, path, frame, image_label, name_label)

    # --- layout / reflow -------------------------------------------------

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # Keep the inner frame as wide as the canvas (so centering works), and
        # debounce a column recompute that only re-grids when the count changes.
        self._canvas.itemconfigure(self._inner_id, width=event.width)
        if self._configure_after_id is not None:
            self.after_cancel(self._configure_after_id)
        self._configure_after_id = self.after(80, self._reflow)

    def _reflow(self) -> None:
        self._configure_after_id = None
        if not self.winfo_exists() or not self._tiles:
            return
        width = self._canvas.winfo_width()
        columns = thumbnails.columns_for_width(width, TILE_W, GAP, PAD)
        if columns == self._columns:
            return
        self._columns = columns
        self._regrid()

    def _regrid(self) -> None:
        for tile in self._tiles:
            row, col = divmod(tile.index, self._columns)
            tile.frame.grid(row=row, column=col, padx=GAP // 2, pady=GAP // 2)
        if self._selected is not None:
            self._scroll_into_view(self._selected)

    # --- selection / activation ------------------------------------------

    def sync_selection(self, index: int) -> None:
        """Highlight `index` and scroll it into view. Never loads (viewer -> grid)."""
        if not self._tiles or not (0 <= index < len(self._tiles)):
            return
        if self._selected is not None and 0 <= self._selected < len(self._tiles):
            self._highlight(self._selected, on=False)
        self._selected = index
        self._highlight(index, on=True)
        self._scroll_into_view(index)

    def _highlight(self, index: int, *, on: bool) -> None:
        tile = self._tiles[index]
        color = _SELECT_FG if on else self._cell_hex
        tile.frame.configure(highlightbackground=color, highlightcolor=color)
        tile.name_label.configure(fg=_SELECT_FG if on else _NAME_FG)

    def _nav(self, delta: int) -> None:
        if not self._tiles:
            return
        current = self._selected if self._selected is not None else 0
        target = max(0, min(len(self._tiles) - 1, current + delta))
        self._activate(target)

    def _activate_selected(self) -> None:
        if self._selected is not None:
            self._activate(self._selected)

    def _activate(self, index: int) -> None:
        """Pick a tile: delegate to the viewer. load_current() calls sync_selection.

        focus_force keeps keyboard focus on the grid after a click so the arrow keys
        keep working; the load path never steals focus back.
        """
        self.focus_force()
        commands.cmd_show_index(self.app, index)

    def _scroll_into_view(self, index: int) -> None:
        self._canvas.update_idletasks()
        region = self._inner.winfo_height()
        if region <= 1:
            return
        tile = self._tiles[index]
        fy = tile.frame.winfo_y()
        fh = tile.frame.winfo_height()
        # canvasy is untyped in typeshed; float() pins the type for the comparisons below.
        top = float(self._canvas.canvasy(0))  # type: ignore[no-untyped-call]
        view_h = self._canvas.winfo_height()
        if fy < top:
            self._canvas.yview_moveto(fy / region)
        elif fy + fh > top + view_h:
            self._canvas.yview_moveto(max(0.0, (fy + fh - view_h) / region))

    # --- incremental thumbnail loading -----------------------------------

    def _kick_loader(self) -> None:
        if self._load_queue and self._loader_after_id is None:
            self._loader_after_id = self.after(1, self._pump_loader)

    def _pump_loader(self) -> None:
        self._loader_after_id = None
        if not self.winfo_exists():
            return
        batch = 3
        while self._load_queue and batch > 0:
            self._load_tile(self._load_queue.pop(0))
            batch -= 1
        if self._load_queue:
            self._loader_after_id = self.after(1, self._pump_loader)

    def _load_tile(self, index: int) -> None:
        tile = self._tiles[index]
        cached = self.app.thumbnail_cache.get(tile.path)
        if cached is None:
            try:
                cached = thumbnails.load_thumbnail(tile.path, THUMBNAIL_SIZE)
            except Exception:
                self._mark_broken(tile)
                return
            self.app.thumbnail_cache.put(tile.path, cached)
        photo = ImageTk.PhotoImage(cached)
        tile.photo = photo  # keep a ref or Tk garbage-collects the image
        tile.image_label.configure(image=photo, text="")
        tile.loaded = True

    def _mark_broken(self, tile: _Tile) -> None:
        tile.image_label.configure(
            image=self._placeholder, text="broken", compound=tk.CENTER, fg="#cc6666"
        )
        tile.loaded = True

    def _cancel_loader(self) -> None:
        if self._loader_after_id is not None:
            self.after_cancel(self._loader_after_id)
            self._loader_after_id = None

    # --- scrolling / teardown --------------------------------------------

    def _on_wheel(self, event: tk.Event) -> str | None:
        num = getattr(event, "num", 0)
        if num == 4:
            delta = -1
        elif num == 5:
            delta = 1
        elif getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1
        else:
            return None
        self._canvas.yview_scroll(delta, "units")
        return "break"

    def _on_touchpad_scroll(self, event: tk.Event) -> str:
        """Scroll for Tk 8.7+/9.0 trackpad <TouchpadScroll> events.

        Their packed delta is decoded by tk::PreciseScrollDeltas into (dx, dy) line
        counts. These fire ~60x/second, so act on every 5th event (matching Tk's own
        Listbox/Treeview bindings) to avoid flinging the grid.
        """
        if event.serial % 5 != 0:
            return "break"
        _dx, dy = self.tk.call("tk::PreciseScrollDeltas", event.delta)
        dy = int(dy)
        if dy:
            self._canvas.yview_scroll(-dy, "units")
        return "break"

    def _on_close(self) -> None:
        # AIDEV-NOTE: Cancel the pending loader/reflow timers, null the app ref, then
        # destroy and reclaim focus AFTER destroy() (see PxvApp.restore_main_focus —
        # destroying a Toplevel that holds input focus clears it).
        self._cancel_loader()
        if self._configure_after_id is not None:
            self.after_cancel(self._configure_after_id)
            self._configure_after_id = None
        self.app.browser = None
        self.destroy()
        self.app.restore_main_focus()
