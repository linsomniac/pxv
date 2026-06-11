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
from dataclasses import replace
from tkinter import colorchooser, messagebox, ttk
from typing import TYPE_CHECKING, Any, Literal, Union, cast

from pxv.annotation_render import render_overlay
from pxv.annotations import AnnotationLayer, Shape, Tool, hit_tolerance, size_presets

if TYPE_CHECKING:
    from PIL import Image

    from pxv.app import PxvApp

# The palette's active tool: any drawing Tool, or the non-drawing Select tool.
# Shape.tool stays the narrower Tool — "select" never reaches a Shape.
# typing.Union (not the | operator): this alias is evaluated at runtime.
PaletteTool = Union[Tool, Literal["select"]]

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

_PREVIEW_KINDS: dict[Tool, Literal["polyline", "line", "arrow", "rect", "ellipse"]] = {
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
        # (layer.revision, display_size, scale) -> rendered RGBA display overlay.
        self._overlay_cache: tuple[tuple[int, tuple[int, int], float], Image.Image] | None = None
        # Capture the dirty flag at open — a confirmed Cancel only discards THIS
        # session's shapes; baked-but-unsaved work from earlier sessions is
        # preserved.
        self._dirty_at_open: bool = app.annotations_unsaved
        # Exactly-once funnel latch: askyesno spins a local event loop during which
        # cancel_stale could tear down the palette mid-prompt; the latch prevents
        # _end_session from running twice.
        self._ended: bool = False

        # Styling state for NEW shapes; with a live selection the controls
        # also restyle it (see _restyle_selection).
        self._presets = size_presets(max(app.image_model.get_working_size()))
        self.tool: PaletteTool = "freehand"
        self.color: str = SWATCHES[0]
        self.width_px: float = self._presets.widths[1]  # medium

        # In-flight drag: accumulated image-space points, or None.
        self._drag_points: list[tuple[float, float]] | None = None
        # Escape latch: swallow motion/release until the physical ButtonRelease.
        self._cancel_latch = False
        # In-flight Select-tool move: (press_xy, shape AS PRESSED), plus
        # whether the 3-screen-px gate opened (a click with jitter ≠ a move).
        self._select_drag: tuple[tuple[float, float], Shape] | None = None
        self._select_moved = False

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
            ("1", "Select", True),
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
                command=lambda c=swatch: self.set_color(c),  # type: ignore[misc]
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

    def _restyle_selection(self, **changes: Any) -> None:
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

    # --- session protocol (called by CanvasView and the app) ----------------

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
        # AIDEV-NOTE: Re-anchor to the current image if the session is empty and
        # the image was swapped since open — drawing on the new image is safe
        # because nothing was drawn on the old one, and this prevents the first
        # shape from being instantly discarded by cancel_stale.
        if not self.layer.shapes and not self.image_is_current():
            self._session_image = self.app.image_model.working_image
        self._drag_points = [image_xy]

    def on_drag(self, image_xy: tuple[float, float]) -> None:
        if self._cancel_latch:
            return
        if self.tool == "select":
            self._select_drag_to(image_xy)
            return
        if self._drag_points is None:
            return
        # self.tool is narrowed to Tool here (the "select" branch returned above)
        if self.tool == "freehand":
            self._drag_points.append(image_xy)
        else:
            self._drag_points = [self._drag_points[0], image_xy]
        self.app.canvas_view.set_preview_shape(
            _PREVIEW_KINDS[self.tool],
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
        # self.tool is narrowed to Tool here (the "select" branch returned above)
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

    def render_display_overlay(self, target_size: tuple[int, int], scale: float) -> Image.Image:
        """The committed shapes rendered as an RGBA overlay at display size.

        AIDEV-NOTE: Cache key is (layer.revision, target_size, scale) — revision
        bumps on every shape mutation. Only the OVERLAY is cached: the base
        display image changes under the same key (enhancement debounce,
        Compare, background toggle), so the app composites onto a fresh base
        every refresh (2026-06-10 design).
        """
        key = (self.layer.revision, target_size, scale)
        if self._overlay_cache is None or self._overlay_cache[0] != key:
            self._overlay_cache = (key, render_overlay(self.layer.shapes, target_size, scale))
        return self._overlay_cache[1]

    # --- in-mode keys --------------------------------------------------------

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

    def on_delete_key(self) -> None:
        """Delete the selected shape (Delete, or BackSpace with a selection)."""
        if self.layer.selected is None:
            return
        self.layer.delete_selected()
        self._refresh_selection_marker()
        self.app.refresh_display()

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

    # --- session end -----------------------------------------------------

    def image_is_current(self) -> bool:
        """Stale-image guard predicate (see _session_image)."""
        return self.app.image_model.working_image is self._session_image

    def cancel_stale(self) -> None:
        """Guard trip from the composite hook: discard the session, no prompt.

        AIDEV-NOTE: show_temp_title is called BEFORE _end_session (which
        calls refresh_display -> _update_title). _update_title skips its
        root.title() call while _status_after_id is set, so the stale
        message survives the trailing _update_title in the outer display
        path (2026-06-10 design). Without this ordering the outer
        _update_title would overwrite the stale message.
        """
        self.app.show_temp_title(_STALE_MESSAGE)
        self._end_session(bake=False)

    def _on_done(self) -> None:
        self._end_session(bake=True)

    def _on_cancel(self) -> None:
        if self.layer.shapes:
            if not messagebox.askyesno("pxv", "Discard annotations?", parent=self):
                return
            # A confirmed discard only covers THIS session's shapes — restore the
            # dirty flag to what it was when the palette opened (baked-but-unsaved
            # work from earlier sessions is NOT discarded by this Cancel).
            self.app.annotations_unsaved = self._dirty_at_open
        self._end_session(bake=False)

    def _end_session(self, bake: bool) -> None:
        """The ONE teardown path — every way out of draw mode goes through here.

        Disarms the canvas FIRST (the eyedropper _on_close pattern) so no
        event can reach a dying session, then destroys the window, keeping the
        palette-open <=> mode-active invariant.
        """
        # AIDEV-NOTE: Exactly-once latch — askyesno in _on_cancel spins a local
        # Tk event loop during which cancel_stale could call _end_session again.
        if self._ended:
            return
        self._ended = True
        self.app.canvas_view.set_annotation_session(None)
        shapes = self.layer.shapes
        stale = bake and bool(shapes) and not self.image_is_current()
        if stale:
            # Stale-image guard at bake start: never bake against the wrong image.
            bake = False
            # AIDEV-NOTE: show_temp_title BEFORE refresh_display so _status_after_id
            # is set when _update_title runs inside refresh_display; _update_title
            # skips its root.title() call while a temp title is in flight, keeping
            # the stale message visible (2026-06-10 design).
            self.app.show_temp_title(_STALE_MESSAGE)
        self.app.annotation_palette = None
        self.destroy()
        self.app.restore_main_focus()
        if bake and shapes:
            self.app.bake_annotations(shapes)  # refreshes the display itself
        else:
            # Drop the composited overlay (and any preview) from the screen.
            self.app.refresh_display()
