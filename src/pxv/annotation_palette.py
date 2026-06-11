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
