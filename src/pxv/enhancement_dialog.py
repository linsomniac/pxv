"""Enhancement dialog — separate Toplevel window with sliders and live preview.

AIDEV-NOTE: Slider changes are debounced at 30ms via after() to prevent
excessive redraws while dragging. The guard flag _updating_sliders prevents
feedback loops when programmatically setting slider values (e.g., on Reset).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING, cast

from pxv.curve_editor import CurveEditor
from pxv.enhancements import COLOR_SLIDER_SPECS, SLIDER_SPECS
from pxv.histogram_panel import HistogramPanel, compute_histograms
from pxv.levels_tab import LevelsTab

if TYPE_CHECKING:
    from PIL import Image

    from pxv.app import PxvApp
    from pxv.tone import CurvePoints, LevelsChannel


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

        # Cache of (working_image object, (lum, rgb)) for the Levels strip.
        self._input_hist_cache: tuple[object, tuple[list[int], list[int]]] | None = None

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

        # Histogram stays visible above whichever tab is active.
        self.histogram_panel = HistogramPanel(main_frame)
        self.histogram_panel.pack(fill=tk.X, pady=(0, 6))

        # AIDEV-NOTE: Tabbed layout per the 2026-06-10 histogram/levels/curves
        # design — Sliders, Levels, and Curves tabs; eyedroppers/Compare arrive in Phase 4.
        self._notebook = ttk.Notebook(main_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        sliders_tab = ttk.Frame(self._notebook, padding=6)
        self._notebook.add(sliders_tab, text="Sliders")

        core_frame = ttk.LabelFrame(sliders_tab, text="Core Adjustments", padding=6)
        core_frame.pack(fill=tk.X, pady=(0, 6))
        self._add_sliders(core_frame, SLIDER_SPECS)

        color_frame = ttk.LabelFrame(sliders_tab, text="Color", padding=6)
        color_frame.pack(fill=tk.X)
        self._add_sliders(color_frame, COLOR_SLIDER_SPECS)

        self.levels_tab = LevelsTab(
            self._notebook,
            get_levels=self._get_levels,
            set_levels=self._set_levels,
            get_input_histograms=self._input_histograms,
            on_change=self._schedule_refresh,
            request_pick=self._request_pick,
        )
        self._notebook.add(self.levels_tab, text="Levels")

        self.curve_editor = CurveEditor(
            self._notebook,
            get_curve=self._get_curve,
            set_curve=self._set_curve,
            get_input_histograms=self._input_histograms,
            on_change=self._schedule_refresh,
        )
        self._notebook.add(self.curve_editor, text="Curves")
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
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
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Debounce the display refresh (shared by sliders and levels edits)."""
        if self._refresh_after_id is not None:
            self.after_cancel(self._refresh_after_id)
        self._refresh_after_id = self.after(30, self._do_refresh)

    def _do_refresh(self) -> None:
        self._refresh_after_id = None
        self.app.refresh_display()

    def _on_apply(self) -> None:
        """Bake current enhancements into the working image, then reset sliders.

        AIDEV-NOTE: This is the xv "Apply" behavior — enhancements become permanent
        part of the working image, and sliders return to identity defaults. The
        pre-bake state (pixels + the to-be-baked slider values) is recorded for
        undo first; nothing is recorded or baked when the sliders are at identity.
        """
        if self.app.image_model.working_image is None:
            return
        if self.app.enhancement_params.is_identity():
            return
        self.app.record_history()
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
        # AIDEV-NOTE: Cancel any in-flight debounce timer before teardown so it
        # can't fire a stray refresh after the dialog is gone.
        if self._refresh_after_id is not None:
            self.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        self.app.enhancement_dialog = None
        self.destroy()
        # AIDEV-NOTE: Reclaim keyboard focus for the main window AFTER teardown —
        # same non-modal-transient focus bug as InfoDialog (see
        # PxvApp.restore_main_focus). destroy() clears the input focus this dialog
        # held, so the reclaim must follow it or the app appears locked up.
        self.app.restore_main_focus()

    def sync_sliders_from_params(self) -> None:
        """Sync all tabs' controls from the current EnhancementParams.

        Uses the guard flag to prevent triggering slider change callbacks.
        """
        self._updating_sliders = True
        params = self.app.enhancement_params
        for attr, var in self._slider_vars.items():
            val = getattr(params, attr)
            var.set(val)
        self._updating_sliders = False
        self.levels_tab.sync_from_params()
        self.curve_editor.sync_from_params()

    def update_histogram(self, img: Image.Image | None) -> None:
        """Feed the latest preview image to the histogram panel (None blanks it)."""
        self.histogram_panel.update_from_image(img)
        # AIDEV-NOTE: Geometry ops (crop/rotate/flip/resize) replace
        # working_image and refresh the display while the Levels tab may be
        # frontmost — resync its strip and the curve editor's backdrop, but only
        # when the input image actually changed, so marker-drag refreshes don't
        # redraw the strip every 30ms.
        cached = self._input_hist_cache
        current = self.app.image_model.working_image
        if current is not None and (cached is None or cached[0] is not current):
            self.levels_tab.sync_from_params()
            self.curve_editor.sync_from_params()

    _LEVELS_ATTRS = {
        "master": "levels_master",
        "r": "levels_r",
        "g": "levels_g",
        "b": "levels_b",
    }

    def _get_levels(self, key: str) -> LevelsChannel:
        return cast("LevelsChannel", getattr(self.app.enhancement_params, self._LEVELS_ATTRS[key]))

    def _set_levels(self, key: str, value: LevelsChannel) -> None:
        setattr(self.app.enhancement_params, self._LEVELS_ATTRS[key], value)

    _CURVE_ATTRS = {
        "master": "curve_master",
        "r": "curve_r",
        "g": "curve_g",
        "b": "curve_b",
    }

    def _get_curve(self, key: str) -> CurvePoints:
        return cast("CurvePoints", getattr(self.app.enhancement_params, self._CURVE_ATTRS[key]))

    def _set_curve(self, key: str, value: CurvePoints) -> None:
        setattr(self.app.enhancement_params, self._CURVE_ATTRS[key], value)

    def _request_pick(
        self, on_sample: Callable[[tuple[int, int, int] | None], None]
    ) -> Callable[[], None]:
        """Arm a one-shot eyedropper pick on the main canvas; returns a cancel.

        AIDEV-NOTE: Samples the WORKING image (input side), consistent with the
        Levels strip — see the spec's eyedropper-approximation note. No image
        means an immediate None delivery.
        """
        img = self.app.image_model.working_image
        if img is None:
            on_sample(None)
            return lambda: None

        def deliver(coords: tuple[int, int] | None) -> None:
            if coords is None:
                on_sample(None)
                return
            pixel = img.getpixel(coords)
            on_sample((int(pixel[0]), int(pixel[1]), int(pixel[2])))  # type: ignore[index]

        self.app.canvas_view.set_pick_callback(deliver, img.size)

        def cancel() -> None:
            self.app.canvas_view.set_pick_callback(None, None)
            on_sample(None)

        return cancel

    def _input_histograms(self) -> tuple[list[int], list[int]] | None:
        """Histograms of the working image (input side of the pipeline), cached.

        AIDEV-NOTE: Levels markers operate on INPUT values, so the strip shows
        the pre-enhancement working image, not the live preview (which would
        feed back while dragging). The cache keys on the working_image object
        identity — every mutation (crop/rotate/Apply/undo) replaces the object.
        """
        img = self.app.image_model.working_image
        if img is None:
            return None
        if self._input_hist_cache is None or self._input_hist_cache[0] is not img:
            self._input_hist_cache = (img, compute_histograms(img))
        return self._input_hist_cache[1]

    def _on_tab_changed(self, _event: tk.Event) -> None:
        """Resync the newly shown tone tab (the image may have changed since)."""
        selected = self._notebook.select()  # type: ignore[no-untyped-call]
        if selected == str(self.levels_tab):
            self.levels_tab.sync_from_params()
        elif selected == str(self.curve_editor):
            self.curve_editor.sync_from_params()
