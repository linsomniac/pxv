"""Three-tier image state model: original -> working -> display.

AIDEV-NOTE: original_image preserves the true loaded image (including alpha/mode).
working_image is always RGB, mutated by destructive ops (crop, rotate, flip, resize).
_save_alpha tracks the alpha channel through geometry ops so it can be re-attached on save.
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
        self._original_alpha: Image.Image | None = None
        self._save_alpha: Image.Image | None = None

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @staticmethod
    def _to_rgb_working(img: Image.Image) -> Image.Image:
        """Convert any image to RGB for the working/enhancement pipeline.

        AIDEV-NOTE: RGBA is composited onto white so transparency renders
        visibly. Other modes are directly converted. The enhancement pipeline
        (HSV conversion, LUT, etc.) requires RGB.
        """
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        if img.mode != "RGB":
            return img.convert("RGB")
        return img.copy()

    def load(self, path: Path) -> None:
        """Load an image from disk. Handles EXIF orientation and mode conversion."""
        raw = Image.open(path)
        raw.load()  # force full load so file handle is released

        # Fix EXIF orientation
        img: Image.Image = ImageOps.exif_transpose(raw)

        # AIDEV-NOTE: Store true original (preserving alpha/mode) for reset and save.
        # working_image is always RGB for the enhancement pipeline.
        self.original_image = img.copy()

        if img.mode == "RGBA":
            self._original_alpha = img.split()[3].copy()
            self._save_alpha = self._original_alpha.copy()
        else:
            self._original_alpha = None
            self._save_alpha = None

        self.working_image = self._to_rgb_working(img)
        self._current_path = path

    def crop(self, box: tuple[int, int, int, int]) -> None:
        """Crop working image to (left, upper, right, lower)."""
        if self.working_image is None:
            return
        self.working_image = self.working_image.crop(box)
        if self._save_alpha is not None:
            self._save_alpha = self._save_alpha.crop(box)

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
            if self._save_alpha is not None:
                self._save_alpha = self._save_alpha.transpose(method)

    def flip_horizontal(self) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self._save_alpha is not None:
            self._save_alpha = self._save_alpha.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    def flip_vertical(self) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if self._save_alpha is not None:
            self._save_alpha = self._save_alpha.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def resize(self, new_size: tuple[int, int]) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.resize(new_size, Image.Resampling.LANCZOS)
        if self._save_alpha is not None:
            self._save_alpha = self._save_alpha.resize(new_size, Image.Resampling.LANCZOS)

    def reset(self) -> None:
        """Reset working image to original (undo all destructive ops)."""
        if self.original_image is not None:
            self.working_image = self._to_rgb_working(self.original_image)
            self._save_alpha = (
                self._original_alpha.copy() if self._original_alpha is not None else None
            )

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

        return apply_enhancements(scaled, params, zoom=zoom)

    def get_save_image(
        self, params: EnhancementParams, *, preserve_alpha: bool = False
    ) -> Image.Image | None:
        """Get the full-resolution enhanced image for saving.

        AIDEV-NOTE: When preserve_alpha is True and the original had an alpha
        channel, we re-attach it after applying enhancements to the RGB working
        image. Enhancements only affect RGB; alpha passes through unchanged.
        """
        if self.working_image is None:
            return None
        enhanced = apply_enhancements(self.working_image, params)
        if preserve_alpha and self._save_alpha is not None:
            enhanced.putalpha(self._save_alpha)
        return enhanced
