"""Shared UI bits for the tone-editing tabs (Levels, Curves).

AIDEV-NOTE: Extracted in Phase 4 because LevelsTab and CurveEditor carried
byte-identical channel constants and radio-row construction.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

CHANNEL_KEYS = [("master", "RGB"), ("r", "R"), ("g", "G"), ("b", "B")]
HIST_CHANNEL = {"master": "lum", "r": "r", "g": "g", "b": "b"}


def build_channel_row(
    parent: tk.Misc, variable: tk.StringVar, command: Callable[[], None]
) -> ttk.Frame:
    """Packed row of RGB/R/G/B radiobuttons; returned so callers can add to it."""
    row = ttk.Frame(parent)
    row.pack(fill=tk.X)
    for key, label in CHANNEL_KEYS:
        ttk.Radiobutton(row, text=label, value=key, variable=variable, command=command).pack(
            side=tk.LEFT
        )
    return row
