# General Undo/Redo Stack — Design

**Date:** 2026-06-06
**Ideas:** Ideas.md #3 (general undo/redo stack, M)

## Background

Only **crop** is undoable today, and only **one level**: `crop()` stashes the prior
`working_image`/`_save_rgba` into the single slots `_pre_crop_working`/`_pre_crop_rgba`
(`image_model.py:30`), which `uncrop()` (bound to `u`) restores. Every other destructive
op — rotate, flip, resize, and enhancement **Apply** (`enhancement_dialog._on_apply`,
which bakes the live sliders into `working_image`) — is irreversible except a full
`reset()`.

This replaces the single slot with a bounded, multi-level undo/redo history and binds
`Ctrl+Z` / `Ctrl+Y`.

## Decisions (from brainstorming)

- **Snapshot scope:** a snapshot captures the **full editable document state** —
  `(working_image, save_rgba, enhancement_params)`. Capturing `enhancement_params` is
  required because Apply must be reversible *including the slider values* (below).
- **Apply is undoable, sliders included:** undoing an Apply restores the pre-bake pixels
  **and** the slider positions that were baked. Because params live in `PxvApp`, the
  history stack is **owned by the app**, not the model.
- **Reset clears history:** `reset()` returns to the original; there is nothing to
  undo/redo afterward. (Reset also resets metadata/keep-flag, which a buffer snapshot
  could not restore anyway — so a half-undoable Reset was rejected.)
- **`u` becomes general Undo:** `u` now undoes *any* op (was uncrop). New `Ctrl+Z` =
  Undo; `Ctrl+Y` and `Ctrl+Shift+Z` = Redo.
- **Zoom is a view setting, not document state:** undo/redo preserve the current zoom
  (they do not re-fit), mirroring how `cmd_rotate`/`cmd_crop` leave zoom untouched today.
- **Whole-state semantics:** since a snapshot is the entire document state, undoing a
  geometry op also rolls back any *uncommitted live slider tweaks* made after that op,
  back to that checkpoint's params. This is the coherent, predictable rule: Apply commits
  sliders; geometry undo returns you to a checkpoint exactly.

## Components

### `history.py` (new, pure — no Tk)

```python
DEFAULT_MAX_LEVELS = 20

@dataclass(frozen=True)
class Snapshot:
    """Full editable document state at one point in time."""
    working_image: Image.Image
    save_rgba: Image.Image | None
    params: EnhancementParams

class History:
    """Bounded undo/redo stacks of Snapshots."""
    def __init__(self, max_levels: int = DEFAULT_MAX_LEVELS) -> None: ...

    @property
    def can_undo(self) -> bool: ...
    @property
    def can_redo(self) -> bool: ...

    def clear(self) -> None: ...

    def record(self, snapshot: Snapshot) -> None:
        """Push a pre-edit snapshot onto undo, CLEAR redo, drop oldest past the bound."""

    def undo(self, current: Snapshot) -> Snapshot | None:
        """Push `current` onto redo, pop+return the top undo snapshot (None if empty)."""

    def redo(self, current: Snapshot) -> Snapshot | None:
        """Push `current` onto undo, pop+return the top redo snapshot (None if empty)."""
```

`record`/`undo`/`redo` follow the standard editor model: a new edit invalidates the redo
branch; undo and redo move the "current" state between the two stacks. The bound is
enforced by dropping the **oldest** undo entry (`_undo.pop(0)`) once `len > max_levels`.

AIDEV-NOTE worth carrying into the code: each `Snapshot` holds full-resolution image
copies (doubled for transparent images that also carry `save_rgba`), so `max_levels`
directly bounds peak memory. `20` is generous for pxv's screen-sized images; the constant
is the single tuning knob.

### `image_model.py` — changes

- **Remove** `_pre_crop_working`, `_pre_crop_rgba` (from `__init__`), the slot-saving
  lines in `crop()`, and the `uncrop()` method. `crop()` becomes a pure mutator; update
  its docstring/AIDEV-NOTE.
- **Add** buffer snapshot/restore so the app never touches `_save_rgba` directly:

```python
def snapshot_buffers(self) -> tuple[Image.Image, Image.Image | None] | None:
    """Deep-copy (working_image, _save_rgba) for the undo stack, or None if no image."""

def restore_buffers(self, working: Image.Image, save_rgba: Image.Image | None) -> None:
    """Install buffers from a snapshot (no copy — caller owns the snapshot)."""
```

`autocrop()` still calls `crop()` internally; with recording moved to the app layer there
is no double-record.

### `PxvApp` — new state & methods

```python
self.history = History()          # in __init__
```

- `snapshot_state() -> Snapshot | None`: `model.snapshot_buffers()` + a copy of
  `enhancement_params` (`dataclasses.replace`). Returns `None` when no image is loaded.
- `record_history()`: `snap = snapshot_state(); if snap: self.history.record(snap)`.
  Called by destructive commands **before** they mutate.
