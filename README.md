# pxv

A simple image viewer and manipulator built with Python/Pillow/Tkinter that takes inspiration from
the classic Unix [xv](http://www.trilon.com/xv/) image viewer.

## Quickstart

Run directly from the GitHub repo (requires [uv](https://docs.astral.sh/uv/)):

```sh
uvx --from git+https://github.com/seanreifschneider/pxv pxv photo.jpg
```

Or install locally:

```sh
uv pip install git+https://github.com/seanreifschneider/pxv
pxv photo.jpg
```

Pass files, directories, or nothing (opens a file dialog):

```sh
pxv image.png              # single file
pxv *.jpg                  # multiple files
pxv ~/Photos/              # all images in a directory
pxv                        # open file dialog
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `>` | Zoom in |
| `<` | Zoom out |
| `n` | Zoom to 1:1 (normal) |
| `Space` / `Right` | Next image |
| `Backspace` / `Left` | Previous image |
| `c` | Crop to selection |
| `e` | Enhancement dialog |
| `Ctrl+s` | Save as |
| `Escape` | Clear selection |
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
- Rubber-band selection for cropping
- Wrap-around file navigation
- Supports PNG, JPEG, BMP, TIFF, GIF, WebP, PPM, PGM, PBM, ICO

## Requirements

- Python 3.10+
- Tkinter (usually included with Python; on Debian/Ubuntu: `sudo apt install python3-tk`)
- Pillow 12+

## Development

```sh
git clone https://github.com/seanreifschneider/pxv
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
