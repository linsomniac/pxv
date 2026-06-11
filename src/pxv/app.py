"""Main application: creates the Tk root, wires all components together.

AIDEV-NOTE: All keyboard bindings are on the root window so they work regardless
of which widget has focus. The enhancement dialog binds its own widget-level events.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tkinter as tk
from dataclasses import replace
from typing import TYPE_CHECKING

from pxv import commands
from pxv.annotation_render import render_overlay
from pxv.canvas_view import CanvasView
from pxv.context_menu import ContextMenu
from pxv.enhancements import EnhancementParams
from pxv.file_list import FileList, expand_paths
from pxv.history import History, Snapshot
from pxv.image_model import ImageModel
from pxv.save_options import SaveOptions
from pxv.slideshow import DEFAULT_SLIDESHOW_SECONDS, adjusted_interval_ms, interval_to_ms
from pxv.thumbnails import ThumbnailCache

if TYPE_CHECKING:
    from collections.abc import Sequence

    from PIL import Image

    from pxv.annotation_palette import AnnotationPalette
    from pxv.annotations import Shape
    from pxv.enhancement_dialog import EnhancementDialog
    from pxv.info_dialog import InfoDialog
    from pxv.thumbnail_browser import BrowserWindow


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
        # AIDEV-NOTE: Session-remembered Save As encoding options (JPEG quality,
        # PNG level, WebP lossless/quality, TIFF compression). Reset on restart.
        self.save_options = SaveOptions()
        # AIDEV-NOTE: Multi-level undo/redo. A snapshot is the full document state
        # (image buffers + enhancement params), captured before each destructive
        # edit and on undo/redo (see snapshot_state/_restore_snapshot below).
        self.history = History()

        # Will be set if the enhancement dialog is open
        self.enhancement_dialog: EnhancementDialog | None = None
        # Will be set if the info / EXIF dialog is open
        self.info_dialog: InfoDialog | None = None
        # Will be set if the drawing palette (draw mode) is open
        self.annotation_palette: AnnotationPalette | None = None
        # AIDEV-NOTE: Annotation-specific dirty flag (2026-06-10 design) — set
        # on the first shape and on bake; cleared by a successful save, a
        # confirmed discard prompt, and load_current. Other edits keep pxv's
        # historical silent-discard behavior.
        self.annotations_unsaved: bool = False
        # AIDEV-NOTE: The Visual Schnauzer thumbnail browser (a non-modal Toplevel).
        # Held here so commands/load_current can drive it; None when closed.
        self.browser: BrowserWindow | None = None
        # AIDEV-NOTE: Decoded PIL thumbnails keyed by resolved path. Lives on the app
        # (not the window) so it survives browser open/close and navigation.
        self.thumbnail_cache = ThumbnailCache()
        # AIDEV-NOTE: Toggles transparent-area compositing between white and black.
        # Only affects display; saving always uses the true alpha channel.
        self.dark_background: bool = False
        # AIDEV-NOTE: Set True while the Compare button is held in the enhancement
        # dialog; _active_params() returns identity params so the display renders
        # the original (pre-enhancement) image. Cleared on dialog close.
        self._compare_active: bool = False

        # AIDEV-NOTE: Presentation modes. In fullscreen the window stays screen-sized
        # (refresh_display skips the resize-to-image) and the image is fit to the
        # whole monitor. The slideshow drives cmd_next_image on a self-rescheduling
        # after() timer tracked by _slideshow_after_id so stop/quit cancels cleanly.
        self.fullscreen: bool = False
        self.slideshow_active: bool = False
        self.slideshow_interval_ms: int = interval_to_ms(DEFAULT_SLIDESHOW_SECONDS)
        self._slideshow_after_id: str | None = None

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
        # AIDEV-NOTE: Pending after-id for the transient title-bar status message.
        self._status_after_id: str | None = None

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
        self.root.bind("<Key-A>", lambda _: commands.cmd_autocrop(self))
        self.root.bind("<Key-u>", lambda _: commands.cmd_undo(self))
        self.root.bind("<Control-z>", lambda _: commands.cmd_undo(self))
        self.root.bind("<Control-y>", lambda _: commands.cmd_redo(self))
        self.root.bind("<Control-Shift-Z>", lambda _: commands.cmd_redo(self))
        self.root.bind("<Key-n>", lambda _: commands.cmd_zoom_normal(self))
        self.root.bind("<Key-e>", lambda _: commands.cmd_enhancement_dialog(self))
        self.root.bind("<Key-comma>", lambda _: commands.cmd_zoom_reduce(self))
        self.root.bind("<Key-period>", lambda _: commands.cmd_zoom_increase(self))
        self.root.bind("<greater>", lambda _: commands.cmd_zoom_double(self))
        self.root.bind("<less>", lambda _: commands.cmd_zoom_halve(self))
        self.root.bind("<Key-M>", lambda _: commands.cmd_zoom_max(self))
        self.root.bind("<Key-D>", lambda _: commands.cmd_toggle_background(self))
        self.root.bind("<Key-t>", lambda _: commands.cmd_rotate(self, 270))
        self.root.bind("<Key-T>", lambda _: commands.cmd_rotate(self, 90))
        self.root.bind("<Control-s>", lambda _: commands.cmd_save_as(self))
        self.root.bind("<space>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<Right>", lambda _: commands.cmd_next_image(self))
        self.root.bind("<BackSpace>", lambda _: commands.cmd_prev_image(self))
        self.root.bind("<Left>", lambda _: commands.cmd_prev_image(self))
        self.root.bind("<Escape>", lambda _: commands.cmd_escape(self))
        self.root.bind("<question>", lambda _: commands.cmd_help(self))
        self.root.bind("<Key-i>", lambda _: commands.cmd_info(self))
        self.root.bind("<Key-b>", lambda _: commands.cmd_toggle_browser(self))
        self.root.bind("<Key-f>", lambda _: commands.cmd_toggle_fullscreen(self))
        self.root.bind("<F11>", lambda _: commands.cmd_toggle_fullscreen(self))
        self.root.bind("<Key-s>", lambda _: commands.cmd_toggle_slideshow(self))
        self.root.bind("<plus>", lambda _: commands.cmd_slideshow_adjust(self, 1))
        self.root.bind("<KP_Add>", lambda _: commands.cmd_slideshow_adjust(self, 1))
        self.root.bind("<minus>", lambda _: commands.cmd_slideshow_adjust(self, -1))
        self.root.bind("<KP_Subtract>", lambda _: commands.cmd_slideshow_adjust(self, -1))

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
            # AIDEV-NOTE: Clear any rubber-band selection — its canvas-space coords
            # are stale once the image re-centers at the new canvas size, so a
            # subsequent crop would target the wrong region. Every other mutating
            # path clears the selection; this one must too.
            self.canvas_view.clear_selection()
            self.canvas_view.clear_preview()
            self._update_display()

    def _on_right_click(self, event: tk.Event) -> None:
        self.context_menu.show(event)

    def restore_main_focus(self) -> None:
        """Force keyboard focus back to the image canvas after a dialog closes.

        AIDEV-NOTE: Every shortcut is bound on self.root (see _bind_keys), so a
        key only fires while a widget in root's bindtag chain holds the input
        focus. The info/enhancement panels are non-modal transients with NO
        grab_set, so closing one does not reliably return X input focus to the
        main window: under click-to-focus root never received a click, and under
        focus-follows-mouse the pointer is over the just-closed dialog (which
        opens BESIDE the main window). The app then looks "locked up" — every key
        binding is dead while pointer/rubber-band events still work. focus_force()
        (not focus_set()) is required: focus_set silently defers until the app
        next gains WM focus, which is exactly the state that was lost, whereas
        focus_force reclaims it immediately under both focus models. Guarded so a
        close during teardown is a safe no-op.

        Call this AFTER the dialog's destroy(): destroying a Toplevel that holds
        the input focus clears the focus, which would undo a pre-destroy reclaim.
        """
        canvas = self.canvas_view.canvas
        if canvas.winfo_exists():
            canvas.focus_force()

    def load_current(self) -> bool:
        """Load the current file from the file list. Returns True on success.

        AIDEV-NOTE: Returns success so navigation can roll back the file-list
        cursor on a failed load, keeping the cursor and the displayed image in sync.
        """
        path = self.file_list.current()
        if path is None:
            return False
        try:
            self.image_model.load(path)
        except Exception as e:
            from tkinter import messagebox

            messagebox.showerror("Open Error", f"Could not open {path.name}:\n{e}")
            return False

        self.enhancement_params.reset()
        # AIDEV-NOTE: A freshly loaded image starts with empty undo/redo history.
        self.history.clear()
        self.annotations_unsaved = False
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.sync_sliders_from_params()
        if self.info_dialog is not None:
            self.info_dialog.refresh()
        self.canvas_view.clear_selection()

        # Fit to the available area (monitor in fullscreen, else window-capped).
        self._apply_fit()

        self.refresh_display()
        # AIDEV-NOTE: Keep the open browser's highlight on the displayed image. This
        # covers every load path (Space/arrows, jumps, Open). sync_selection never
        # loads, so there is no recursion with _activate -> cmd_show_index.
        if self.browser is not None:
            self.browser.sync_selection(self.file_list.index)
        return True

    def _apply_fit(self) -> None:
        """Zoom-fit the working image to the available area.

        Fullscreen fits to the whole monitor; otherwise to the window-capped size.
        """
        img_size = self.image_model.get_working_size()
        if self.fullscreen:
            bounds = _get_monitor_size(self.root)
        else:
            bounds = self._get_max_image_size()
        self.canvas_view.zoom_fit(img_size, bounds)

    def show_temp_title(self, message: str, duration_ms: int = 2000) -> None:
        """Show a transient message in the title bar, then restore the real title.

        AIDEV-NOTE: Tracks the pending after-id so repeated calls don't stack, and
        the restore is guarded by winfo_exists() so a quit within the window is a
        safe no-op rather than a callback against a destroyed interpreter.
        """
        if self._status_after_id is not None:
            self.root.after_cancel(self._status_after_id)
        self.root.title(message)
        self._status_after_id = self.root.after(duration_ms, self._restore_title)

    def _restore_title(self) -> None:
        self._status_after_id = None
        if self.root.winfo_exists():
            self._update_title()

    def _bg_color(self) -> tuple[int, int, int]:
        return (0, 0, 0) if self.dark_background else (255, 255, 255)

    # --- undo / redo ----------------------------------------------------

    def snapshot_state(self) -> Snapshot | None:
        """Capture the full editable document state, or None if no image is loaded."""
        buffers = self.image_model.snapshot_buffers()
        if buffers is None:
            return None
        working, save_rgba = buffers
        return Snapshot(working, save_rgba, replace(self.enhancement_params))

    def record_history(self) -> None:
        """Record the current state onto the undo stack before a destructive edit."""
        snap = self.snapshot_state()
        if snap is not None:
            self.history.record(snap)

    # --- annotations (draw mode) -----------------------------------------

    def bake_annotations(self, shapes: Sequence[Shape]) -> None:
        """Rasterize shapes into the image pixels as ONE undoable edit.

        The crop/rotate command pattern: snapshot, mutate, refresh. An empty
        layer exits silently with no history snapshot (checked up front, so
        autocrop's conditional-snapshot dance is not needed).

        AIDEV-NOTE: The bake composites onto the PRE-enhancement working
        image, while the preview composited onto the post-enhancement display
        — parity holds exactly when EnhancementParams is identity (the common
        case). With live non-identity params the annotation pixels become
        subject to the enhancement pass from here on: colors visibly shift at
        Done and in the saved file. Accepted in the 2026-06-10 design — do
        NOT "fix" this by inverse-mapping colors.
        """
        working = self.image_model.working_image
        if working is None or not shapes:
            return
        self.record_history()
        overlay = render_overlay(shapes, working.size, 1.0)
        self.image_model.apply_overlay(overlay)
        self.annotations_unsaved = True
        self.refresh_display()

    def undo(self) -> None:
        if not self.history.can_undo:
            self.show_temp_title("pxv: nothing to undo")
            return
        current = self.snapshot_state()
        if current is None:
            return
        restored = self.history.undo(current)
        if restored is not None:
            self._restore_snapshot(restored)

    def redo(self) -> None:
        if not self.history.can_redo:
            self.show_temp_title("pxv: nothing to redo")
            return
        current = self.snapshot_state()
        if current is None:
            return
        restored = self.history.redo(current)
        if restored is not None:
            self._restore_snapshot(restored)

    def _restore_snapshot(self, snap: Snapshot) -> None:
        """Install a snapshot as the live document state and redraw (zoom preserved)."""
        self.image_model.restore_buffers(snap.working_image, snap.save_rgba)
        # AIDEV-NOTE: Replace (don't mutate) the params object — every consumer
        # dereferences app.enhancement_params fresh, so a new object is safe and
        # leaves the snapshot's copy untouched.
        self.enhancement_params = replace(snap.params)
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.sync_sliders_from_params()
        self.canvas_view.clear_selection()
        self.refresh_display()

    def _active_params(self) -> EnhancementParams:
        """Identity params while Compare is held in the dialog, else the live ones.

        AIDEV-NOTE: Read at refresh time, so an in-flight debounce timer firing
        during a Compare hold still renders the compare (original) state.
        """
        return EnhancementParams() if self._compare_active else self.enhancement_params

    def _composite_annotations(self, display_img: Image.Image | None) -> Image.Image | None:
        """Composite the live annotation overlay onto a fresh display render.

        AIDEV-NOTE: The ONE composite hook shared by refresh_display and
        _update_display — without the resize path, shapes would vanish on
        window resize. Only the rendered overlay is cached (in the palette,
        keyed on (layer.revision, display size)); the composite happens fresh
        every call because the base changes under the same key (enhancement
        debounce, Compare, background toggle). Also the stale-image guard's
        first checkpoint: never composite against a replaced image.
        """
        palette = self.annotation_palette
        if display_img is None or palette is None or not palette.layer.shapes:
            return display_img
        if not palette.image_is_current():
            palette.cancel_stale()  # tears down + refreshes; skip the overlay
            return display_img
        overlay = palette.render_display_overlay(display_img.size, self.canvas_view.zoom)
        display_img.paste(overlay, (0, 0), overlay)
        return display_img

    def refresh_display(self) -> None:
        """Re-render the image with current zoom and enhancement params."""
        display_img = self.image_model.get_display_image(
            zoom=self.canvas_view.zoom,
            params=self._active_params(),
            bg_color=self._bg_color(),
        )
        display_img = self._composite_annotations(display_img)
        if display_img is not None:
            # AIDEV-NOTE: Resize window BEFORE display() so the canvas has correct
            # dimensions when centering the image. Skipped in fullscreen, where the
            # window must stay screen-sized and the image is centered on black.
            if not self.fullscreen:
                self._resize_window_to_image(display_img.width, display_img.height)
            self.canvas_view.display(display_img)
        # AIDEV-NOTE: The histogram tracks the post-enhancement preview — exactly
        # what the user sees, including the background composite for transparent
        # images (accepted in the 2026-06-10 design). None blanks the panel.
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.update_histogram(display_img)
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
            params=self._active_params(),
            bg_color=self._bg_color(),
        )
        display_img = self._composite_annotations(display_img)
        if display_img is not None:
            self.canvas_view.display(display_img)
        if self.enhancement_dialog is not None:
            self.enhancement_dialog.update_histogram(display_img)
        self._update_title()

    def _update_title(self) -> None:
        # AIDEV-NOTE: Skip if a temp title is in flight (show_temp_title set
        # _status_after_id). This lets stale-image cancel_stale() call
        # show_temp_title BEFORE the outer refresh_display's trailing
        # _update_title fires — without this guard the outer call would
        # overwrite the stale message (2026-06-10 design).
        if self._status_after_id is not None:
            return
        path = self.image_model.current_path
        if path is not None:
            name = path.name
            pos = self.file_list.position_str()
            w, h = self.image_model.get_working_size()
            zoom_pct = int(self.canvas_view.zoom * 100)
            self.root.title(f"pxv: {name} [{pos}] {w}x{h} ({zoom_pct}%)")
        else:
            self.root.title("pxv")

    # --- presentation modes ---------------------------------------------

    def toggle_fullscreen(self) -> None:
        """Toggle borderless fullscreen, re-fitting the image to the new area."""
        self.set_fullscreen(not self.fullscreen)

    def set_fullscreen(self, on: bool) -> None:
        """Enter or leave fullscreen and re-fit/redraw the current image."""
        self.fullscreen = on
        # AIDEV-NOTE: Some WMs ignore -fullscreen; keep self.fullscreen authoritative
        # so refresh_display/_apply_fit stay consistent regardless.
        try:
            self.root.attributes("-fullscreen", on)
        except tk.TclError:
            pass
        self.root.update_idletasks()
        self.canvas_view.clear_selection()
        if self.image_model.working_image is not None:
            self._apply_fit()
            self.refresh_display()

    def toggle_slideshow(self) -> None:
        if self.slideshow_active:
            self.stop_slideshow()
        else:
            self.start_slideshow()

    def start_slideshow(self) -> None:
        if self.slideshow_active:
            return
        self.slideshow_active = True
        secs = self.slideshow_interval_ms // 1000
        self.show_temp_title(f"pxv: slideshow on ({secs}s)")
        self._schedule_slideshow()

    def stop_slideshow(self) -> None:
        if not self.slideshow_active:
            return
        self.slideshow_active = False
        self._cancel_slideshow()
        self.show_temp_title("pxv: slideshow off")

    def _cancel_slideshow(self) -> None:
        if self._slideshow_after_id is not None:
            self.root.after_cancel(self._slideshow_after_id)
            self._slideshow_after_id = None

    def _schedule_slideshow(self) -> None:
        self._slideshow_after_id = self.root.after(
            self.slideshow_interval_ms, self._slideshow_tick
        )

    def _slideshow_tick(self) -> None:
        # AIDEV-NOTE: Guard against a tick firing after the window is gone; reschedule
        # only while still active so stop_slideshow()/quit ends the chain cleanly.
        self._slideshow_after_id = None
        if not self.slideshow_active or not self.root.winfo_exists():
            return
        commands.cmd_next_image(self)
        if self.slideshow_active:
            self._schedule_slideshow()

    def adjust_slideshow_interval(self, delta_seconds: float) -> None:
        """Change the slideshow interval by +/- seconds (clamped), live if running."""
        self.slideshow_interval_ms = adjusted_interval_ms(
            self.slideshow_interval_ms, delta_seconds
        )
        secs = self.slideshow_interval_ms // 1000
        self.show_temp_title(f"pxv: slideshow {secs}s")
        if self.slideshow_active:
            self._cancel_slideshow()
            self._schedule_slideshow()

    def escape_action(self) -> None:
        """Escape: leave presentation modes if active, else clear the selection."""
        if self.slideshow_active or self.fullscreen:
            if self.slideshow_active:
                self.stop_slideshow()
            if self.fullscreen:
                self.set_fullscreen(False)
            return
        self.canvas_view.clear_selection()


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser.

    AIDEV-NOTE: Extracted from main() so argument parsing is unit-testable without
    constructing a Tk root. __version__ is imported lazily (not at module top)
    because app.py is imported during pxv/__init__ before __version__ is assigned —
    a top-level import would be circular. Mirrors commands.py's local import.
    """
    from pxv import __version__

    parser = argparse.ArgumentParser(description="pxv - A Python xv image viewer")
    parser.add_argument("--version", action="version", version=f"pxv {__version__}")
    parser.add_argument(
        "--slideshow",
        nargs="?",
        type=float,
        const=DEFAULT_SLIDESHOW_SECONDS,
        default=None,
        metavar="SECS",
        help="Start a slideshow, advancing every SECS seconds (default %(const)s).",
    )
    parser.add_argument("--fullscreen", action="store_true", help="Start in fullscreen mode.")
    parser.add_argument("paths", nargs="*", help="Image files or directories to open")
    return parser


def main() -> None:
    """Entry point: parse args, create app, run main loop."""
    args = _build_parser().parse_args()

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

    if args.slideshow is not None:
        app.slideshow_interval_ms = interval_to_ms(args.slideshow)

    def _apply_startup_modes() -> None:
        # AIDEV-NOTE: Applied after the first load so the image is fit to the right
        # area (fullscreen changes the fit bounds) before the slideshow starts.
        if not root.winfo_exists():
            return
        if args.fullscreen:
            app.set_fullscreen(True)
        if args.slideshow is not None:
            app.start_slideshow()

    # AIDEV-NOTE: Deferred so the canvas has real dimensions once mainloop starts.
    # Guarded by winfo_exists() in case the window is closed before the timer fires.
    def _load_when_ready() -> None:
        if root.winfo_exists():
            app.load_current()
            _apply_startup_modes()

    def _open_when_ready() -> None:
        if root.winfo_exists():
            commands.cmd_open(app)

    if file_list.count() > 0:
        root.after(50, _load_when_ready)
    else:
        # No files: show open dialog after startup
        root.after(100, _open_when_ready)

    root.mainloop()


if __name__ == "__main__":
    main()