- `_restore_snapshot(snap)`: `model.restore_buffers(...)`; install a fresh copy of
  `snap.params` as `self.enhancement_params`; if the enhancement dialog is open,
  `sync_sliders_from_params()`; `canvas_view.clear_selection()`; `refresh_display()`
  (zoom preserved).
- `undo()` / `redo()`: if the relevant stack is empty, flash
  `"pxv: nothing to undo"` / `"…redo"` via `show_temp_title`; otherwise capture
  `snapshot_state()` as `current`, call `history.undo(current)` / `history.redo(current)`,
  and `_restore_snapshot()` the returned snapshot.

Replacing (not mutating) `self.enhancement_params` is safe: every consumer
(`enhancement_dialog`, `get_display_image`, `get_save_image`) dereferences
`app.enhancement_params` fresh on each use — nothing caches the object.

### `commands.py` — changes

- New `cmd_undo(app)` → `app.undo()`, `cmd_redo(app)` → `app.redo()`. **Delete**
  `cmd_uncrop`.
- `cmd_crop`, `cmd_rotate`, `cmd_flip_horizontal`, `cmd_flip_vertical`, `cmd_resize`:
  call `app.record_history()` immediately before the model mutation.
- `cmd_autocrop`: capture `snap = app.snapshot_state()` first, but `app.history.record(snap)`
  **only if** `autocrop()` returns `True` (keeps the "nothing to crop" path clean — no
  no-op undo entry).
- `cmd_reset`: add `app.history.clear()`.

### `enhancement_dialog._on_apply` — changes

Record + bake only when there is something to bake:

```python
def _on_apply(self) -> None:
    if self.app.image_model.working_image is None:
        return
    if self.app.enhancement_params.is_identity():
        return                      # nothing to bake — no no-op undo entry
    self.app.record_history()       # captures pre-bake pixels + the to-be-baked params
    save_img = self.app.image_model.get_save_image(self.app.enhancement_params)
    if save_img is not None:
        self.app.image_model.working_image = save_img
    self.app.enhancement_params.reset()
    self.sync_sliders_from_params()
    self.app.refresh_display()
```

### `app.py` `_bind_keys` — changes

- `<Key-u>`: `cmd_uncrop` → `cmd_undo`.
- Add `<Control-z>` → `cmd_undo`; `<Control-y>` and `<Control-Shift-Z>` → `cmd_redo`.

### `load_current()` — change

After a successful `image_model.load(...)`, call `self.history.clear()` (a freshly loaded
image starts with empty history).

### `dialogs.py` `KEYBINDINGS` — changes

- Replace `("u", "Uncrop (undo last crop)")` with `("u / Ctrl+Z", "Undo")`.
- Add `("Ctrl+Y / Ctrl+Shift+Z", "Redo")`.

### `context_menu.py` — changes

Add an edit group at the top (uncrop was never in the menu — this is a discoverability
win):

```python
self.menu.add_command(label="Undo", command=lambda: commands.cmd_undo(app))
self.menu.add_command(label="Redo", command=lambda: commands.cmd_redo(app))
self.menu.add_separator()
```

## Edge cases

- **No image loaded:** `snapshot_state()` returns `None`; `record_history()` is a no-op;
  `undo`/`redo` flash the empty message.
- **Autocrop / Apply no-ops:** never push a snapshot, so undo never appears to "do
  nothing."
- **Bound reached:** oldest undo entry is dropped; redo is unaffected until the next
  `record`.
- **Reset / load:** both clear the full history.
- **Window resize on undo:** undoing a crop/resize changes image dimensions;
  `refresh_display()` resizes the window to match, exactly as the original op did.

## Testing

Mirrors the suite's split: pure logic is display-free; Tk wiring is `DISPLAY`-gated.

- **`tests/test_history.py`** (new, pure): `record` clears redo; bound drops the oldest;
  `undo`/`redo` move the current state across stacks and return `None` when empty;
  `can_undo`/`can_redo`; `clear`.
- **`tests/test_image_model.py`**: add a `snapshot_buffers`/`restore_buffers` round-trip
  (incl. the `save_rgba is None` opaque case and that snapshots are independent copies);
  **replace** `test_crop_then_uncrop_restores_one_level` and the uncrop half of
  `test_crop_applies_to_save_rgba` (keep the crop-applies-to-`save_rgba` assertion).
- **DISPLAY-gated app test** (new, pattern from `test_dialog_focus.py`): rotate→undo→redo
  round-trips `working_image`; Apply→undo restores both pixels and slider values;
  `reset()` clears history (`can_undo`/`can_redo` both `False`).

## Out of scope

- Persisting history across image navigation (each image starts fresh).
- Coalescing rapid identical ops, or delta/tile-based snapshots (full copies, bounded).
- Undoing metadata / keep-flag changes (outside the buffer-and-params snapshot).
