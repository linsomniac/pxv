"""Main application: creates the Tk root, wires all components together.

AIDEV-NOTE: All keyboard bindings are on the root window so they work regardless
of which widget has focus. The enhancement dialog binds its own widget-level events.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tkinter as tk
from typing import TYPE_CHECKING

from pxv import commands
from pxv.canvas_view import CanvasView
from pxv.context_menu import ContextMenu
from pxv.enhancements import EnhancementParams
from pxv.file_list import FileList, expand_paths
from pxv.image_model import ImageModel

if TYPE_CHECKING:
    from pxv.enhancement_dialog import EnhancementDialog


# AIDEV-NOTE: Tkinter's winfo_screenwidth/height returns the total virtual desktop
# across all monitors. These helpers use xrandr to detect individual monitor
# geometry so windows don't span multiple displays.

_cached_monitors: list[tuple[int, int, int, int]] | None = None


def _parse_monitors() -> list[tuple[int, int, int, int]]:
    """Parse xrandr output to get connected monitor geometries.

    Returns list of (width, height, x_offset, y_offset) tuples.
    Result is cached for the process lifetime.
    """
    global _cached_monitors
    if _cached_monitors is not None:
        return _cached_monitors
    try:
        output = subprocess.check_output(
            ["xrandr"], text=True, timeout=5, stderr=subprocess.DEVNULL
        )
        pattern = r"\bconnected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)"
        _cached_monitors = [
            (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
            for m in re.finditer(pattern, output)
        ]
    except Exception:
        _cached_monitors = []
    return _cached_monitors


def _get_monitor_size(root: tk.Tk) -> tuple[int, int]:
    """Get pixel dimensions of the monitor containing the window's center.

    Falls back to winfo_screenwidth/height if xrandr is unavailable.
    """
    monitors = _parse_monitors()
    if monitors:
        root.update_idletasks()
        cx = root.winfo_x() + root.winfo_width() // 2
        cy = root.winfo_y() + root.winfo_height() // 2
        for mw, mh, mx, my in monitors:
            if mx <= cx < mx + mw and my <= cy < my + mh:
                return (mw, mh)
        # Window center not in any monitor — use first
        return (monitors[0][0], monitors[0][1])
    return (root.winfo_screenwidth(), root.winfo_screenheight())


class PxvApp:
    """Top-level application coordinator."""

    def __init__(self, root: tk.Tk, file_list: FileList) -> None:
        self.root = root
        self.file_list = file_list
        self.image_model = ImageModel()
        self.enhancement_params = EnhancementParams()

        # Will be set if the enhancement dialog is open
        self.enhancement_dialog: EnhancementDialog | None = None

        # Create canvas view (passes right-click handler)
        self.canvas_view = CanvasView(root, on_right_click=self._on_right_click)

        # Context menu
        self.context_menu = ContextMenu(root, self)

        # Debounce for configure events
        self._configure_after_id: str | None = None
        # AIDEV-NOTE: Guard flag to prevent <Configure> feedback loop when we
        # programmatically resize the window to match the image.
        self._resizing_programmatically = False
        self._deco_size: tuple[int, int] | None = None

        self._bind_keys()
        self._bind_configure()

    def _get_decoration_size(self) -> tuple[int, int]:
        """Measure window decoration overhead (borders + title bar).

        Caches the result after first successful measurement.
        Returns conservative defaults if the window isn't mapped yet.
        """
        if self._deco_size is not None:
            return self._deco_size
        self.root.update_idletasks()
        border = self.root.winfo_rootx() - self.root.winfo_x()
        titlebar = self.root.winfo_rooty() - self.root.winfo_y()
        if border > 0 or titlebar > 0:
            self._deco_size = (border * 2, titlebar + border)
            return self._deco_size
        # Conservative defaults for typical Linux WMs
        return (8, 48)

    def _get_max_image_size(self) -> tuple[int, int]:
        """Maximum image display size that fits on the current monitor."""
        mon_w, mon_h = _get_monitor_size(self.root)
        deco_w, deco_h = self._get_decoration_size()
        return (mon_w - deco_w, mon_h - deco_h)

    def _bind_keys(self) -> None:
        self.root.bind("<Key-q>", lambda _: commands.cmd_quit(self))
        self.root.bind("<Key-c>", lambda _: commands.cmd_crop(self))
        self.root.bind("<Key-u>", lambda _: commands.cmd_uncrop(self))
        self.root.bind("<Key-n>", lambda _: commands.cmd_zoom_normal(self))
        self.root.bind("<Key-e>", lambda _: commands.cmd_enhancement_dialog(self))
        self.root.bind("<Key-comma>", lambda _: commands.cmd_zoom_reduce(self))
        self.root.bind("<Key-period>", lambda _: commands.cmd_zoom_increase(self))
        self.root.bind("<greater>", lambda _: commands.cmd_zoom_double(self))
        self.root.bind("<less>", lambda _: commands.cmd_zoom_halve(self))
        self.root.bind("<Key-M>", lambda _: commands.cmd_zoom_max(self))
        self.root.bind("<Key-t>", lambda _: commands.cmd_rotate(self, 270))
        self.root.bind("<Key-T>", lambda _: commands.cmd_rotate(self, 90))
        self.root.bind("<Control-s>", lambda _: commands.cmd_save_as(self))
        self.root.bind("<space>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<Right>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<BackSpace>", lambda _: commands.cmd_prev_image(self))
        self.root.bind("<Left>", lambda _: commands.cmd_prev_image(self))
        self.root.bind("<Escape>", lambda _: self.canvas_view.clear_selection())

    def _bind_configure(self) -> None:
        """Debounced handler for window resize events."""
        self.canvas_view.canvas.bind("<Configure>", self._on_configure)

    def _on_configure(self, _event: tk.Event) -> None:
        if self._resizing_programmatically:
            return
        if self._configure_after_id is not None:
            self.root.after_cancel(self._configure_after_id)
        self._configure_after_id = self.root.after(50, self._handle_resize)

    def _handle_resize(self) -> None:
        self._configure_after_id = None
        if self.image_model.working_image is not None:
            self._update_display()

    def _on_right_click(self, event: tk.Event) -> None:
        self.context_menu.show(event)

    def load_current(self) -> None:
        """Load the current file from the file list."""
        path = self.file_list.current()
        if path is None:
            return
        try:
            self.image_model.load(path)
        except Exception as e:
            from tkinter import messagebox

            messagebox.showerror("Open Error", f"Could not open {path.name}:\n{e}")
            return

        self.enhancement_params.reset()
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.sync_sliders_from_params()
        self.canvas_view.clear_selection()

        # Fit to current monitor on load
        max_w, max_h = self._get_max_image_size()
        img_size = self.image_model.get_working_size()
        self.canvas_view.zoom_fit(img_size, (max_w, max_h))

        self.refresh_display()

    def refresh_display(self) -> None:
        """Re-render the image with current zoom and enhancement params."""
        display_img = self.image_model.get_display_image(
            zoom=self.canvas_view.zoom,
            params=self.enhancement_params,
        )
        if display_img is not None:
            # AIDEV-NOTE: Resize window BEFORE display() so the canvas has correct
            # dimensions when centering the image.
            self._resize_window_to_image(display_img.width, display_img.height)
            self.canvas_view.display(display_img)
        self._update_title()

    def _resize_window_to_image(self, img_w: int, img_h: int) -> None:
        """Resize the window to fit the displayed image, capped at monitor bounds."""
        max_w, max_h = self._get_max_image_size()
        win_w = min(img_w, max_w)
        win_h = min(img_h, max_h)
        self._resizing_programmatically = True
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.update_idletasks()
        self._resizing_programmatically = False

    def _update_display(self) -> None:
        """Refresh display without changing zoom or window size (for resize events)."""
        display_img = self.image_model.get_display_image(
            zoom=self.canvas_view.zoom,
            params=self.enhancement_params,
        )
        if display_img is not None:
            self.canvas_view.display(display_img)
        self._update_title()

    def _update_title(self) -> None:
        path = self.image_model.current_path
        if path is not None:
            name = path.name
            pos = self.file_list.position_str()
            w, h = self.image_model.get_working_size()
            zoom_pct = int(self.canvas_view.zoom * 100)
            self.root.title(f"pxv: {name} [{pos}] {w}x{h} ({zoom_pct}%)")
        else:
            self.root.title("pxv")


def main() -> None:
    """Entry point: parse args, create app, run main loop."""
    parser = argparse.ArgumentParser(description="pxv - A Python xv image viewer")
    parser.add_argument("paths", nargs="*", help="Image files or directories to open")
    args = parser.parse_args()

    root = tk.Tk(className="pxv")
    root.title("pxv")
    root.configure(bg="black")

    # Set initial window size — 75% of current monitor, capped at reasonable max
    mon_w, mon_h = _get_monitor_size(root)
    win_w = min(int(mon_w * 0.75), 1200)
    win_h = min(int(mon_h * 0.75), 900)
    root.geometry(f"{win_w}x{win_h}")

    paths = expand_paths(args.paths)
    file_list = FileList(paths)
    app = PxvApp(root, file_list)

    if file_list.count() > 0:
        # Delay loading until after mainloop starts so canvas has real dimensions
        root.after(50, app.load_current)
    else:
        # No files: show open dialog after startup
        root.after(100, lambda: commands.cmd_open(app))

    root.mainloop()


if __name__ == "__main__":
    main()
