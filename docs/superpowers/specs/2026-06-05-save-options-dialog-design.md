# Save-options dialog + EXIF-preserving saves — Design

**Date:** 2026-06-05
**Idea:** Ideas.md #9 (S–M)

## Background

JPEG quality is hardcoded to 95 (`commands.py:139`); PNG/WebP/TIFF get no encoding
options. EXIF/metadata preservation is **already implemented** — `ImageModel.keep_metadata`,
`commands._exif_for_save()`, sanitization, GPS redaction, and a "Keep metadata on save"
toggle in the Info dialog. The remaining gap is a small dialog to choose per-format encoding
parameters at Save As time.

## Decisions (from brainstorming)

- **Flow:** native Save As file picker first; an options dialog appears **only** when the
  resolved format has tunable options. GIF/BMP save immediately.
- **Scope of options:** JPEG quality, PNG compression level, WebP lossless + quality, and
  TIFF compression.
- **Keep-EXIF:** the dialog also shows a "Keep metadata" checkbox (all option-formats are
  EXIF-capable), synced with `model.keep_metadata` and the Info dialog.
- **Persistence:** session memory only (an instance on the app); resets to defaults on
  restart. No config file (separate honorable-mention item).

## Components

### `save_options.py` (new, pure — no Tk)

```python
@dataclass
class SaveOptions:
    jpeg_quality: int = 95
    png_compress_level: int = 6
    webp_lossless: bool = False
    webp_quality: int = 80
    tiff_compression: str = "None"   # UI label: "None" | "LZW" | "Deflate"

FORMATS_WITH_OPTIONS = {"JPEG", "PNG", "WEBP", "TIFF"}

_TIFF_COMPRESSION = {"LZW": "tiff_lzw", "Deflate": "tiff_deflate"}  # "None" -> omit

def build_save_kwargs(fmt: str, opts: SaveOptions) -> dict[str, object]:
    ...
```

`build_save_kwargs` returns the Pillow encoder kwargs for the format, **excluding** `exif`
(which stays in the existing `_exif_for_save` path):

| Format | kwargs |
|--------|--------|
| JPEG   | `{"quality": jpeg_quality}` |
| PNG    | `{"compress_level": png_compress_level}` |
| WEBP   | `{"lossless": webp_lossless, "quality": webp_quality}` |
| TIFF   | `{"compression": <mapped>}` when not `"None"`, else `{}` |
| GIF/BMP/other | `{}` |

### `dialogs.py` — `save_options_dialog` (new)

Modal `Toplevel`, same pattern as `resize_dialog` (transient, grab_set, centered on parent,
Return=OK / Escape=Cancel, `wait_window`).

```python
def save_options_dialog(
    parent: tk.Tk, fmt: str, opts: SaveOptions,
    keep_metadata: bool, keep_supported: bool,
) -> tuple[SaveOptions, bool] | None:
```

- Renders only widgets relevant to `fmt`:
  - JPEG: quality scale/spinbox 1–100.
  - PNG: compression-level spinbox 0–9.
  - WebP: "Lossless" checkbox + quality spinbox; quality disabled while lossless is checked.
  - TIFF: compression dropdown (None / LZW / Deflate).
- "Keep metadata on save" checkbox shown when `keep_supported`, seeded from `keep_metadata`.
- OK → returns a new `SaveOptions` (clamped to valid ranges) and the keep flag.
- Cancel / window-close → returns `None`, which aborts the save entirely.

### `commands.py` — `cmd_save_as` changes

After `_resolve_save_format`:

```python
if fmt in save_options.FORMATS_WITH_OPTIONS:
    keep_supported = fmt in _EXIF_WRITE_FORMATS
    result = save_options_dialog(
        app.root, fmt, app.save_options,
        app.image_model.keep_metadata, keep_supported,
    )
    if result is None:
        return  # cancelled
    app.save_options, app.image_model.keep_metadata = result
    if app.info_dialog is not None:
        app.info_dialog.refresh()  # keep the two checkboxes in sync

save_kwargs = save_options.build_save_kwargs(fmt, app.save_options)
```

The hardcoded `if fmt == "JPEG": save_kwargs["quality"] = 95` block is removed. EXIF handling,
the "metadata not saved for {fmt}" title message, the GIF `_rgba_to_gif` special-case, and
`preserve_alpha` all stay unchanged.

### `app.py`

Add `self.save_options = SaveOptions()` in `PxvApp.__init__`.

## Error handling

- Cancel aborts cleanly (no save, no state change).
- Out-of-range entries are clamped on OK (mirrors `resize_dialog`'s tolerant `IntVar` reads).
- Save failures continue to surface via the existing `messagebox.showerror("Save Error", …)`.

## Testing

`tests/test_save_options.py` (pure, no display, mirrors `test_save_helpers.py`):

- `build_save_kwargs` for each format and option combination.
- TIFF "None" omits `compression`; "LZW"/"Deflate" map correctly.
- WebP lossless True vs False both include expected keys.
- Defaults match the dataclass.
- GIF/BMP/unknown → `{}`.

`cmd_grab`'s screenshot save is intentionally untouched (always PNG, no dialog).

## Out of scope

Config-file persistence, progressive-JPEG / chroma-subsampling, PNG `optimize`, and changes
to the screenshot save path.
