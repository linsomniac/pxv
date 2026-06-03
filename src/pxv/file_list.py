"""Ordered list of image file paths with next/prev navigation."""

from __future__ import annotations

import sys
from pathlib import Path

IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tif",
        ".tiff",
        ".gif",
        ".webp",
        ".ppm",
        ".pgm",
        ".pbm",
        ".ico",
    }
)


class FileList:
    """Manages an ordered list of image paths with wrap-around navigation."""

    def __init__(self, paths: list[Path]) -> None:
        self._paths: list[Path] = list(paths)
        self._index: int = 0

    @property
    def index(self) -> int:
        return self._index

    @index.setter
    def index(self, value: int) -> None:
        # AIDEV-NOTE: Wrap into range so a restored index (e.g. rolling back a
        # failed navigation) always points at a valid entry.
        if self._paths:
            self._index = value % len(self._paths)

    def current(self) -> Path | None:
        if not self._paths:
            return None
        return self._paths[self._index]

    def next(self) -> Path | None:
        """Advance to next image (wraps around)."""
        if not self._paths:
            return None
        self._index = (self._index + 1) % len(self._paths)
        return self._paths[self._index]

    def prev(self) -> Path | None:
        """Go to previous image (wraps around)."""
        if not self._paths:
            return None
        self._index = (self._index - 1) % len(self._paths)
        return self._paths[self._index]

    def position_str(self) -> str:
        """Return e.g. '3/10' for display in title bar."""
        if not self._paths:
            return "0/0"
        return f"{self._index + 1}/{len(self._paths)}"

    def count(self) -> int:
        return len(self._paths)

    def add(self, path: Path) -> None:
        """Add a file to the list and make it current.

        AIDEV-NOTE: Deduplicates by resolved path so re-opening an already-listed
        file just selects the existing entry instead of creating a phantom duplicate
        (which would inflate the position count and stutter next/prev navigation).
        """
        resolved = path.resolve()
        for i, existing in enumerate(self._paths):
            if existing == resolved:
                self._index = i
                return
        self._paths.append(resolved)
        self._index = len(self._paths) - 1


def expand_paths(raw_paths: list[str]) -> list[Path]:
    """Expand CLI arguments to a flat list of image file paths.

    Files are added directly. Directories are expanded to sorted image files within.
    Duplicate paths are removed (first occurrence wins); nonexistent paths are
    reported to stderr so a typo isn't silently indistinguishable from "no args".
    """
    result: list[Path] = []
    seen: set[Path] = set()
    missing: list[str] = []

    def _add(p: Path) -> None:
        if p not in seen:
            seen.add(p)
            result.append(p)

    for raw in raw_paths:
        p = Path(raw).expanduser().resolve()
        if p.is_file():
            _add(p)
        elif p.is_dir():
            dir_files = sorted(
                (f for f in p.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS),
                key=lambda f: f.name.lower(),
            )
            for f in dir_files:
                _add(f)
        else:
            missing.append(raw)

    if missing:
        print("pxv: skipping nonexistent path(s): " + ", ".join(missing), file=sys.stderr)
    return result
