"""Image display canvas with rubber-band selection and zoom.

AIDEV-NOTE: The image is always centered on the canvas. Rubber-band coordinates
are in canvas space and must be converted to image space for crop operations.
The conversion accounts for the centering offset and current zoom factor.
"""

from __future__ import annotations

import bisect
import tkinter as tk
from typing import TYPE_CHECKING

from PIL import ImageTk

if TYPE_CHECKING:
    from PIL import Image

ZOOM_LEVELS = [0.10, 0.25, 0.33, 0.50, 0.75, 1.0, 1.50, 2.0, 3.0, 4.0, 8.0]


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

        self._bind_mouse()

    def _bind_mouse(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Right-click: Button-3 on Linux/Windows, Button-2 on macOS
        self.canvas.bind("<Button-3>", self._on_right_click_event)
        self.canvas.bind("<Button-2>", self._on_right_click_event)

    def display(self, pil_image: Image.Image) -> None:
        """Display a PIL image centered on the canvas."""
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
        """Convert canvas selection rectangle to working_image pixel coordinates.

        AIDEV-NOTE: The image is centered on the canvas. We must:
        1. Compute the image's top-left offset on the canvas
        2. Subtract that offset from selection coords
        3. Divide by zoom to get image-space coords
        4. Clamp to image bounds
        """
        if self._selection is None:
            return None

        sx1, sy1, sx2, sy2 = self._selection
        img_w, img_h = working_size

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        # Image top-left on canvas (centered)
        area_w = max(canvas_w, self._display_width)
        area_h = max(canvas_h, self._display_height)
        img_x0 = (area_w - self._display_width) / 2
        img_y0 = (area_h - self._display_height) / 2

        # Convert to image-relative coords and divide by zoom
        ix1 = (sx1 - img_x0) / self.zoom
        iy1 = (sy1 - img_y0) / self.zoom
        ix2 = (sx2 - img_x0) / self.zoom
        iy2 = (sy2 - img_y0) / self.zoom

        # Clamp to image bounds
        ix1 = max(0, min(img_w, int(ix1)))
        iy1 = max(0, min(img_h, int(iy1)))
        ix2 = max(0, min(img_w, int(ix2)))
        iy2 = max(0, min(img_h, int(iy2)))

        if ix2 <= ix1 or iy2 <= iy1:
            return None
        return (ix1, iy1, ix2, iy2)

    def zoom_in(self) -> None:
        idx = self._nearest_zoom_index()
        if idx < len(ZOOM_LEVELS) - 1:
            self.zoom = ZOOM_LEVELS[idx + 1]

    def zoom_out(self) -> None:
        idx = self._nearest_zoom_index()
        if idx > 0:
            self.zoom = ZOOM_LEVELS[idx - 1]

    def zoom_normal(self) -> None:
        self.zoom = 1.0

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

    def _nearest_zoom_index(self) -> int:
        """Find the index of the nearest zoom level to current zoom."""
        idx = bisect.bisect_left(ZOOM_LEVELS, self.zoom)
        if idx == 0:
            return 0
        if idx >= len(ZOOM_LEVELS):
            return len(ZOOM_LEVELS) - 1
        if abs(ZOOM_LEVELS[idx] - self.zoom) < abs(ZOOM_LEVELS[idx - 1] - self.zoom):
            return idx
        return idx - 1

    # --- Mouse event handlers ---

    def _on_press(self, event: tk.Event) -> None:
        self.clear_selection()
        self._rb_start = (event.x, event.y)

    def _on_drag(self, event: tk.Event) -> None:
        if self._rb_start is None:
            return
        x0, y0 = self._rb_start
        x1, y1 = event.x, event.y
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
        x1, y1 = event.x, event.y
        self._rb_start = None

        # If selection is tiny (click without meaningful drag), clear it
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            self.clear_selection()
            return

        # Normalize: ensure x1 > x0, y1 > y0
        self._selection = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _on_right_click_event(self, event: tk.Event) -> None:
        if self._on_right_click is not None:
            self._on_right_click(event)  # type: ignore[operator]
