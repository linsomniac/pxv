"""Levels tab widget: histogram strip with draggable black/gamma/white markers.

AIDEV-NOTE: Pure math (levels_lut, gamma_to_mid/mid_to_gamma, auto_levels)
lives in tone.py; this module is only the Tk shell, decoupled from the app via
callbacks the dialog injects (get_levels/set_levels/get_input_histograms/
on_change) — same pattern as HistogramPanel. Marker x-coordinates equal input
values directly because the strip is exactly 256px wide.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from pxv.histogram_panel import render_histogram
from pxv.tone import LevelsChannel, auto_levels, gamma_to_mid, gray_balance_gammas, mid_to_gamma
from pxv.tone_ui import HIST_CHANNEL, build_channel_row

STRIP_SIZE = (256, 80)
MARKER_H = 14


class LevelsTab(ttk.Frame):
    """Channel levels editor: input markers, output range, spinboxes, Auto."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_levels: Callable[[str], LevelsChannel],
        set_levels: Callable[[str, LevelsChannel], None],
        get_input_histograms: Callable[[], tuple[list[int], list[int]] | None],
        on_change: Callable[[], None],
        request_pick: Callable[[Callable[[tuple[int, int, int] | None], None]], Callable[[], None]]
        | None = None,
    ) -> None:
        super().__init__(parent, padding=6)
        self._get_levels = get_levels
        self._set_levels = set_levels
        self._get_input_histograms = get_input_histograms
        self._on_change = on_change
        self._request_pick = request_pick
        self._pick_cancel: Callable[[], None] | None = None
        self._pick_kind: str | None = None

        self._channel = tk.StringVar(value="master")
        self._updating = False  # guard: programmatic spinbox writes
        self._drag: str | None = None
        self._hist_photo: ImageTk.PhotoImage | None = None
        self._grad_photo: ImageTk.PhotoImage | None = None

        chan_row = build_channel_row(self, self._channel, self.sync_from_params)
        ttk.Button(chan_row, text="Auto", width=6, command=self._on_auto).pack(side=tk.RIGHT)

        w, h = STRIP_SIZE
        self._hist_canvas = tk.Canvas(self, width=w, height=h, bg="#181818", highlightthickness=0)
        self._hist_canvas.pack(pady=(4, 0))

        self._in_canvas = tk.Canvas(self, width=w, height=MARKER_H, highlightthickness=0)
        self._in_canvas.pack()
        self._in_canvas.bind("<Button-1>", self._on_in_press)
        self._in_canvas.bind("<B1-Motion>", self._on_in_drag)
        self._in_canvas.bind("<ButtonRelease-1>", self._on_release)

        self._out_canvas = tk.Canvas(self, width=w, height=MARKER_H + 8, highlightthickness=0)
        self._out_canvas.pack(pady=(6, 0))
        self._out_canvas.bind("<Button-1>", self._on_out_press)
        self._out_canvas.bind("<B1-Motion>", self._on_out_drag)
        self._out_canvas.bind("<ButtonRelease-1>", self._on_release)

        spin_row = ttk.Frame(self)
        spin_row.pack(fill=tk.X, pady=(6, 0))
        self._spins: dict[str, tk.Spinbox] = {}
        for field, label, lo, hi, inc in (
            ("in_black", "Black", 0.0, 254.0, 1.0),
            ("gamma", "Gamma", 0.1, 10.0, 0.1),
            ("in_white", "White", 1.0, 255.0, 1.0),
            ("out_black", "Out lo", 0.0, 255.0, 1.0),
            ("out_white", "Out hi", 0.0, 255.0, 1.0),
        ):
            ttk.Label(spin_row, text=label).pack(side=tk.LEFT, padx=(0, 2))
            spin = tk.Spinbox(
                spin_row, from_=lo, to=hi, increment=inc, width=5, command=self._on_spin_change
            )
            spin.bind("<Return>", lambda _e: self._on_spin_change())
            spin.bind("<FocusOut>", lambda _e: self._on_spin_change())
            spin.pack(side=tk.LEFT, padx=(0, 6))
            self._spins[field] = spin

        pick_row = ttk.Frame(self)
        pick_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(pick_row, text="Pick:").pack(side=tk.LEFT, padx=(0, 4))
        for kind, label in (("black", "Black"), ("gray", "Gray"), ("white", "White")):
            ttk.Button(
                pick_row,
                text=label,
                width=6,
                command=lambda k=kind: self._on_eyedropper(k),  # type: ignore[misc]
            ).pack(side=tk.LEFT, padx=2)

        self.sync_from_params()

    # --- state plumbing ---

    def _levels(self) -> LevelsChannel:
        return self._get_levels(self._channel.get())

    def _put(self, **changes: Any) -> None:
        """Replace the current channel's LevelsChannel and propagate everywhere."""
        new = replace(self._levels(), **changes)
        self._set_levels(self._channel.get(), new)
        self._on_change()
        self._redraw(new)
        self._sync_spins(new)

    def sync_from_params(self) -> None:
        """Redraw everything from the current channel (channel switch, undo, Apply)."""
        ch = self._levels()
        self._redraw_histogram()
        self._redraw(ch)
        self._sync_spins(ch)

    # --- drawing ---

    def _redraw_histogram(self) -> None:
        self._hist_canvas.delete("all")
        self._hist_photo = None
        hists = self._get_input_histograms()
        if hists is None:
            return
        lum, rgb = hists
        key = HIST_CHANNEL[self._channel.get()]
        rendered = render_histogram(lum, rgb, {key}, log_scale=False, size=STRIP_SIZE)
        self._hist_photo = ImageTk.PhotoImage(rendered)
        self._hist_canvas.create_image(0, 0, anchor=tk.NW, image=self._hist_photo)

    def _redraw(self, ch: LevelsChannel) -> None:
        c = self._in_canvas
        c.delete("all")
        for x, fill in (
            (float(ch.in_black), "#000000"),
            (gamma_to_mid(ch.in_black, ch.in_white, ch.gamma), "#888888"),
            (float(ch.in_white), "#ffffff"),
        ):
            c.create_polygon(
                x - 5, MARKER_H - 1, x + 5, MARKER_H - 1, x, 1, fill=fill, outline="#444444"
            )
        o = self._out_canvas
        o.delete("all")
        if self._grad_photo is None:
            grad = Image.new("L", (256, 8))
            grad.putdata(list(range(256)) * 8)
            self._grad_photo = ImageTk.PhotoImage(grad.convert("RGB"))
        o.create_image(0, 0, anchor=tk.NW, image=self._grad_photo)
        for x, fill in ((float(ch.out_black), "#000000"), (float(ch.out_white), "#ffffff")):
            o.create_polygon(
                x - 5, MARKER_H + 7, x + 5, MARKER_H + 7, x, 9, fill=fill, outline="#444444"
            )

    # --- input marker interaction ---

    def _on_in_press(self, event: object) -> None:
        ch = self._levels()
        mid_x = gamma_to_mid(ch.in_black, ch.in_white, ch.gamma)
        candidates = {"black": float(ch.in_black), "mid": mid_x, "white": float(ch.in_white)}
        x = getattr(event, "x", 0)
        self._drag = min(candidates, key=lambda k: abs(candidates[k] - x))
        self._on_in_drag(event)

    def _on_in_drag(self, event: object) -> None:
        if self._drag is None:
            return
        ch = self._levels()
        x = min(255, max(0, int(getattr(event, "x", 0))))
        if self._drag == "black":
            self._put(in_black=min(x, ch.in_white - 1))
        elif self._drag == "white":
            self._put(in_white=max(x, ch.in_black + 1))
        elif self._drag == "mid":
            self._put(gamma=round(mid_to_gamma(ch.in_black, ch.in_white, x), 2))

    def _on_out_press(self, event: object) -> None:
        ch = self._levels()
        candidates = {"out_black": float(ch.out_black), "out_white": float(ch.out_white)}
        x = getattr(event, "x", 0)
        self._drag = min(candidates, key=lambda k: abs(candidates[k] - x))
        self._on_out_drag(event)

    def _on_out_drag(self, event: object) -> None:
        if self._drag is None:
            return
        ch = self._levels()
        x = min(255, max(0, int(getattr(event, "x", 0))))
        if self._drag == "out_black":
            self._put(out_black=min(x, ch.out_white))
        elif self._drag == "out_white":
            self._put(out_white=max(x, ch.out_black))

    def _on_release(self, _event: object) -> None:
        self._drag = None

    # --- spinboxes / auto ---

    def _sync_spins(self, ch: LevelsChannel) -> None:
        self._updating = True
        for field in ("in_black", "gamma", "in_white", "out_black", "out_white"):
            spin = self._spins[field]
            spin.delete(0, tk.END)
            val = getattr(ch, field)
            spin.insert(0, f"{val:.2f}" if field == "gamma" else str(val))
        self._updating = False

    def _on_spin_change(self) -> None:
        if self._updating:
            return
        try:
            in_black = int(float(self._spins["in_black"].get()))
            gamma = float(self._spins["gamma"].get())
            in_white = int(float(self._spins["in_white"].get()))
            out_black = int(float(self._spins["out_black"].get()))
            out_white = int(float(self._spins["out_white"].get()))
        except (ValueError, tk.TclError):
            return  # ignore partial/invalid input; the next valid edit wins
        in_black = min(254, max(0, in_black))
        in_white = min(255, max(in_black + 1, in_white))
        gamma = min(10.0, max(0.1, gamma))
        # AIDEV-NOTE: Spinboxes deliberately allow out_black > out_white
        # (output inversion / negative effect — levels_lut supports it);
        # marker DRAGS clamp no-cross because accidental inversion while
        # dragging feels broken. Intentional asymmetry.
        out_black = min(255, max(0, out_black))
        out_white = min(255, max(0, out_white))
        self._put(
            in_black=in_black,
            gamma=gamma,
            in_white=in_white,
            out_black=out_black,
            out_white=out_white,
        )

    def _on_auto(self) -> None:
        """Auto-levels: per-channel black/white from the input histogram."""
        hists = self._get_input_histograms()
        if hists is None:
            return
        r, g, b = auto_levels(hists[1])
        for key, ch in (("r", r), ("g", g), ("b", b)):
            current = self._get_levels(key)
            self._set_levels(key, replace(current, in_black=ch.in_black, in_white=ch.in_white))
        self._on_change()
        self.sync_from_params()

    def _on_eyedropper(self, kind: str) -> None:
        """Arm a one-shot pick on the main canvas; second press cancels.

        AIDEV-NOTE: No root <Escape> cancel binding on purpose — tkinter's
        unbind(seq, funcid) removes ALL bindings for the sequence (bpo-31485),
        so a temporary bind would clobber future root Escape bindings.
        Cancel paths: press the same button again, press another eyedropper
        (re-arms), or click outside the image (delivers None).
        """
        if self._request_pick is None:
            return
        if self._pick_cancel is not None:
            cancel, armed = self._pick_cancel, self._pick_kind
            self._pick_cancel = None
            self._pick_kind = None
            cancel()
            if armed == kind:
                return  # second press on the same button = plain cancel

        def on_sample(sample: tuple[int, int, int] | None) -> None:
            self._pick_cancel = None
            self._pick_kind = None
            self._apply_pick(kind, sample)

        self._pick_cancel = self._request_pick(on_sample)
        self._pick_kind = kind

    def _apply_pick(self, kind: str, sample: tuple[int, int, int] | None) -> None:
        """Apply a sampled pixel to per-channel levels (black/white/gray)."""
        if sample is None:
            return
        if kind == "gray":
            for key, gamma in zip(("r", "g", "b"), gray_balance_gammas(sample)):
                self._set_levels(key, replace(self._get_levels(key), gamma=gamma))
        else:
            for key, value in zip(("r", "g", "b"), sample):
                ch = self._get_levels(key)
                if kind == "black":
                    ch = replace(ch, in_black=min(value, ch.in_white - 1))
                else:
                    ch = replace(ch, in_white=max(value, ch.in_black + 1))
                self._set_levels(key, ch)
        self._on_change()
        self.sync_from_params()
