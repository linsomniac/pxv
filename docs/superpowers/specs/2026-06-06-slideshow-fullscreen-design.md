# Slideshow + Fullscreen — Design

**Date:** 2026-06-06
**Ideas:** Ideas.md #5 (slideshow, S) and #7 (fullscreen, S)

## Background

Navigation is manual only. xv-style presentation needs two small additions: a
timer-driven auto-advance (slideshow) and a borderless fullscreen mode with the image
centered on black. The wrap-around `FileList` and the `show_temp_title`/`after` timer
plumbing already exist; the canvas letterbox is already black (`canvas_view.py:60`).

## Decisions (from brainstorming)

- **Fullscreen key:** `f` and `F11` toggle; `Escape` also exits.
- **Slideshow key:** `s` toggles; default interval 4 s.
- **Interval control:** `--slideshow[=SECS]` at startup; `+` / `-` (and keypad
  `KP_Add`/`KP_Subtract`) adjust by 1 s at runtime, min 1 s.
- **Startup flags:** `--slideshow [SECS]` and `--fullscreen`.
- **Escape semantics:** one Escape exits slideshow and fullscreen if either is active;
  otherwise it clears the selection (existing behavior).
- Manual navigation keeps working during a slideshow and does not reset the timer.

## Components

### `slideshow.py` (new, pure — no Tk)

```python
DEFAULT_SLIDESHOW_SECONDS = 4
MIN_SLIDESHOW_SECONDS = 1

def interval_to_ms(seconds: float) -> int:
    """Clamp to >= MIN and convert seconds to whole milliseconds."""

def adjusted_interval_ms(current_ms: int, delta_seconds: float) -> int:
    """Apply a +/- seconds delta to a ms interval, clamped to >= MIN."""
```

### `PxvApp` — new state

```python
self.fullscreen: bool = False
self.slideshow_active: bool = False
self.slideshow_interval_ms: int = interval_to_ms(DEFAULT_SLIDESHOW_SECONDS)
self._slideshow_after_id: str | None = None
```

### `PxvApp` — new / changed methods

- `toggle_fullscreen()`: flips `self.fullscreen`, calls
  `root.attributes("-fullscreen", self.fullscreen)`, `update_idletasks()`, then
  `_apply_fit()` + `refresh_display()`. Wrapped so a WM that rejects the attribute
  still leaves consistent state.
- `_apply_fit()`: `bounds = _get_monitor_size(root)` when fullscreen else
  `_get_max_image_size()`; `canvas_view.zoom_fit(img_size, bounds)`. `load_current()`
  is updated to call `_apply_fit()` instead of its inline fit.
- `refresh_display()`: skip `_resize_window_to_image(...)` while `self.fullscreen`
  (the window must remain screen-sized); still calls `canvas_view.display()`.
- `toggle_slideshow()` / `start_slideshow()` / `stop_slideshow()`: manage state and the
  `after` timer. `start` schedules `_slideshow_tick`; `stop` cancels
  `_slideshow_after_id`. Toggling shows a transient title (`pxv: slideshow on (4s)` /
  `pxv: slideshow off`).
- `_slideshow_tick()`: guard `root.winfo_exists()`; `commands.cmd_next_image(self)`;
  reschedule while `self.slideshow_active`.
- `adjust_slideshow_interval(delta_s)`: update `slideshow_interval_ms` via
  `adjusted_interval_ms`; if running, cancel + reschedule; show transient title with the
  new value.
- `escape_action()`: if `slideshow_active` or `fullscreen`, stop slideshow and exit
  fullscreen; else `canvas_view.clear_selection()`.

### `commands.py` — thin wrappers

`cmd_toggle_fullscreen(app)`, `cmd_toggle_slideshow(app)`,
`cmd_slideshow_adjust(app, delta)`, `cmd_escape(app)` — each delegates to the matching
`PxvApp` method, keeping every keybinding routed through `commands.cmd_*`.

### Keybindings (`app._bind_keys`) and help table (`dialogs.KEYBINDINGS`)

| Key | Action |
|-----|--------|
| `f`, `F11` | Toggle fullscreen |
| `s` | Toggle slideshow |
| `+` / `-` (and keypad) | Slideshow interval +/- 1 s |
| `Escape` | Exit slideshow/fullscreen, else clear selection |

### CLI (`app.main`)

Extract `_build_parser() -> argparse.ArgumentParser` (testable headlessly). Add:

- `--slideshow` with `nargs="?"`, `const=DEFAULT_SLIDESHOW_SECONDS`, `type=float`,
  `metavar="SECS"`. `None` → off; a value (or bare flag) → interval + auto-start.
- `--fullscreen` with `action="store_true"`.

After the image loads: if `args.fullscreen`, enter fullscreen; if `args.slideshow is not
None`, set the interval and start the slideshow (scheduled via `after`, guarded by
`winfo_exists`).

## Error handling

- Slideshow timer guarded by `winfo_exists`; `stop_slideshow` cancels the pending
  after-id so no callback fires against a torn-down interpreter.
- Interval clamped to `MIN_SLIDESHOW_SECONDS`.
- Fullscreen toggle keeps `self.fullscreen` consistent even if the WM ignores the
  attribute.

## Testing

- `tests/test_slideshow.py` (pure, no display): `interval_to_ms` clamping + conversion;
  `adjusted_interval_ms` increment/decrement and min clamp; default constant.
- `tests/test_cli.py` (extend, headless via `_build_parser()`): `--slideshow` absent →
  `None`; bare `--slideshow` → default; `--slideshow 2` → 2.0; `--fullscreen` →
  `True`.
- Tk timer/fullscreen side-effects are verified by an Xvfb smoke check, not unit tests
  (consistent with the save-options dialog and `resize_dialog`).

## Out of scope

Pause-on-manual-nav, per-image durations, slideshow transition effects, and persisting
the interval across sessions (config-file item).
