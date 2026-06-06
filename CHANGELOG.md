# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/).

## [Unreleased]

### Added
- Save-options dialog: when saving as JPEG, PNG, WebP, or TIFF, a small dialog now
  lets you choose encoding parameters — JPEG quality, PNG compression level, WebP
  lossless/quality, and TIFF compression (None/LZW/Deflate) — plus a "keep metadata"
  toggle synced with the info panel. Chosen values are remembered for the session.
  JPEG quality is no longer hardcoded to 95.
- Slideshow mode: press `s` to auto-advance through the file list (default 4s), and
  `+` / `-` to change the interval by 1s while it runs. Start one at launch with
  `--slideshow` (or `--slideshow=SECS`).
- Fullscreen presentation mode: press `f` or `F11` (or launch with `--fullscreen`)
  to show the image centered on black with no window chrome. `Escape` leaves
  slideshow/fullscreen before falling back to clearing the selection.
- Multi-level undo/redo: crop, autocrop, rotate, flip, resize, and enhancement
  "Apply" (slider values included) can now all be undone and redone. Press `u` or
  `Ctrl+Z` to undo and `Ctrl+Y` / `Ctrl+Shift+Z` to redo; Undo/Redo are also in the
  right-click menu. This replaces the previous single-level "uncrop" (`u` is now a
  general undo); Reset and loading a new image start a fresh history.

## [1.0.3] - 2026-06-05

Adds the image info / EXIF panel and fixes a dialog-close focus lockup.

### Added
- Image info / EXIF panel (`i` or right-click → Info): view file facts and decoded
  camera, exposure, capture-date, and GPS metadata; edit Description / Artist /
  Copyright / Date; remove GPS; and opt in to "keep metadata on save". Saving still
  strips metadata by default.

### Fixed
- Closing the info/EXIF panel (or the enhancement panel) with its **Close** button
  no longer leaves the app keyboard-unresponsive. Because all shortcuts are bound to
  the main window, closing a non-modal dialog now explicitly returns keyboard focus
  to it; clicking the image also re-arms the shortcuts.

## [1.0.2] - 2026-06-05

Adds a `--version` flag and official Debian packaging.

### Added

- `--version` command-line flag that prints the installed version and exits.
- A native Debian package (`.deb`), built in CI and attached to each GitHub
  release. Installs the `pxv` command plus a desktop launcher, scalable icon,
  and "Open with" associations for common image formats.

## [1.0.1] - 2026-06-03

A bug-fix and hardening release over 1.0.0.

### Added

- Pan zoomed images that are larger than the viewport: scroll the wheel to pan
  vertically and Shift+scroll to pan horizontally (supports `<MouseWheel>` on
  Windows/macOS and Button-4/5 on X11). Oversized images now open centered
  instead of showing a clipped corner.
- Warn on stderr when a path passed on the command line does not exist, so a
  typo no longer silently behaves like "no arguments."

### Changed

- Lowered the minimum Pillow version from 12.0 to 10.0 to avoid forcing
  upgrades and resolver conflicts (nothing in the code needs 12.x).
- The package version is now single-sourced from installed package metadata,
  eliminating drift between `pyproject.toml` and `__init__.py`.
- Synced the README keyboard-shortcut table with the in-app help and relabeled
  `M` as "Zoom to fill display."

### Fixed

- Transparency compositing: `LA`, `PA`, and palette-with-transparency images
  now composite onto the background like `RGBA`, instead of leaking the
  underlying color of transparent pixels into the display and into non-alpha
  saves.
- Cropping after a window resize no longer targets the wrong region: the
  rubber-band selection is cleared on resize, and selection coordinates are
  scroll-aware so they stay correct while the image is panned.
- Saving a transparent image to GIF preserves binary transparency instead of
  flattening it to white.
- Saving to a name with an unknown or missing extension now writes PNG to a
  `.png` path instead of writing PNG bytes under a mismatched, extensionless
  name.
- The `t` / `T` rotate shortcuts are now documented correctly (`t` clockwise,
  `T` counterclockwise) in both the in-app help and the README.
- Blur is no longer silently dropped from the enhancement preview at low zoom.
- Navigation keeps the file-list cursor in sync with the displayed image when a
  corrupt or unreadable file fails to load.
- A screenshot grab that captures successfully but fails to save no longer
  reports the misleading "Could not capture screenshot."
- Eliminated stray timer callbacks firing against torn-down widgets (the
  autocrop status-title timer, the enhancement-dialog debounce timer, and
  deferred startup callbacks).

## [1.0.0] - 2026-04-12

Initial release. Core features: crop, autocrop, save, resize, rotate, maxpect
(zoom to fill display), and forward/back navigation across multiple images
given on the command line.

[Unreleased]: https://github.com/linsomniac/pxv/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/linsomniac/pxv/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/linsomniac/pxv/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/linsomniac/pxv/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/linsomniac/pxv/releases/tag/v1.0.0
