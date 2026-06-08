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
| `u` | Uncrop (undo last crop) |
| `t` | Rotate clockwise |
| `T` | Rotate counterclockwise |
| `D` | Toggle dark/light background |
| `f` / `F11` | Toggle fullscreen |
| `s` | Toggle slideshow |
| `+` / `-` | Slideshow interval +/- 1s |
| `e` | Enhancement dialog |
| `i` | Show image info / EXIF |
| `Ctrl+s` | Save as |
| `Escape` | Exit slideshow/fullscreen, or clear selection |
| `q` | Quit |

Right-click for additional options: rotate, flip, resize, grab (screenshot), print, and more.

## Enhancements

The enhancement dialog (`e`) provides real-time adjustment of:

- Brightness, contrast, gamma
- Sharpen, blur
- Saturation, hue rotation
- Per-channel RGB color balance

## Features

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
- Pillow 10+

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
