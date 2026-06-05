# pxv EXIF Viewer / Light Editor / Wiper — Design Spec

**Date:** 2026-06-05
**Status:** Approved (design)

## Goal

pxv shows almost no image metadata — only name/size/zoom in the title bar
(`app.py:262-271`). EXIF is read at load **only** for orientation
(`ImageOps.exif_transpose`, `image_model.py:70`) and then discarded; the raw
`Image.Exif` is never stored. On save, no `exif=` argument is ever passed
(`commands.py:135`), so pxv silently strips **all** metadata.

This adds xv's classic info view (the `i` key) plus a small, deliberate metadata
editor and wiper:

- **Viewer** — an info panel showing file facts and decoded EXIF (camera,
  exposure, capture date, GPS).
- **Light editor** — edit a curated set of common string/date fields
  (Description, Artist, Copyright, Date).
- **Wiper** — strip all metadata (the default) or selectively redact location
  (Remove GPS).

## Scope

**In scope (this pass):**
- Capture image metadata at load and expose it on `ImageModel`.
- A pure-logic `metadata.py` module: decode/format EXIF, group it for display,
  sanitize it for save, and redact GPS.
- A non-modal `InfoDialog` bound to `i`, with a context-menu entry.
- Save integration so an explicit **"keep metadata on save"** writes sanitized
  EXIF; the default remains today's strip behavior.
- Unit tests for the pure logic plus a save/reload round-trip.

