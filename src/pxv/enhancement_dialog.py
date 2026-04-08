"""Enhancement dialog — separate Toplevel window with sliders and live preview.

AIDEV-NOTE: Slider changes are debounced at 30ms via after() to prevent
excessive redraws while dragging. The guard flag _updating_sliders prevents
feedback loops when programmatically setting slider values (e.g., on Reset).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from collections.abc import Callable
from typing import TYPE_CHECKING

from pxv.enhancements import COLOR_SLIDER_SPECS, SLIDER_SPECS

if TYPE_CHECKING:
    from pxv.app import PxvApp


class EnhancementDialog(tk.Toplevel):
    """Enhancement sliders with debounced live preview."""

    def __init__(self, app: PxvApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Enhancements")
        self.resizable(False, False)
        self.transient(app.root)

        self._updating_sliders = False
        self._refresh_after_id: str | None = None

        # Maps attribute name -> (tk variable, scale widget)
        self._slider_vars: dict[str, tk.DoubleVar | tk.IntVar] = {}
        self._scales: dict[str, tk.Scale] = {}

        self._build_ui()
        self.sync_sliders_from_params()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Position near parent
        self.update_idletasks()
        px = app.root.winfo_x() + app.root.winfo_width() + 10
        py = app.root.winfo_y()
        self.geometry(f"+{px}+{py}")

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Core adjustments section
        core_frame = ttk.LabelFrame(main_frame, text="Core Adjustments", padding=6)
        core_frame.pack(fill=tk.X, pady=(0, 6))
        self._add_sliders(core_frame, SLIDER_SPECS)

        # Color section
        color_frame = ttk.LabelFrame(main_frame, text="Color", padding=6)
        color_frame.pack(fill=tk.X, pady=(0, 6))
        self._add_sliders(color_frame, COLOR_SLIDER_SPECS)

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_frame, text="Apply", command=self._on_apply, width=8).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Reset", command=self._on_reset, width=8).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Close", command=self._on_close, width=8).pack(
            side=tk.LEFT, padx=4
        )

    def _add_sliders(
        self,
        parent: ttk.LabelFrame,
        specs: list[tuple[str, str, float, float, float, float, bool]],
    ) -> None:
        for row_idx, (attr, label, from_, to, _default, resolution, is_int) in enumerate(specs):
            ttk.Label(parent, text=f"{label}:", width=10, anchor=tk.E).grid(
                row=row_idx, column=0, sticky=tk.E, padx=(0, 4)
            )

            if is_int:
                var: tk.DoubleVar | tk.IntVar = tk.IntVar()
            else:
                var = tk.DoubleVar()

            scale = tk.Scale(
                parent,
                from_=from_,
                to=to,
                resolution=resolution,
                orient=tk.HORIZONTAL,
                length=200,
                variable=var,
                showvalue=True,
                command=self._make_slider_callback(attr),
            )
            scale.grid(row=row_idx, column=1, sticky=tk.EW, padx=2)

            self._slider_vars[attr] = var
            self._scales[attr] = scale

    def _make_slider_callback(self, attr: str) -> Callable[[str], None]:
        """Create a callback for a specific slider attribute."""

        def callback(_val: str) -> None:
            self._on_slider_change(attr)

        return callback

    def _on_slider_change(self, attr: str) -> None:
        """Called when any slider moves. Debounces the display refresh."""
        if self._updating_sliders:
            return

        # Update the corresponding param
        val = self._slider_vars[attr].get()
        setattr(self.app.enhancement_params, attr, val)

        # Debounce refresh
        if self._refresh_after_id is not None:
            self.after_cancel(self._refresh_after_id)
        self._refresh_after_id = self.after(30, self._do_refresh)

    def _do_refresh(self) -> None:
        self._refresh_after_id = None
        self.app.refresh_display()

    def _on_apply(self) -> None:
        """Bake current enhancements into the working image, then reset sliders.

        AIDEV-NOTE: This is the xv "Apply" behavior — enhancements become permanent
        part of the working image, and sliders return to identity defaults.
        """
        save_img = self.app.image_model.get_save_image(self.app.enhancement_params)
        if save_img is not None:
            self.app.image_model.working_image = save_img
        self.app.enhancement_params.reset()
        self.sync_sliders_from_params()
        self.app.refresh_display()

    def _on_reset(self) -> None:
        """Reset all sliders to defaults without baking."""
        self.app.enhancement_params.reset()
        self.sync_sliders_from_params()
        self.app.refresh_display()

    def _on_close(self) -> None:
        self.app.enhancement_dialog = None
        self.destroy()

    def sync_sliders_from_params(self) -> None:
        """Set all slider values from the current EnhancementParams.

        Uses the guard flag to prevent triggering slider change callbacks.
        """
        self._updating_sliders = True
        params = self.app.enhancement_params
        for attr, var in self._slider_vars.items():
            val = getattr(params, attr)
            var.set(val)
        self._updating_sliders = False
