"""Right-click context menu for pxv, matching classic xv menu structure."""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from pxv import commands

if TYPE_CHECKING:
    from pxv.app import PxvApp


class ContextMenu:
    """Builds and manages the right-click context menu."""

    def __init__(self, root: tk.Tk, app: PxvApp) -> None:
        self.menu = tk.Menu(root, tearoff=0)

        self.menu.add_command(label="Open...", command=lambda: commands.cmd_open(app))
        self.menu.add_command(label="Save As...", command=lambda: commands.cmd_save_as(app))
        self.menu.add_separator()

        self.menu.add_command(label="Crop", command=lambda: commands.cmd_crop(app))
        self.menu.add_command(label="Autocrop", command=lambda: commands.cmd_autocrop(app))
        self.menu.add_command(label="Resize...", command=lambda: commands.cmd_resize(app))
        self.menu.add_command(label="Reset", command=lambda: commands.cmd_reset(app))
        self.menu.add_separator()

        # Rotate submenu
        rotate_menu = tk.Menu(self.menu, tearoff=0)
        rotate_menu.add_command(label="90°", command=lambda: commands.cmd_rotate(app, 90))
        rotate_menu.add_command(label="180°", command=lambda: commands.cmd_rotate(app, 180))
        rotate_menu.add_command(label="270°", command=lambda: commands.cmd_rotate(app, 270))
        self.menu.add_cascade(label="Rotate", menu=rotate_menu)

        self.menu.add_command(
            label="Flip Horizontal", command=lambda: commands.cmd_flip_horizontal(app)
        )
        self.menu.add_command(
            label="Flip Vertical", command=lambda: commands.cmd_flip_vertical(app)
        )
        self.menu.add_separator()

        self.menu.add_command(label="Grab", command=lambda: commands.cmd_grab(app))
        self.menu.add_command(label="Print", command=lambda: commands.cmd_print(app))
        self.menu.add_separator()

        self.menu.add_command(
            label="Enhancements...", command=lambda: commands.cmd_enhancement_dialog(app)
        )
        self.menu.add_command(label="About", command=lambda: commands.cmd_about(app))
        self.menu.add_separator()

        self.menu.add_command(label="Quit", command=lambda: commands.cmd_quit(app))

    def show(self, event: tk.Event) -> None:
        """Display the context menu at the cursor position."""
        self.menu.tk_popup(event.x_root, event.y_root)
