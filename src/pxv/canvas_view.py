"""Image display canvas with rubber-band selection, zoom, and pan.

AIDEV-NOTE: The image is centered within the canvas scrollregion. When a zoomed
image is larger than the viewport it can be panned with the scroll wheel
(Shift+wheel pans horizontally). Rubber-band coordinates are taken in canvas space
(via canvasx/canvasy, so they stay correct while scrolled) and converted to image
space for crop operations, accounting for the centering offset and zoom factor.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import TYPE_CHECKING

from PIL import ImageTk

if TYPE_CHECKING:
    from PIL import Image


def selection_to_image_box(
    selection: tuple[int, int, int, int],
    working_size: tuple[int, int],
    display_size: tuple[int, int],
    canvas_size: tuple[int, int],
    zoom: float,
) -> tuple[int, int, int, int] | None:
    """Convert a canvas-space selection rectangle to working-image pixel coords.

    AIDEV-NOTE: Pure geometry extracted from CanvasView.get_selection_image_coords
    so it can be unit-tested without a live Tk display. The image is centered in
    the canvas; we subtract that centering offset, divide by zoom, and clamp to the
    image bounds. Returns None for a degenerate (zero/negative-area) box.
    """
    sx1, sy1, sx2, sy2 = selection
    img_w, img_h = working_size
    disp_w, disp_h = display_size
    canvas_w, canvas_h = canvas_size

    area_w = max(canvas_w, disp_w)
    area_h = max(canvas_h, disp_h)
    img_x0 = (area_w - disp_w) / 2
    img_y0 = (area_h - disp_h) / 2

    ix1 = max(0, min(img_w, int((sx1 - img_x0) / zoom)))
    iy1 = max(0, min(img_h, int((sy1 - img_y0) / zoom)))
    ix2 = max(0, min(img_w, int((sx2 - img_x0) / zoom)))
    iy2 = max(0, min(img_h, int((sy2 - img_y0) / zoom)))

    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return (ix1, iy1, ix2, iy2)


def canvas_point_to_image_xy(
    point: tuple[int, int],
    working_size: tuple[int, int],
    display_size: tuple[int, int],
    canvas_size: tuple[int, int],
    zoom: float,
) -> tuple[int, int] | None:
    """Map one canvas-space point to working-image pixel coords, or None if outside.

    AIDEV-NOTE: Single-point analog of selection_to_image_box — same centering
    offset and zoom math, kept pure for headless testing.
    """
    x, y = point
    img_w, img_h = working_size
    disp_w, disp_h = display_size
    canvas_w, canvas_h = canvas_size
    area_w = max(canvas_w, disp_w)
    area_h = max(canvas_h, disp_h)
    ix = int((x - (area_w - disp_w) / 2) / zoom)
    iy = int((y - (area_h - disp_h) / 2) / zoom)
    if ix < 0 or iy < 0 or ix >= img_w or iy >= img_h:
        return None
    return (ix, iy)


def canvas_point_to_image_xy_f(
    point: tuple[float, float],
    display_size: tuple[int, int],
    canvas_size: tuple[int, int],
    zoom: float,
) -> tuple[float, float]:
    """Map a canvas-space point to UNCLAMPED float image coords (no None case).

    AIDEV-NOTE: The annotation session's converter (2026-06-10 design) — same
    centering/zoom math as canvas_point_to_image_xy, but float precision, no
    truncation, and out-of-image points pass through unclamped (clipping
    happens at render time), so it needs no working_size parameter.
    """
    x, y = point
    disp_w, disp_h = display_size
    canvas_w, canvas_h = canvas_size
    area_w = max(canvas_w, disp_w)
    area_h = max(canvas_h, disp_h)
    return ((x - (area_w - disp_w) / 2) / zoom, (y - (area_h - disp_h) / 2) / zoom)


def image_xy_to_canvas_point(
    xy: tuple[float, float],
    display_size: tuple[int, int],
    canvas_size: tuple[int, int],
    zoom: float,
) -> tuple[float, float]:
    """Inverse of canvas_point_to_image_xy_f: image coords -> canvas coords.

    Used to (re-)derive transient Tk items (drag preview, selection marker)
    from image-space truth after any zoom/pan/resize.
    """
    ix, iy = xy
    disp_w, disp_h = display_size
    canvas_w, canvas_h = canvas_size
    area_w = max(canvas_w, disp_w)
    area_h = max(canvas_h, disp_h)
    return (ix * zoom + (area_w - disp_w) / 2, iy * zoom + (area_h - disp_h) / 2)


class CanvasView:
    """Canvas widget that displays an image with rubber-band selection and zoom."""

    def __init__(self, root: tk.Tk, on_right_click: object = None) -> None:
        self.root = root
        self.canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # AIDEV-NOTE: _photo_image MUST be kept as an instance var.
        # Tkinter garbage-collects PhotoImage if no Python reference exists,
        # even while the canvas displays it.
        self._photo_image: ImageTk.PhotoImage | None = None
        self._image_id: int | None = None

        # Display dimensions of the currently shown image
        self._display_width: int = 0
        self._display_height: int = 0

        # Rubber-band selection state
        self._rubber_band_id: int | None = None
        self._rb_start: tuple[int, int] | None = None
        self._selection: tuple[int, int, int, int] | None = None  # canvas coords (x1,y1,x2,y2)

        # Zoom
        self.zoom: float = 1.0

        # Debounce for configure events
        self._configure_after_id: str | None = None
        self._on_right_click = on_right_click

        # One-shot eyedropper pick mode (None = normal rubber-band behavior).
        self._pick_callback: Callable[[tuple[int, int] | None], None] | None = None
        self._pick_working_size: tuple[int, int] | None = None

        self._bind_mouse()

    def _bind_mouse(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Right-click: Button-3 on Linux/Windows, Button-2 on macOS
        self.canvas.bind("<Button-3>", self._on_right_click_event)
        self.canvas.bind("<Button-2>", self._on_right_click_event)
        # Scroll-wheel panning (no-op unless the image exceeds the viewport).
        # Windows/macOS deliver <MouseWheel>; X11 delivers Button-4/5. Shift pans
        # horizontally. Bound to the root so the wheel works regardless of pointer.
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)
        self.canvas.bind("<Shift-Button-4>", self._on_mouse_wheel)
        self.canvas.bind("<Shift-Button-5>", self._on_mouse_wheel)

    def display(self, pil_image: Image.Image) -> None:
        """Display a PIL image centered on the canvas."""
        size_changed = (pil_image.width, pil_image.height) != (
            self._display_width,
            self._display_height,
        )
        self._display_width = pil_image.width
        self._display_height = pil_image.height
        self._photo_image = ImageTk.PhotoImage(pil_image)

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        cx = max(canvas_w, self._display_width) // 2
        cy = max(canvas_h, self._display_height) // 2

        if self._image_id is not None:
            self.canvas.coords(self._image_id, cx, cy)
            self.canvas.itemconfig(self._image_id, image=self._photo_image)
        else:
            self._image_id = self.canvas.create_image(
                cx, cy, image=self._photo_image, anchor=tk.CENTER
            )

        # Set scroll region to encompass the image
        self.canvas.config(
            scrollregion=(
                0,
                0,
                max(canvas_w, self._display_width),
                max(canvas_h, self._display_height),
            )
        )

        # AIDEV-NOTE: Only re-center the viewport when the displayed size changes
        # (load/navigate/zoom), so an oversized image starts centered rather than
        # showing a clipped corner — but a same-size redraw (slider preview, resize)
        # preserves the user's current pan position.
        if size_changed:
            self._center_view()

    def _center_view(self) -> None:
        """Center the viewport on the image (only matters when image > canvas)."""
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        region_w = max(canvas_w, self._display_width)
        region_h = max(canvas_h, self._display_height)
        self.canvas.xview_moveto((region_w - canvas_w) / 2 / region_w if region_w else 0.0)
        self.canvas.yview_moveto((region_h - canvas_h) / 2 / region_h if region_h else 0.0)

    def clear_selection(self) -> None:
        """Remove the rubber-band rectangle and clear selection."""
        if self._rubber_band_id is not None:
            self.canvas.delete(self._rubber_band_id)
            self._rubber_band_id = None
        self._selection = None
        self._rb_start = None

    def has_selection(self) -> bool:
        return self._selection is not None

    def get_selection_image_coords(
        self, working_size: tuple[int, int]
    ) -> tuple[int, int, int, int] | None:
        """Convert the canvas selection rectangle to working_image pixel coordinates.

        AIDEV-NOTE: Reads live widget sizes here and delegates the pure geometry to
        selection_to_image_box() (module level) so the math stays unit-testable.
        """
        if self._selection is None:
            return None
        return selection_to_image_box(
            self._selection,
            working_size,
            (self._display_width, self._display_height),
            (self.canvas.winfo_width(), self.canvas.winfo_height()),
            self.zoom,
        )

    def set_pick_callback(
        self,
        callback: Callable[[tuple[int, int] | None], None] | None,
        working_size: tuple[int, int] | None,
    ) -> None:
        """Arm (or disarm with None) a one-shot pick: the next click is consumed
        and the callback receives working-image coords, or None for a miss."""
        self._pick_callback = callback
        self._pick_working_size = working_size
        self.canvas.config(cursor="tcross" if callback is not None else "crosshair")

    def zoom_normal(self) -> None:
        self.zoom = 1.0

    def zoom_set(self, value: float) -> None:
        """Set zoom to an arbitrary value, clamped to [0.01, 64.0]."""
        self.zoom = max(0.01, min(64.0, value))

    def zoom_fit(self, image_size: tuple[int, int], canvas_size: tuple[int, int]) -> None:
        """Set zoom so the image fits within the given canvas size."""
        img_w, img_h = image_size
        max_w, max_h = canvas_size
        if img_w <= 0 or img_h <= 0:
            self.zoom = 1.0
            return
        scale_w = max_w / img_w
        scale_h = max_h / img_h
        self.zoom = min(scale_w, scale_h, 1.0)  # never upscale on initial fit

    def zoom_max(self, image_size: tuple[int, int], canvas_size: tuple[int, int]) -> None:
        """Set zoom so the image fills the display (may upscale)."""
        img_w, img_h = image_size
        max_w, max_h = canvas_size
        if img_w <= 0 or img_h <= 0:
            self.zoom = 1.0
            return
        scale_w = max_w / img_w
        scale_h = max_h / img_h
        self.zoom = min(scale_w, scale_h)

    # --- Mouse event handlers ---

    def _canvas_xy(self, event: tk.Event) -> tuple[int, int]:
        """Translate widget-relative event coords to canvas coords (scroll-aware)."""
        cx = self.canvas.canvasx(event.x)  # type: ignore[no-untyped-call]
        cy = self.canvas.canvasy(event.y)  # type: ignore[no-untyped-call]
        return (int(cx), int(cy))

    def _on_press(self, event: tk.Event) -> None:
        # AIDEV-NOTE: Take keyboard focus on click so the root-bound shortcuts are
        # re-armed if focus was somehow lost (defense in depth alongside
        # PxvApp.restore_main_focus). A real click means the main window is
        # gaining focus anyway, so cooperative focus_set suffices here.
        self.canvas.focus_set()
        # AIDEV-NOTE: Pick mode consumes this click entirely — no rubber band,
        # one shot, then auto-disarm (cursor restored) before delivering,
        # coords via _canvas_xy so picks stay correct on a scrolled view.
        if self._pick_callback is not None and self._pick_working_size is not None:
            callback = self._pick_callback
            coords = canvas_point_to_image_xy(
                self._canvas_xy(event),
                self._pick_working_size,
                (self._display_width, self._display_height),
                (self.canvas.winfo_width(), self.canvas.winfo_height()),
                self.zoom,
            )
            self.set_pick_callback(None, None)
            callback(coords)
            return
        self.clear_selection()
        self._rb_start = self._canvas_xy(event)

    def _on_drag(self, event: tk.Event) -> None:
        if self._rb_start is None:
            return
        x0, y0 = self._rb_start
        x1, y1 = self._canvas_xy(event)
        if self._rubber_band_id is None:
            self._rubber_band_id = self.canvas.create_rectangle(
                x0, y0, x1, y1, outline="yellow", dash=(6, 6), width=2
            )
        else:
            self.canvas.coords(self._rubber_band_id, x0, y0, x1, y1)

    def _on_release(self, event: tk.Event) -> None:
        if self._rb_start is None:
            return
        x0, y0 = self._rb_start
        x1, y1 = self._canvas_xy(event)
        self._rb_start = None

        # If selection is tiny (click without meaningful drag), clear it
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            self.clear_selection()
            return

        # Normalize: ensure x1 > x0, y1 > y0
        self._selection = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _on_mouse_wheel(self, event: tk.Event) -> str | None:
        """Pan the view with the scroll wheel (Shift = horizontal)."""
        num = getattr(event, "num", 0)
        if num == 4:  # X11 scroll up
            delta = -1
        elif num == 5:  # X11 scroll down
            delta = 1
        elif event.delta:  # Windows/macOS
            delta = -1 if event.delta > 0 else 1
        else:
            return None
        # event.state is an int bitmask for pointer events (typed int | str); 0x1 = Shift.
        shift_held = isinstance(event.state, int) and bool(event.state & 0x0001)
        if shift_held:  # Shift held -> horizontal pan
            self.canvas.xview_scroll(delta, "units")
        else:
            self.canvas.yview_scroll(delta, "units")
        return "break"

    def _on_right_click_event(self, event: tk.Event) -> None:
        if self._on_right_click is not None:
            self._on_right_click(event)  # type: ignore[operator]
