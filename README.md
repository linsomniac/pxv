# pxv

A simple image viewer and manipulator built with Python/Pillow/Tkinter that takes inspiration from
the classic Unix [xv](http://www.trilon.com/xv/) image viewer.

## Quickstart

Run directly from the GitHub repo (requires [uv](https://docs.astral.sh/uv/)):

```sh
uvx --from git+https://github.com/linsomniac/pxv pxv photo.jpg
```

Or install locally:

```sh
uv pip install git+https://github.com/linsomniac/pxv
pxv photo.jpg
```

Pass files, directories, or nothing (opens a file dialog):

```sh
pxv image.png              # single file
pxv *.jpg                  # multiple files
pxv ~/Photos/              # all images in a directory
pxv                        # open file dialog
```

### Debian / Ubuntu (.deb)

Each [GitHub release](https://github.com/linsomniac/pxv/releases) includes a
`pxv_<version>_all.deb`. Install it (apt pulls in `python3-tk` and Pillow):

```sh
sudo apt install ./pxv_1.0.1_all.deb
```

It targets current distributions (Debian 13 / Ubuntu 24.04 or newer, which ship
Pillow ≥ 10). After installing, `pxv` is on your `PATH` and appears in the
applications menu and image "Open with" lists.

### NixOS / Nix (flake)

Run it without installing:

```sh
nix run github:linsomniac/pxv -- photo.jpg
```

Install into your profile:

```sh
nix profile install github:linsomniac/pxv
```

Add to a NixOS configuration via the overlay (this also installs the `.desktop`
entry and icon, so pxv appears in launchers and "Open with" menus):

```nix
{
  inputs.pxv.url = "github:linsomniac/pxv";

  # in your configuration.nix / module:
  nixpkgs.overlays = [ inputs.pxv.overlays.default ];
  environment.systemPackages = [ pkgs.pxv ];
}
```

Without flakes, `nix-build` produces the package from a checkout (uses `default.nix`).

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `?` | Show keyboard shortcuts help |
| `>` | Double zoom |
| `<` | Halve zoom |
| `.` | Increase zoom 10% |
| `,` | Reduce zoom 10% |
| `n` | Zoom to 1:1 (normal) |
| `M` | Zoom to fill display |
| `Space` / `Right` | Next image |
| `Backspace` / `Left` | Previous image |
| `b` | Browse thumbnails (Visual Schnauzer) |
| `c` | Crop to selection |
| `A` | Autocrop background borders |
| `u` / `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |
| `t` | Rotate clockwise |
| `T` | Rotate counterclockwise |
| `D` | Toggle dark/light background |
| `f` / `F11` | Toggle fullscreen |
| `s` | Toggle slideshow |
| `+` / `-` | Slideshow interval +/- 1s |
| `e` | Enhancement dialog |
| `d` | Draw / annotate (drawing palette) |
| `i` | Show image info / EXIF |
| `Ctrl+s` | Save as |
| `Escape` | Exit slideshow/fullscreen, or clear selection |
| `q` | Quit |

Right-click for additional options: rotate, flip, resize, grab (screenshot), print, and more.

## Enhancements

The enhancement dialog (`e`) provides real-time adjustment with a live
histogram (luminance + RGB overlays, log scale, clipping readouts) that tracks
every change:

- **Sliders** — brightness, contrast, gamma, sharpen, blur, saturation, hue
  rotation, per-channel RGB balance
- **Levels** — black/gamma/white input markers over the channel histogram,
  output range, Auto (percentile clip), and black/gray/white eyedroppers that
  sample the image
- **Curves** — spline curve editor per channel (master + R/G/B) with histogram
  backdrop, editable histogram Equalize, and Invert — the classic xv intensity
  and RGB graphs, modernized

**Compare** (hold) flips between the original and adjusted image; **Apply**
bakes the adjustments into the working image (undoable with `u`/Ctrl+Z).

## Annotations

Draw mode (`d`, or right-click → Draw / Annotate...) opens a tool palette and
turns the canvas into a drawing surface:

- **Tools** (keys `1`–`8`) — Select, freehand, line, arrow, rectangle,
  ellipse, highlighter, and text labels
- **Styling** — six color swatches plus a custom chooser, thin/medium/thick
  size presets (auto-scaled to the image size), filled-vs-outline toggle, and
  an opacity slider; with a shape selected, the controls restyle it live
- **Editing** — the Select tool picks the topmost shape: drag to move,
  `Delete`/`Backspace` to remove, `u`/`Ctrl+Z`/`Ctrl+Y` for in-mode
  undo/redo; double-click a text label to re-edit it

Shapes stay editable vector objects while the palette is open, and their
sizes are in image pixels — the saved file is independent of the zoom you
drew at. **Done** (or closing the palette window) bakes them into the image
as a single undoable edit; **Cancel** discards them after confirmation.
Navigating away or quitting with unsaved annotation work prompts first.

## Features

- Image annotations / draw mode: freehand, lines, arrows, boxes, ellipses, highlighter, and text labels — editable vectors during the session, baked as one undoable edit
- Histogram, levels, and curves in the enhancement dialog (beyond-xv: live histogram backdrop, eyedroppers, editable equalization)
- XV-style window sizing: window grows/shrinks to fit the displayed image, capped at the current monitor's bounds
- Multi-monitor aware: detects per-monitor geometry via xrandr so windows don't span displays
- EXIF-aware orientation
- Save-options dialog for JPEG/PNG/WebP/TIFF (quality, compression, lossless, keep-metadata)
- Slideshow auto-advance (`--slideshow[=SECS]`) and fullscreen presentation mode (`--fullscreen`)
- Rubber-band selection for cropping
- Wrap-around file navigation
- Supports PNG, JPEG, BMP, TIFF, GIF, WebP, PPM, PGM, PBM, ICO

## Requirements

- Python 3.10+
- Tkinter (usually included with Python; on Debian/Ubuntu: `sudo apt install python3-tk`)
- Pillow 10.1+

## Development

```sh
git clone https://github.com/linsomniac/pxv
cd pxv
uv sync
uv run pxv test_images/
```

Lint and type-check:

```sh
uv run ruff check src/
uv run ruff format --check src/
uv run mypy src/pxv/
```
