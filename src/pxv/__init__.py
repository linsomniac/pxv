"""pxv - A Python clone of the classic Unix xv image viewer."""

from importlib.metadata import PackageNotFoundError, version

from pxv.app import main

# AIDEV-NOTE: Single-source the version from the installed package metadata
# (derived from pyproject.toml) so it can't drift from a hard-coded literal.
try:
    __version__ = version("pxv")
except PackageNotFoundError:  # running from a source tree without an installed dist
    __version__ = "0.0.0+unknown"

__all__ = ["main"]
