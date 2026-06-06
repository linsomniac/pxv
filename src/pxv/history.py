"""Bounded undo/redo history of full document snapshots.

AIDEV-NOTE: A Snapshot is the entire editable document state at one instant:
the working image, the optional true-RGBA save buffer, and the enhancement
params. Capturing params (not just the image buffers) is what makes an
enhancement "Apply" reversible down to the slider values. The stack lives in
PxvApp rather than ImageModel because params are app-level state.

Each Snapshot holds full-resolution image copies (doubled for transparent
images that also carry save_rgba), so max_levels directly bounds peak memory.
DEFAULT_MAX_LEVELS is the single tuning knob.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from pxv.enhancements import EnhancementParams

DEFAULT_MAX_LEVELS = 20


@dataclass(frozen=True)
class Snapshot:
    """Full editable document state at one point in time."""

    working_image: Image.Image
    save_rgba: Image.Image | None
    params: EnhancementParams


class History:
    """Bounded undo/redo stacks of Snapshots, with standard editor semantics."""

    def __init__(self, max_levels: int = DEFAULT_MAX_LEVELS) -> None:
        self.max_levels = max_levels
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        """Drop all undo and redo history (e.g. on reset or loading a new image)."""
        self._undo.clear()
        self._redo.clear()

    def record(self, snapshot: Snapshot) -> None:
        """Push a pre-edit snapshot; clear the redo branch and enforce the bound."""
        self._undo.append(snapshot)
        if len(self._undo) > self.max_levels:
            self._undo.pop(0)  # drop the oldest
        self._redo.clear()

    def undo(self, current: Snapshot) -> Snapshot | None:
        """Move `current` onto the redo stack and return the prior state, or None."""
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current: Snapshot) -> Snapshot | None:
        """Move `current` onto the undo stack and return the next state, or None."""
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()
