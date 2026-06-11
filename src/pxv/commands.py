"""All action callbacks for pxv.

Each function takes the PxvApp instance and performs one action.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Literal

from PIL import Image

from pxv import metadata, save_options

if TYPE_CHECKING:
    from pxv.app import PxvApp
    from pxv.image_model import ImageModel

# Supported save formats
_SAVE_FILETYPES = [
    ("PNG", "*.png"),
    ("JPEG", "*.jpg *.jpeg"),
    ("BMP", "*.bmp"),
    ("TIFF", "*.tif *.tiff"),
    ("WebP", "*.webp"),
    ("GIF", "*.gif"),
    ("All files", "*.*"),
]

_FORMAT_MAP = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".webp": "WEBP",
    ".gif": "GIF",
}

_ALPHA_FORMATS = {"PNG", "WEBP", "TIFF"}

# Formats Pillow can write an exif= block to. GIF/BMP/PPM/ICO cannot.
_EXIF_WRITE_FORMATS = {"JPEG", "TIFF", "WEBP", "PNG"}

_OPEN_FILETYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp *.ppm *.pgm *.pbm *.ico"),
    ("All files", "*.*"),
]


def annotation_gate(app: PxvApp, kind: Literal["mutate", "zoom", "navigate"]) -> bool:
    """Draw-mode chokepoint: may the calling command proceed?

    AIDEV-NOTE: ONE gate for the whole command surface (2026-06-10 design) —
    root keys and context-menu entries call the same cmd_* functions, so a
    single check at the top of each covers both. Kinds:
    - "mutate": image-mutating and save commands — consumed with a title hint
      while the palette is open.
    - "zoom": consumed only while an annotation drag is in flight.
    - "navigate": consumed during a drag; otherwise unsaved annotation work
      prompts "Discard annotations?" — confirming ends an active session,
      clears the flag, and proceeds. An open session with NOTHING at stake
      (empty layer, no unsaved bake) is silently torn down so navigation
      never orphans canvas state.
    Undo/redo and Escape do not come here: they route through the palette's
    on_undo_key/on_redo_key/on_escape (see cmd_undo/cmd_redo/cmd_escape).
    """
    palette = app.annotation_palette
    if kind == "mutate":
        if palette is not None:
            app.show_temp_title("pxv: close the drawing palette first")
            return False
        return True
    if palette is not None and palette.is_dragging:
        return False
    if kind == "zoom":
        return True
    # kind == "navigate"
    if app.annotations_unsaved:
        if not messagebox.askyesno("pxv", "Discard annotations?"):
            return False
        app.annotations_unsaved = False
    if palette is not None:
        palette._end_session(bake=False)
    return True


def _resolve_save_format(path: str) -> tuple[str, str]:
    """Resolve the Pillow format and a normalized path for a save target.

    AIDEV-NOTE: If the extension is missing or unrecognized we default to PNG and
    rewrite the suffix to .png, so the file's name matches its actual PNG content
    (previously PNG bytes were written under a mismatched or extensionless name).
    """
    ext = Path(path).suffix.lower()
    fmt = _FORMAT_MAP.get(ext)
    if fmt is None:
        return "PNG", str(Path(path).with_suffix(".png"))
    return fmt, path


def _rgba_to_gif(img: Image.Image) -> tuple[Image.Image, dict[str, object]]:
    """Convert an RGBA image to a palettized frame with binary GIF transparency.

    AIDEV-NOTE: GIF supports only a single transparent palette index (not partial
    alpha), so we reserve index 255 for fully/mostly-transparent pixels (alpha < 128).
    This keeps transparent regions transparent instead of flattening them to white.
    """
    alpha = img.split()[3]
    transparent_mask = alpha.point(lambda a: 255 if a < 128 else 0)
    palette_img = img.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    palette_img.paste(255, transparent_mask)
    return palette_img, {"transparency": 255, "optimize": True}


def cmd_open(app: PxvApp) -> None:
    """Open a file via dialog, add to file list, and display."""
    if not annotation_gate(app, "navigate"):
        return
    initial_dir = None
    if app.image_model.current_path is not None:
        initial_dir = str(app.image_model.current_path.parent)

    path = filedialog.askopenfilename(
        title="Open Image",
        filetypes=_OPEN_FILETYPES,
        initialdir=initial_dir,
    )
    if not path:
        return
    p = Path(path)
    app.file_list.add(p)
    app.load_current()
    # AIDEV-NOTE: A newly opened file must appear in the Visual Schnauzer if it's open.
    if app.browser is not None:
        app.browser.rebuild()


def _exif_for_save(model: "ImageModel", fmt: str) -> bytes | None:
    """Return sanitized EXIF bytes to write, or None to strip (today's default).

    AIDEV-NOTE: Pure decision helper (no UI) so it is unit-testable without Tk.
    """
    meta = model.metadata
    if model.keep_metadata and meta is not None and fmt in _EXIF_WRITE_FORMATS:
        # AIDEV-NOTE: bind through a typed local — Exif.tobytes() is Any (PIL untyped),
        # and returning Any from a -> bytes | None function trips mypy warn_return_any.
        data: bytes = metadata.build_save_exif(meta).tobytes()
        return data
    return None


def cmd_save_as(app: PxvApp) -> bool:
    """Save the enhanced image via Save As dialog.

    Returns True only when a file was actually written — cancel (either
    dialog), failure, and the draw-mode gate all return False, so the
    annotations_unsaved flag survives everything short of a real save.
    """
    if not annotation_gate(app, "mutate"):
        return False
    if app.image_model.working_image is None:
        return False

    initial_dir = None
    initial_file = ""
    if app.image_model.current_path is not None:
        initial_dir = str(app.image_model.current_path.parent)
        initial_file = app.image_model.current_path.name

    path = filedialog.asksaveasfilename(
        title="Save Image As",
        filetypes=_SAVE_FILETYPES,
        initialdir=initial_dir,
        initialfile=initial_file,
    )
    if not path:
        return False

    fmt, path = _resolve_save_format(path)

    # For formats with tunable encoders, let the user pick options (and toggle
    # metadata) before saving. Cancelling the dialog aborts the whole save.
    if fmt in save_options.FORMATS_WITH_OPTIONS:
        from pxv.dialogs import save_options_dialog

        keep_supported = fmt in _EXIF_WRITE_FORMATS
        chosen = save_options_dialog(
            app.root, fmt, app.save_options, app.image_model.keep_metadata, keep_supported
        )
        if chosen is None:
            return False
        app.save_options, app.image_model.keep_metadata = chosen
        # Keep the Info dialog's "Keep metadata" checkbox in sync.
        if app.info_dialog is not None:
            app.info_dialog.refresh()

    save_kwargs: dict[str, object] = save_options.build_save_kwargs(fmt, app.save_options)
    exif_bytes = _exif_for_save(app.image_model, fmt)
    if exif_bytes is not None:
        save_kwargs["exif"] = exif_bytes
    elif app.image_model.keep_metadata and fmt not in _EXIF_WRITE_FORMATS:
        app.show_temp_title(f"pxv: metadata not saved for {fmt}")

    # GIF carries binary transparency; PNG/WEBP/TIFF carry full alpha. For all of
    # these we enhance the true RGBA so transparent pixels survive the round-trip.
    preserve_alpha = fmt in _ALPHA_FORMATS or fmt == "GIF"
    save_img = app.image_model.get_save_image(
        app.enhancement_params, preserve_alpha=preserve_alpha
    )
    if save_img is None:
        return False

    if fmt == "GIF" and save_img.mode == "RGBA":
        save_img, gif_kwargs = _rgba_to_gif(save_img)
        save_kwargs.update(gif_kwargs)

    try:
        save_img.save(path, format=fmt, **save_kwargs)
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save image:\n{e}")
        return False
    # AIDEV-NOTE: A successful save clears the annotation dirty flag (the
    # 2026-06-10 lifecycle); the bool return exists because None-on-everything
    # could not distinguish a cancelled dialog from a written file.
    app.annotations_unsaved = False
    return True


def cmd_crop(app: PxvApp) -> None:
    """Crop working image to the current rubber-band selection."""
    if not annotation_gate(app, "mutate"):
        return
    if not app.canvas_view.has_selection():
        return
    box = app.canvas_view.get_selection_image_coords(app.image_model.get_working_size())
    if box is None:
        return
    app.record_history()
    app.image_model.crop(box)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_resize(app: PxvApp) -> None:
    """Open resize dialog and apply."""
    if not annotation_gate(app, "mutate"):
        return
    from pxv.dialogs import resize_dialog

    current_size = app.image_model.get_working_size()
    if current_size == (0, 0):
        return
    new_size = resize_dialog(app.root, current_size)
    if new_size is not None:
        app.record_history()
        app.image_model.resize(new_size)
        app.canvas_view.clear_selection()
        app.refresh_display()


def cmd_reset(app: PxvApp) -> None:
    """Reset to original image and clear enhancements."""
    if not annotation_gate(app, "mutate"):
        return
    app.image_model.reset()
    app.enhancement_params.reset()
    app.history.clear()
    app.canvas_view.clear_selection()
    if app.enhancement_dialog is not None:
        app.enhancement_dialog.sync_sliders_from_params()
    app.refresh_display()


def cmd_rotate(app: PxvApp, degrees: int) -> None:
    """Rotate working image by 90, 180, or 270 degrees."""
    if not annotation_gate(app, "mutate"):
        return
    app.record_history()
    app.image_model.rotate(degrees)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_flip_horizontal(app: PxvApp) -> None:
    if not annotation_gate(app, "mutate"):
        return
    app.record_history()
    app.image_model.flip_horizontal()
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_flip_vertical(app: PxvApp) -> None:
    if not annotation_gate(app, "mutate"):
        return
    app.record_history()
    app.image_model.flip_vertical()
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_grab(app: PxvApp) -> None:
    """Grab a screenshot of the pxv window and offer to save it."""
    # AIDEV-NOTE: Keep capture and save in separate try blocks so a save failure
    # (disk full, permissions) isn't mislabeled as a screenshot-capture error.
    try:
        from PIL import ImageGrab

        x = app.root.winfo_rootx()
        y = app.root.winfo_rooty()
        w = app.root.winfo_width()
        h = app.root.winfo_height()
        screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    except Exception as e:
        messagebox.showerror("Grab Error", f"Could not capture screenshot:\n{e}")
        return

    path = filedialog.asksaveasfilename(
        title="Save Screenshot",
        filetypes=_SAVE_FILETYPES,
        initialfile="screenshot.png",
    )
    if not path:
        return

    fmt, path = _resolve_save_format(path)
    try:
        screenshot.save(path, format=fmt)
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save screenshot:\n{e}")


def cmd_print(app: PxvApp) -> None:
    """Print the current image (best-effort via lpr on Linux)."""
    save_img = app.image_model.get_save_image(app.enhancement_params)
    if save_img is None:
        return

    if sys.platform == "linux":
        # AIDEV-NOTE: lpr copies the file into the CUPS spool, so it's safe to
        # unlink immediately after subprocess.run returns.
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name
                save_img.save(tmp_path, format="PNG")
            subprocess.run(["lpr", tmp_path], check=True)
            messagebox.showinfo("Print", "Image sent to default printer.")
        except FileNotFoundError:
            messagebox.showerror("Print Error", "lpr command not found. Install CUPS.")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Print Error", f"Print failed:\n{e}")
        finally:
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)
    else:
        messagebox.showinfo("Print", "Printing is only supported on Linux via lpr.")


def cmd_zoom_normal(app: PxvApp) -> None:
    """Reset zoom to 1:1 pixel mapping."""
    if not annotation_gate(app, "zoom"):
        return
    app.canvas_view.zoom_normal()
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_increase(app: PxvApp) -> None:
    """Increase zoom by 10%."""
    if not annotation_gate(app, "zoom"):
        return
    app.canvas_view.zoom_set(app.canvas_view.zoom * 1.1)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_reduce(app: PxvApp) -> None:
    """Reduce zoom by 10%."""
    if not annotation_gate(app, "zoom"):
        return
    app.canvas_view.zoom_set(app.canvas_view.zoom * 0.9)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_double(app: PxvApp) -> None:
    """Double the zoom level."""
    if not annotation_gate(app, "zoom"):
        return
    app.canvas_view.zoom_set(app.canvas_view.zoom * 2.0)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_halve(app: PxvApp) -> None:
    """Halve the zoom level."""
    if not annotation_gate(app, "zoom"):
        return
    app.canvas_view.zoom_set(app.canvas_view.zoom * 0.5)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_max(app: PxvApp) -> None:
    """Zoom to fill the display while preserving aspect ratio."""
    if not annotation_gate(app, "zoom"):
        return
    img_size = app.image_model.get_working_size()
    if img_size == (0, 0):
        return
    max_w, max_h = app._get_max_image_size()
    app.canvas_view.zoom_max(img_size, (max_w, max_h))
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_autocrop(app: PxvApp) -> None:
    """Auto-crop uniform background borders from the image."""
    if not annotation_gate(app, "mutate"):
        return
    if app.image_model.working_image is None:
        return
    # AIDEV-NOTE: Capture before cropping, but only record if it actually crops \u2014
    # otherwise an undo entry would appear for a no-op autocrop.
    snap = app.snapshot_state()
    if app.image_model.autocrop():
        if snap is not None:
            app.history.record(snap)
        app.canvas_view.clear_selection()
        app.refresh_display()
    else:
        # Brief status message in title bar, auto-restored after 2 seconds
        app.show_temp_title("pxv: Autocrop \u2013 nothing to crop")


def cmd_undo(app: PxvApp) -> None:
    """Undo the last destructive edit (crop, rotate, flip, resize, Apply).

    While draw mode is active, ALL undo entry points (u, Ctrl-z, context
    menu) land in the palette and never fall through to app history.
    """
    if app.annotation_palette is not None:
        app.annotation_palette.on_undo_key()
        return
    app.undo()


def cmd_redo(app: PxvApp) -> None:
    """Redo the last undone edit (palette-routed while draw mode is active)."""
    if app.annotation_palette is not None:
        app.annotation_palette.on_redo_key()
        return
    app.redo()


def cmd_next_image(app: PxvApp) -> None:
    if not annotation_gate(app, "navigate"):
        return
    # AIDEV-NOTE: Roll the cursor back if the load fails (corrupt/unreadable file),
    # so the file-list position stays in sync with the still-displayed image.
    prev_index = app.file_list.index
    if app.file_list.next() is not None and not app.load_current():
        app.file_list.index = prev_index


def cmd_prev_image(app: PxvApp) -> None:
    if not annotation_gate(app, "navigate"):
        return
    prev_index = app.file_list.index
    if app.file_list.prev() is not None and not app.load_current():
        app.file_list.index = prev_index


def cmd_toggle_browser(app: PxvApp) -> None:
    """Open the Visual Schnauzer thumbnail browser, or close it if already open."""
    if app.browser is not None:
        app.browser._on_close()
        return
    from pxv.thumbnail_browser import BrowserWindow

    app.browser = BrowserWindow(app)


def cmd_show_index(app: PxvApp, index: int) -> None:
    """Jump the viewer to file-list position `index` (no-op if out of range).

    AIDEV-NOTE: On a failed full-res load, roll the cursor back like cmd_next_image
    and re-sync the grid highlight to the still-displayed image. On success,
    load_current() itself re-syncs the highlight (the grid<-viewer direction), so
    this only re-syncs on the rollback path.
    """
    if not annotation_gate(app, "navigate"):
        return
    if not (0 <= index < app.file_list.count()):
        return
    prev_index = app.file_list.index
    app.file_list.index = index
    if not app.load_current():
        app.file_list.index = prev_index
        if app.browser is not None:
            app.browser.sync_selection(app.file_list.index)


def cmd_info(app: PxvApp) -> None:
    """Open or raise the image info / EXIF dialog."""
    from pxv.info_dialog import InfoDialog

    if app.info_dialog is not None:
        try:
            app.info_dialog.deiconify()
            app.info_dialog.lift()
            app.info_dialog.refresh()
            return
        except Exception:
            app.info_dialog = None

    if app.image_model.metadata is None:
        return
    app.info_dialog = InfoDialog(app)


def cmd_enhancement_dialog(app: PxvApp) -> None:
    """Open or raise the enhancement dialog."""
    if not annotation_gate(app, "mutate"):
        return
    from pxv.enhancement_dialog import EnhancementDialog

    if app.enhancement_dialog is not None:
        try:
            app.enhancement_dialog.deiconify()
            app.enhancement_dialog.lift()
            return
        except Exception:
            app.enhancement_dialog = None

    app.enhancement_dialog = EnhancementDialog(app)
    # Seed the histogram panel: the refresh paths feed it on every render, but
    # a freshly opened dialog needs one render to pull the current image in.
    app.refresh_display()


def cmd_annotate(app: PxvApp) -> None:
    """Open the drawing palette (draw mode), or raise/focus it if already open.

    AIDEV-NOTE: `d` with the palette open never closes or bakes — it raises
    and focuses (the enhancement-dialog precedent). Draw mode and the Enhance
    dialog gate each other so eyedropper pick mode and the drawing session
    can never share the canvas. Opening stops an active slideshow.
    """
    if app.annotation_palette is not None:
        try:
            app.annotation_palette.deiconify()
            app.annotation_palette.lift()
            app.annotation_palette.focus_set()
            return
        except Exception:
            app.annotation_palette = None

    if app.image_model.working_image is None:
        return
    if app.enhancement_dialog is not None:
        app.show_temp_title("pxv: close the Enhancements dialog first")
        return

    from pxv.annotation_palette import AnnotationPalette

    app.stop_slideshow()  # a safe no-op when not running
    app.annotation_palette = AnnotationPalette(app)


def cmd_toggle_fullscreen(app: PxvApp) -> None:
    """Toggle borderless fullscreen presentation mode."""
    app.toggle_fullscreen()


def cmd_toggle_slideshow(app: PxvApp) -> None:
    """Start or stop the auto-advance slideshow."""
    if not annotation_gate(app, "navigate"):
        return
    app.toggle_slideshow()


def cmd_slideshow_adjust(app: PxvApp, delta_seconds: float) -> None:
    """Adjust the slideshow interval by +/- seconds."""
    app.adjust_slideshow_interval(delta_seconds)


def cmd_escape(app: PxvApp) -> None:
    """Escape key: exit presentation modes if active, else clear the selection.

    While draw mode is active the session consumes Escape entirely (cancel an
    in-flight drag, never exit the mode) — leaving fullscreen mid-session is
    f/F11 (2026-06-10 design).
    """
    if app.annotation_palette is not None:
        app.annotation_palette.on_escape()
        return
    app.escape_action()


def cmd_toggle_background(app: PxvApp) -> None:
    """Toggle transparent image background between dark and light."""
    app.dark_background = not app.dark_background
    app.refresh_display()


def cmd_help(app: PxvApp) -> None:
    """Show keyboard shortcuts help dialog."""
    from pxv.dialogs import help_dialog

    help_dialog(app.root)


def cmd_about(app: PxvApp) -> None:
    from pxv import __version__

    messagebox.showinfo(
        "About pxv",
        f"pxv {__version__}\n\n"
        "A Python clone of the classic Unix xv image viewer\n"
        "by John Bradley.\n\n"
        "Built with Tkinter + Pillow.",
    )


def cmd_quit(app: PxvApp) -> None:
    if not annotation_gate(app, "navigate"):
        return
    # AIDEV-NOTE: Close the thumbnail browser first if open, so its pending loader/
    # reflow after() timers are cancelled before the interpreter is torn down
    # (otherwise a mid-load quit emits "invalid command name" noise on stderr).
    if app.browser is not None:
        app.browser._on_close()
    app.root.destroy()
