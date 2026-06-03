# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/).

## [Unreleased]

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

[Unreleased]: https://github.com/linsomniac/pxv/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/linsomniac/pxv/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/linsomniac/pxv/releases/tag/v1.0.0
