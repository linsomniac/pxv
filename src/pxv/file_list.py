"""Ordered list of image file paths with next/prev navigation."""

from __future__ import annotations

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
        """Add a file to the list and make it current."""
        self._paths.append(path)
        self._index = len(self._paths) - 1


def expand_paths(raw_paths: list[str]) -> list[Path]:
    """Expand CLI arguments to a flat list of image file paths.

    Files are added directly. Directories are expanded to sorted image files within.
    """
    result: list[Path] = []
    for raw in raw_paths:
        p = Path(raw).expanduser().resolve()
        if p.is_file():
            result.append(p)
        elif p.is_dir():
            dir_files = sorted(
                (f for f in p.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS),
                key=lambda f: f.name.lower(),
            )
            result.extend(dir_files)
    return result
