"""Curve editor widget: canvas spline editor with histogram backdrop.

AIDEV-NOTE: Pure math (curve_lut, equalize_curve) lives in tone.py; this is
only the Tk shell, decoupled via injected callbacks like LevelsTab. Canvas
coords map 1:1 to values (256x256 canvas): px = x, py = 255 - y.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import ImageTk

from pxv.histogram_panel import render_histogram
from pxv.tone import IDENTITY_CURVE, CurvePoints, curve_lut, equalize_curve

CURVE_SIZE = (256, 256)
MAX_POINTS = 16
HIT_RADIUS = 6
CHANNEL_KEYS = [("master", "RGB"), ("r", "R"), ("g", "G"), ("b", "B")]
_HIST_CHANNEL = {"master": "lum", "r": "r", "g": "g", "b": "b"}


class CurveEditor(ttk.Frame):
    """Spline curve editor: click adds, drag moves, right-click deletes."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_curve: Callable[[str], CurvePoints],
        set_curve: Callable[[str, CurvePoints], None],
        get_input_histograms: Callable[[], tuple[list[int], list[int]] | None],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=6)
        self._get_curve = get_curve
        self._set_curve = set_curve
        self._get_input_histograms = get_input_histograms
        self._on_change = on_change

        self._channel = tk.StringVar(value="master")
        self._drag_idx: int | None = None
        self._hist_photo: ImageTk.PhotoImage | None = None

        chan_row = ttk.Frame(self)
        chan_row.pack(fill=tk.X)
        for key, label in CHANNEL_KEYS:
            ttk.Radiobutton(
                chan_row,
                text=label,
                value=key,
                variable=self._channel,
                command=self.sync_from_params,
            ).pack(side=tk.LEFT)

        w, h = CURVE_SIZE
        self._canvas = tk.Canvas(self, width=w, height=h, bg="#181818", highlightthickness=0)
        self._canvas.pack(pady=(4, 0))
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Button-3>", self._on_right_click)
        # AIDEV-NOTE: Right-click is Button-3 on Linux/Windows, Button-2 on
        # macOS Aqua Tk — bind both, same convention as canvas_view.py.
        self._canvas.bind("<Button-2>", self._on_right_click)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text="Equalize", command=self._on_equalize).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Invert", command=self._on_invert).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Reset Curve", command=self._on_reset_curve).pack(
            side=tk.LEFT, padx=2
        )

        self.sync_from_params()

    # --- state plumbing ---

    def _points(self) -> list[tuple[int, int]]:
        return list(self._get_curve(self._channel.get()))

    def _put(self, points: list[tuple[int, int]]) -> None:
        self._set_curve(self._channel.get(), tuple(points))
        self._on_change()
        self._redraw()

    def sync_from_params(self) -> None:
        """Redraw backdrop and curve from the current channel (switch/undo/Apply)."""
        self._drag_idx = None  # undo/external resync mid-drag: stale idx would IndexError
        self._redraw_backdrop()
        self._redraw()

    # --- drawing ---

    def _redraw_backdrop(self) -> None:
        self._hist_photo = None
        hists = self._get_input_histograms()
        if hists is None:
            return
        lum, rgb = hists
        key = _HIST_CHANNEL[self._channel.get()]
        rendered = render_histogram(lum, rgb, {key}, log_scale=False, size=CURVE_SIZE)
        self._hist_photo = ImageTk.PhotoImage(rendered)
        self._redraw()

    def _redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        if self._hist_photo is not None:
            c.create_image(0, 0, anchor=tk.NW, image=self._hist_photo)
        for q in (64, 128, 192):
            c.create_line(q, 0, q, 255, fill="#333333")
            c.create_line(0, q, 255, q, fill="#333333")
        points = self._points()
        lut = curve_lut(tuple(points))
        coords: list[int] = []
        for x in range(256):
            coords.extend((x, 255 - lut[x]))
        c.create_line(*coords, fill="#dddddd", width=1)
        for px, py in points:
            c.create_rectangle(
                px - 3, (255 - py) - 3, px + 3, (255 - py) + 3, fill="#ffffff", outline="#000000"
            )

    # --- interaction ---

    def _hit_index(self, x: int, y: int) -> int | None:
        """Index of the control point within HIT_RADIUS of canvas (x, y), or None."""
        points = self._points()
        best: tuple[float, int] | None = None
        for i, (px, py) in enumerate(points):
            dist = max(abs(px - x), abs((255 - py) - y))
            if dist <= HIT_RADIUS and (best is None or dist < best[0]):
                best = (dist, i)
        return None if best is None else best[1]

    def _on_press(self, event: object) -> None:
        x = min(255, max(0, int(getattr(event, "x", 0))))
        y = min(255, max(0, int(getattr(event, "y", 0))))
        idx = self._hit_index(x, y)
        if idx is None:
            points = self._points()
            if len(points) >= MAX_POINTS or any(abs(px - x) <= 2 for px, _py in points):
                return
            points.append((x, 255 - y))
            points.sort()
            idx = points.index((x, 255 - y))
            self._drag_idx = idx
            self._put(points)
        else:
            self._drag_idx = idx

    def _on_drag(self, event: object) -> None:
        if self._drag_idx is None:
            return
        points = self._points()
        i = self._drag_idx
        x = min(255, max(0, int(getattr(event, "x", 0))))
        y = min(255, max(0, int(getattr(event, "y", 0))))
        if i == 0:
            new_x = 0  # endpoints: x pinned, y free
        elif i == len(points) - 1:
            new_x = 255
        else:
            new_x = min(points[i + 1][0] - 1, max(points[i - 1][0] + 1, x))
        points[i] = (new_x, 255 - y)
        self._put(points)

    def _on_release(self, _event: object) -> None:
        self._drag_idx = None

    def _on_right_click(self, event: object) -> None:
        x = int(getattr(event, "x", 0))
        y = int(getattr(event, "y", 0))
        idx = self._hit_index(x, y)
        points = self._points()
        if idx is None or idx == 0 or idx == len(points) - 1:
            return
        del points[idx]
        self._put(points)

    # --- buttons ---

    def _on_equalize(self) -> None:
        """Set the MASTER curve from the input luminance CDF (editable afterward)."""
        hists = self._get_input_histograms()
        if hists is None:
            return
        self._set_curve("master", equalize_curve(hists[0]))
        self._channel.set("master")
        self._on_change()
        self.sync_from_params()

    def _on_invert(self) -> None:
        self._put([(0, 255), (255, 0)])

    def _on_reset_curve(self) -> None:
        self._put(list(IDENTITY_CURVE))
