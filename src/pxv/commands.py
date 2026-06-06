"""All action callbacks for pxv.

Each function takes the PxvApp instance and performs one action.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

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


def cmd_save_as(app: PxvApp) -> None:
    """Save the enhanced image via Save As dialog."""
    if app.image_model.working_image is None:
        return

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
        return

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
            return
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
        return

    if fmt == "GIF" and save_img.mode == "RGBA":
        save_img, gif_kwargs = _rgba_to_gif(save_img)
        save_kwargs.update(gif_kwargs)

    try:
        save_img.save(path, format=fmt, **save_kwargs)
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save image:\n{e}")


def cmd_crop(app: PxvApp) -> None:
    """Crop working image to the current rubber-band selection."""
    if not app.canvas_view.has_selection():
        return
    box = app.canvas_view.get_selection_image_coords(app.image_model.get_working_size())
    if box is None:
        return
    app.image_model.crop(box)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_resize(app: PxvApp) -> None:
    """Open resize dialog and apply."""
    from pxv.dialogs import resize_dialog

    current_size = app.image_model.get_working_size()
    if current_size == (0, 0):
        return
    new_size = resize_dialog(app.root, current_size)
    if new_size is not None:
        app.image_model.resize(new_size)
        app.canvas_view.clear_selection()
        app.refresh_display()


def cmd_reset(app: PxvApp) -> None:
    """Reset to original image and clear enhancements."""
    app.image_model.reset()
    app.enhancement_params.reset()
    app.canvas_view.clear_selection()
    if app.enhancement_dialog is not None:
        app.enhancement_dialog.sync_sliders_from_params()
    app.refresh_display()


def cmd_rotate(app: PxvApp, degrees: int) -> None:
    """Rotate working image by 90, 180, or 270 degrees."""
    app.image_model.rotate(degrees)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_flip_horizontal(app: PxvApp) -> None:
    app.image_model.flip_horizontal()
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_flip_vertical(app: PxvApp) -> None:
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
    app.canvas_view.zoom_normal()
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_increase(app: PxvApp) -> None:
    """Increase zoom by 10%."""
    app.canvas_view.zoom_set(app.canvas_view.zoom * 1.1)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_reduce(app: PxvApp) -> None:
    """Reduce zoom by 10%."""
    app.canvas_view.zoom_set(app.canvas_view.zoom * 0.9)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_double(app: PxvApp) -> None:
    """Double the zoom level."""
    app.canvas_view.zoom_set(app.canvas_view.zoom * 2.0)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_halve(app: PxvApp) -> None:
    """Halve the zoom level."""
    app.canvas_view.zoom_set(app.canvas_view.zoom * 0.5)
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_max(app: PxvApp) -> None:
    """Zoom to fill the display while preserving aspect ratio."""
    img_size = app.image_model.get_working_size()
    if img_size == (0, 0):
        return
    max_w, max_h = app._get_max_image_size()
    app.canvas_view.zoom_max(img_size, (max_w, max_h))
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_autocrop(app: PxvApp) -> None:
    """Auto-crop uniform background borders from the image."""
    if app.image_model.working_image is None:
        return
    if app.image_model.autocrop():
        app.canvas_view.clear_selection()
        app.refresh_display()
    else:
        # Brief status message in title bar, auto-restored after 2 seconds
        app.show_temp_title("pxv: Autocrop \u2013 nothing to crop")


def cmd_uncrop(app: PxvApp) -> None:
    """Undo the last crop operation."""
    if app.image_model.uncrop():
        app.canvas_view.clear_selection()
        app.refresh_display()


def cmd_next_image(app: PxvApp) -> None:
    # AIDEV-NOTE: Roll the cursor back if the load fails (corrupt/unreadable file),
    # so the file-list position stays in sync with the still-displayed image.
    prev_index = app.file_list.index
    if app.file_list.next() is not None and not app.load_current():
        app.file_list.index = prev_index


def cmd_prev_image(app: PxvApp) -> None:
    prev_index = app.file_list.index
    if app.file_list.prev() is not None and not app.load_current():
        app.file_list.index = prev_index


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
    from pxv.enhancement_dialog import EnhancementDialog

    if app.enhancement_dialog is not None:
        try:
            app.enhancement_dialog.deiconify()
            app.enhancement_dialog.lift()
            return
        except Exception:
            app.enhancement_dialog = None

    app.enhancement_dialog = EnhancementDialog(app)


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
    app.root.destroy()
