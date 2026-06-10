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

## Features

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
