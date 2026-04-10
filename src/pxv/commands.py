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

if TYPE_CHECKING:
    from pxv.app import PxvApp

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

_OPEN_FILETYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp *.ppm *.pgm *.pbm *.ico"),
    ("All files", "*.*"),
]


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

    ext = Path(path).suffix.lower()
    fmt = _FORMAT_MAP.get(ext, "PNG")
    save_kwargs: dict[str, object] = {}
    if fmt == "JPEG":
        save_kwargs["quality"] = 95

    save_img = app.image_model.get_save_image(
        app.enhancement_params, preserve_alpha=fmt in _ALPHA_FORMATS
    )
    if save_img is None:
        return

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
    try:
        from PIL import ImageGrab

        x = app.root.winfo_rootx()
        y = app.root.winfo_rooty()
        w = app.root.winfo_width()
        h = app.root.winfo_height()
        screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))

        path = filedialog.asksaveasfilename(
            title="Save Screenshot",
            filetypes=_SAVE_FILETYPES,
            initialfile="screenshot.png",
        )
        if path:
            ext = Path(path).suffix.lower()
            fmt = _FORMAT_MAP.get(ext, "PNG")
            screenshot.save(path, format=fmt)
    except Exception as e:
        messagebox.showerror("Grab Error", f"Could not capture screenshot:\n{e}")


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


def cmd_zoom_in(app: PxvApp) -> None:
    app.canvas_view.zoom_in()
    app.canvas_view.clear_selection()
    app.refresh_display()


def cmd_zoom_out(app: PxvApp) -> None:
    app.canvas_view.zoom_out()
    app.canvas_view.clear_selection()
    app.refresh_display()


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


def cmd_uncrop(app: PxvApp) -> None:
    """Undo the last crop operation."""
    if app.image_model.uncrop():
        app.canvas_view.clear_selection()
        app.refresh_display()


def cmd_next_image(app: PxvApp) -> None:
    p = app.file_list.next()
    if p is not None:
        app.load_current()


def cmd_prev_image(app: PxvApp) -> None:
    p = app.file_list.prev()
    if p is not None:
        app.load_current()


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
