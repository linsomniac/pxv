"""Tests for the bounded undo/redo history (history.py).

AIDEV-NOTE: Pure stack semantics — no Tk, no display. Snapshots use 1x1 images
so identity (`is`) checks stay cheap and unambiguous.
"""

from __future__ import annotations

from PIL import Image

from pxv.enhancements import EnhancementParams
from pxv.history import DEFAULT_MAX_LEVELS, History, Snapshot


def _snap(tag: int) -> Snapshot:
    """A distinct snapshot tagged by a 1x1 image so identity is checkable."""
    return Snapshot(
        working_image=Image.new("RGB", (1, 1), (tag % 256, 0, 0)),
        save_rgba=None,
        params=EnhancementParams(),
    )


def test_new_history_has_nothing_to_undo_or_redo() -> None:
    h = History()
    assert h.can_undo is False
    assert h.can_redo is False


def test_default_max_levels() -> None:
    assert DEFAULT_MAX_LEVELS == 20
    assert History().max_levels == 20


def test_undo_on_empty_returns_none() -> None:
    assert History().undo(_snap(1)) is None


def test_redo_on_empty_returns_none() -> None:
    assert History().redo(_snap(1)) is None


def test_record_then_undo_returns_recorded_snapshot() -> None:
    h = History()
    s0 = _snap(0)
    h.record(s0)
    assert h.can_undo is True
    assert h.undo(_snap(1)) is s0
    assert h.can_undo is False
    assert h.can_redo is True


def test_undo_then_redo_round_trips_the_current_state() -> None:
    h = History()
    h.record(_snap(0))
    current = _snap(1)
    h.undo(current)  # returns s0; `current` goes onto the redo stack
    assert h.redo(_snap(2)) is current
    assert h.can_redo is False
    assert h.can_undo is True


def test_record_clears_the_redo_branch() -> None:
    h = History()
    h.record(_snap(0))
    h.undo(_snap(1))
    assert h.can_redo is True
    h.record(_snap(2))  # a fresh edit must invalidate any redo branch
    assert h.can_redo is False


def test_clear_empties_both_stacks() -> None:
    h = History()
    h.record(_snap(0))
    h.undo(_snap(1))
    h.clear()
    assert h.can_undo is False
    assert h.can_redo is False


def test_bound_drops_oldest_undo_entry() -> None:
    h = History(max_levels=3)
    for i in range(4):  # record 4 with a bound of 3
        h.record(_snap(i))
    assert h.undo(_snap(90)) is not None
    assert h.undo(_snap(91)) is not None
    assert h.undo(_snap(92)) is not None
    assert h.undo(_snap(93)) is None  # the oldest of the 4 was dropped
