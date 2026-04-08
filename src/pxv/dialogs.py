"""Resize dialog and About dialog for pxv."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def resize_dialog(parent: tk.Tk, current_size: tuple[int, int]) -> tuple[int, int] | None:
    """Modal dialog to enter a new width/height. Returns new size or None if cancelled."""
    cur_w, cur_h = current_size
    result: tuple[int, int] | None = None

    dialog = tk.Toplevel(parent)
    dialog.title("Resize Image")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    # Variables
    width_var = tk.IntVar(value=cur_w)
    height_var = tk.IntVar(value=cur_h)
    constrain_var = tk.BooleanVar(value=True)
    aspect_ratio = cur_w / cur_h if cur_h != 0 else 1.0

    _updating = False

    def on_width_change(*_args: object) -> None:
        nonlocal _updating
        if _updating or not constrain_var.get():
            return
        _updating = True
        try:
            w = width_var.get()
            height_var.set(max(1, int(w / aspect_ratio + 0.5)))
        except (tk.TclError, ValueError):
            pass
        _updating = False

    def on_height_change(*_args: object) -> None:
        nonlocal _updating
        if _updating or not constrain_var.get():
            return
        _updating = True
        try:
            h = height_var.get()
            width_var.set(max(1, int(h * aspect_ratio + 0.5)))
        except (tk.TclError, ValueError):
            pass
        _updating = False

    def on_ok() -> None:
        nonlocal result
        try:
            w = width_var.get()
            h = height_var.get()
            if w > 0 and h > 0:
                result = (w, h)
        except (tk.TclError, ValueError):
            pass
        dialog.destroy()

    def on_cancel() -> None:
        dialog.destroy()

    # Layout
    frame = ttk.Frame(dialog, padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text=f"Current size: {cur_w} x {cur_h}").grid(
        row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8)
    )

    ttk.Label(frame, text="Width:").grid(row=1, column=0, sticky=tk.E, padx=(0, 4))
    w_entry = ttk.Entry(frame, textvariable=width_var, width=8)
    w_entry.grid(row=1, column=1, sticky=tk.W)

    ttk.Label(frame, text="Height:").grid(row=2, column=0, sticky=tk.E, padx=(0, 4))
    h_entry = ttk.Entry(frame, textvariable=height_var, width=8)
    h_entry.grid(row=2, column=1, sticky=tk.W)

    ttk.Checkbutton(frame, text="Constrain proportions", variable=constrain_var).grid(
        row=3, column=0, columnspan=2, sticky=tk.W, pady=(4, 8)
    )

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=4, column=0, columnspan=2)
    ttk.Button(btn_frame, text="OK", command=on_ok, width=8).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_frame, text="Cancel", command=on_cancel, width=8).pack(side=tk.LEFT, padx=4)

    # Bind constrain-aware updates
    width_var.trace_add("write", on_width_change)
    height_var.trace_add("write", on_height_change)

    # Focus and key bindings
    w_entry.focus_set()
    w_entry.select_range(0, tk.END)
    dialog.bind("<Return>", lambda _: on_ok())
    dialog.bind("<Escape>", lambda _: on_cancel())

    # Center on parent
    dialog.update_idletasks()
    px = parent.winfo_x() + (parent.winfo_width() - dialog.winfo_width()) // 2
    py = parent.winfo_y() + (parent.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{px}+{py}")

    parent.wait_window(dialog)
    return result