**Out of scope (deliberately, for later passes):**
- A full arbitrary-tag editor (edit/add/remove any EXIF tag by id).
- IPTC and XMP metadata standards.
- In-place file rewriting (all changes remain deferred to Save As, matching
  pxv's non-destructive model).
- CLI metadata flags and sidecar (`.xmp`) files.

## Decisions (from brainstorming)

- **Persistence: deferred only.** Metadata edits/wipes mutate in-memory state and
  are written only on Save As — no surprise overwrites of the open file.
  Consistent with crop/rotate/resize/enhance, which also vanish on navigate-away.
- **Save default: strip.** Today's silent-strip behavior is preserved exactly;
  the default IS the wipe. "Keep metadata on save" is an explicit opt-in, so the
  light-editor fields only reach disk when keep is checked.

## Approach

Chosen: **a pure-logic `metadata.py` module + capture in `ImageModel` + a thin
non-modal `InfoDialog`.** This mirrors the existing split between `enhancements.py`
(pure pipeline) and `enhancement_dialog.py` (Tk widget), and keeps all
decode/sanitize/redact logic unit-testable with synthetic `Image.Exif` objects —
matching the test-suite philosophy already established (`tests/conftest.py`).

Rejected:
- **Decode inline in the dialog** (stash raw EXIF, format in Tk code): faster to
  write but buries testable logic inside the widget. Conflicts with the
  pure-logic test direction.
- **Multi-standard abstraction (EXIF + IPTC + XMP, pluggable):**
  over-engineered; EXIF covers the named use cases. YAGNI.

## Data model & capture (`image_model.py`)

New `ImageModel` state:
- `self.metadata: ImageMetadata | None = None`
- `self.keep_metadata: bool = False` (default = strip)

In `load()` (`image_model.py:64-88`), capture metadata from `raw` **before**
`exif_transpose` discards it — `raw.getexif()` is reliable on the freshly-opened
image. Set `self.metadata = metadata.read_metadata(raw, path)` and reset
`keep_metadata = False`. `reset()` restores the working exif from the captured
original (clearing pending edits/redactions). Navigation reloads rebuild metadata
fresh, exactly like every other edit.

## `metadata.py` — pure logic (no Tkinter)

- `ImageMetadata` dataclass: `path`, `file_size`, `file_format`, `mode`,
  `size` (original pixel dimensions), a mutable working `Image.Exif` (`exif`),
  and an immutable copy of the originally-captured exif (for `reset()`).
- `read_metadata(raw: Image.Image, path: Path) -> ImageMetadata` — gathers file
  facts (`path.stat().st_size`, `raw.format`, `raw.mode`, `raw.size`) and
  `raw.getexif()`. The only function that touches the filesystem; kept thin.
- `decode_value(tag_id: int, value) -> str` — formats values defensively:
  rationals → `f/2.8`, `1/250 s`, `28 mm`, `+0.3 EV`; GPS IFD → decimal degrees;
  EXIF datetime strings normalized. Each tag decode is wrapped so one bad value
  can't break the panel (falls back to `repr`).
- `build_sections(meta: ImageMetadata) -> list[Section]` — groups decoded tags
  into **File / Camera / Exposure / Location / Other**, plus a full "all tags"
  list (id, name, value). Pure → unit-tested with a synthetic `Exif`.
- `build_save_exif(meta: ImageMetadata) -> Image.Exif` — clones the working exif
  and **sanitizes unconditionally** so preserved EXIF can never contradict the
  saved pixels:
  - set `Orientation` (0x0112) to `1` — orientation is already baked into the
    working pixels by `exif_transpose` at load;
  - drop the embedded thumbnail / IFD1;
  - drop stale `ExifImageWidth` (0xA002) / `ExifImageHeight` (0xA003).
- `redact_gps(exif: Image.Exif) -> None` — removes the GPS IFD (0x8825),
  leaving all other tags intact.
- Field-edit helpers for the curated set: `ImageDescription` (0x010E),
  `Artist` (0x013B), `Copyright` (0x8298), and `DateTime` (0x0132) /
  `DateTimeOriginal` (0x9003).

## UI — `src/pxv/info_dialog.py`, non-modal `InfoDialog`

Modeled on `EnhancementDialog` (non-modal `tk.Toplevel`, registered as
`app.info_dialog`, positioned beside the main window). Non-modal so navigation
(Space/arrows) still works while it is open; `app` calls `info_dialog.refresh()`
after a successful load so the panel follows the displayed image. `cmd_info`
opens-or-raises it, mirroring `cmd_enhancement_dialog` (`commands.py:332-344`).
`_on_close` clears `app.info_dialog`.

Layout (ttk `LabelFrame` sections, matching dialog conventions):

```
┌─ pxv: Image Info ──────────────────────────────┐
│ File                                           │
│   Name        IMG_4021.jpg                     │
│   Path        /home/sean/photos/IMG_4021.jpg   │
│   Size        3.4 MB  (3,581,234 bytes)        │
│   Format/Mode JPEG · RGB                        │
│   Dimensions  4032 × 3024  (working 4032×3024) │
│ Camera                                         │
│   Apple  iPhone 13 Pro · 26 mm f/1.5           │
│   Taken   2024-08-12 14:33:02                  │
│ Exposure                                       │
│   1/250 s · f/2.8 · ISO 100 · 28 mm · +0.0 EV  │
│ Location                                       │
│   37.7749, -122.4194           [ Remove GPS ]  │
│ Edit  (written only if "keep" is checked)      │
│   Description [__________________________]     │
│   Artist      [__________________________]     │
│   Copyright   [__________________________]     │
│   Date        [2024-08-12 14:33:02_______]     │
│ ▸ All tags (47)                     [ show ]   │
│ [✓] Keep metadata on save        [Strip all]   │
│                                     [ Close ]  │
└────────────────────────────────────────────────┘
```

- "All tags" expands a scrollable read-only `Treeview` (id · name · value).
- Edit fields write into the working exif as they change; the "Date" field binds
  to `DateTimeOriginal` (capture time), falling back to `DateTime` when no
  original exists. Edits only reach disk when "Keep metadata on save" is checked.
- "Remove GPS" calls `redact_gps`; "Strip all" sets `keep_metadata = False`
  (and unchecks keep). The keep checkbox is bound to `image_model.keep_metadata`.
- Empty/edit fields with no EXIF present are usable to *add* metadata.

## Integration points

- **Keybinding:** add `self.root.bind("<Key-i>", lambda _: commands.cmd_info(self))`
  in `_bind_keys` (`app.py:151`).
- **Context menu:** add an "Info" command in `ContextMenu.__init__`
  (`context_menu.py`).
- **Refresh hook:** after a successful load in `app.load_current`, if
  `self.info_dialog` is open, call `self.info_dialog.refresh()`.
- **New command:** `cmd_info(app)` in `commands.py`, modeled on
  `cmd_enhancement_dialog`.

## Save integration (`commands.py`)

In `cmd_save_as`, after `save_kwargs` is built (`commands.py:117`):

```python
meta = app.image_model.metadata
if app.image_model.keep_metadata and meta is not None and fmt in _EXIF_WRITE_FORMATS:
    save_kwargs["exif"] = metadata.build_save_exif(meta).tobytes()
```

- `_EXIF_WRITE_FORMATS = {"JPEG", "TIFF", "WEBP", "PNG"}` — formats Pillow can
  write `exif=` to. For other formats (GIF/BMP/PPM/ICO) with keep enabled, skip
  silently and flash a `show_temp_title` note ("metadata not written for <fmt>").
- The default path (keep off) is unchanged → today's strip behavior is preserved
  byte-for-byte.

## Error handling

- **No EXIF:** Camera/Exposure/Location show "No EXIF metadata"; the File section
  still populates; edit fields remain usable to add metadata.
- **Bad tag values:** per-tag decode wrapped in try/except → raw `repr` shown,
  panel never crashes.
- **Missing file at stat time:** size shows "unknown."
- **Unsupported save format with keep on:** skipped with a temp-title note.

## Testing (`tests/test_metadata.py`, synthetic fixtures)

Pure-logic units (synthetic `Image.Exif`, no committed binaries — matches
`tests/conftest.py`):
- `decode_value`: rationals (`f/2.8`, `1/250 s`, focal length, EV), GPS →
  decimal degrees, datetime normalization, defensive fallback on a bad value.
- `build_sections`: known tags land in the right group with the right labels;
  "all tags" lists everything; empty exif yields the empty-state sections.
- `build_save_exif`: `Orientation` reset to 1, thumbnail/IFD1 dropped,
  `ExifImageWidth/Height` removed, edits applied.
- `redact_gps`: GPS IFD removed, other tags intact.

Round-trip (via `tmp_path`):
- Build a JPEG carrying a known `Exif` (new `conftest` fixture) → `ImageModel.load`
  → save with `keep_metadata=True` → reopen and assert tags survive and
  orientation is normalized; with `redact_gps` applied, assert GPS is gone.
- Save with default (`keep_metadata=False`) → reopened file has no EXIF
  (today's behavior, now covered).

## Definition of Done

- `cmd_info` opens the panel via `i` and the context menu; it follows navigation.
- Default Save As still strips metadata (unchanged); "Keep metadata on save"
  writes sanitized EXIF for JPEG/TIFF/WebP/PNG; "Remove GPS" and "Strip all" work.
- `tests/test_metadata.py` (and the round-trip) pass under `uv run pytest`.
- `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, and
  `uv run mypy src/pxv/` are all clean.
- No binary fixtures committed; no new runtime dependencies (Pillow already
  provides everything).
