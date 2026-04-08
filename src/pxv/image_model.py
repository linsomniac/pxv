"""Three-tier image state model: original -> working -> display.

AIDEV-NOTE: original_image is NEVER modified after load (only used for Reset).
working_image is mutated by destructive ops (crop, rotate, flip, resize).
Display image is computed on-the-fly: scale working to display size, then apply enhancements.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from pxv.enhancements import EnhancementParams, apply_enhancements


class ImageModel:
    """Manages the three-tier image state."""

    def __init__(self) -> None:
        self.original_image: Image.Image | None = None
        self.working_image: Image.Image | None = None
        self._current_path: Path | None = None

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    def load(self, path: Path) -> None:
        """Load an image from disk. Handles EXIF orientation and mode conversion."""
        raw = Image.open(path)
        raw.load()  # force full load so file handle is released

        # Fix EXIF orientation
        img: Image.Image = ImageOps.exif_transpose(raw)

        # AIDEV-NOTE: Convert to RGB for consistent processing.
        # RGBA: composite onto white. Other modes: direct convert.
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        self.original_image = img
        self.working_image = img.copy()
        self._current_path = path

    def crop(self, box: tuple[int, int, int, int]) -> None:
        """Crop working image to (left, upper, right, lower)."""
        if self.working_image is None:
            return
        self.working_image = self.working_image.crop(box)

    def rotate(self, degrees: int) -> None:
        """Rotate working image by 90, 180, or 270 degrees."""
        if self.working_image is None:
            return
        transpose_map = {
            90: Image.Transpose.ROTATE_90,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_270,
        }
        method = transpose_map.get(degrees)
        if method is not None:
            self.working_image = self.working_image.transpose(method)

    def flip_horizontal(self) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    def flip_vertical(self) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def resize(self, new_size: tuple[int, int]) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.resize(new_size, Image.Resampling.LANCZOS)

    def reset(self) -> None:
        """Reset working image to original (undo all destructive ops)."""
        if self.original_image is not None:
            self.working_image = self.original_image.copy()

    def get_working_size(self) -> tuple[int, int]:
        if self.working_image is None:
            return (0, 0)
        w, h = self.working_image.size
        return (w, h)

    def get_display_image(
        self,
        zoom: float,
        params: EnhancementParams,
    ) -> Image.Image | None:
        """Get the image scaled for display and with enhancements applied.

        AIDEV-NOTE: Scale FIRST, then enhance — this is ~4x faster than enhance-then-scale
        because the enhancement pipeline operates on fewer pixels.
        """
        if self.working_image is None:
            return None

        w, h = self.working_image.size
        display_w = max(1, int(w * zoom))
        display_h = max(1, int(h * zoom))

        # Choose resampling method based on zoom level
        if zoom > 2.0:
            resample = Image.Resampling.NEAREST  # show individual pixels
        else:
            resample = Image.Resampling.LANCZOS

        if zoom == 1.0:
            scaled = self.working_image.copy()
        else:
            scaled = self.working_image.resize((display_w, display_h), resample)

        return apply_enhancements(scaled, params)

    def get_save_image(self, params: EnhancementParams) -> Image.Image | None:
        """Get the full-resolution enhanced image for saving."""
        if self.working_image is None:
            return None
        return apply_enhancements(self.working_image, params)
