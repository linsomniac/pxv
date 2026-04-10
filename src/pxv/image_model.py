"""Three-tier image state model: original -> working -> display.

AIDEV-NOTE: original_image preserves the true loaded image (including alpha/mode).
working_image is always RGB (composited onto white for display), mutated by destructive ops.
_save_rgba keeps the true RGBA pixel values through geometry ops so that semi-transparent
pixels survive round-trip save. Enhancements are applied to _save_rgba's RGB channels on save.
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
        self._original_rgba: Image.Image | None = None
        self._save_rgba: Image.Image | None = None
        # AIDEV-NOTE: Pre-crop state for uncrop (one level of undo)
        self._pre_crop_working: Image.Image | None = None
        self._pre_crop_rgba: Image.Image | None = None

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

    @staticmethod
    def _has_transparency(img: Image.Image) -> bool:
        """Check if an image has transparency (alpha band or palette transparency)."""
        if img.mode in ("RGBA", "LA", "PA"):
            return True
        if img.mode == "P" and "transparency" in img.info:
            return True
        return False

    def load(self, path: Path) -> None:
        """Load an image from disk. Handles EXIF orientation and mode conversion."""
        raw = Image.open(path)
        raw.load()  # force full load so file handle is released

        # Fix EXIF orientation
        img: Image.Image = ImageOps.exif_transpose(raw)

        # AIDEV-NOTE: Store true original (preserving alpha/mode) for reset and save.
        # working_image is always RGB for the enhancement pipeline.
        self.original_image = img.copy()

        # AIDEV-NOTE: Normalize any transparent image (RGBA, LA, palette+transparency)
        # to RGBA for the save buffer. This ensures semi-transparent RGB values survive
        # round-trip saves instead of being corrupted by white-compositing.
        if self._has_transparency(img):
            rgba = img.convert("RGBA")
            self._original_rgba = rgba.copy()
            self._save_rgba = rgba.copy()
        else:
            self._original_rgba = None
            self._save_rgba = None

        self.working_image = self._to_rgb_working(img)
        self._current_path = path

    def crop(self, box: tuple[int, int, int, int]) -> None:
        """Crop working image to (left, upper, right, lower).

        AIDEV-NOTE: Saves pre-crop state so uncrop() can restore it.
        Only one level of undo is supported.
        """
        if self.working_image is None:
            return
        self._pre_crop_working = self.working_image.copy()
        self._pre_crop_rgba = self._save_rgba.copy() if self._save_rgba is not None else None
        self.working_image = self.working_image.crop(box)
        if self._save_rgba is not None:
            self._save_rgba = self._save_rgba.crop(box)

    def uncrop(self) -> bool:
        """Restore the pre-crop image state. Returns True if uncrop was performed."""
        if self._pre_crop_working is None:
            return False
        self.working_image = self._pre_crop_working
        self._save_rgba = self._pre_crop_rgba
        self._pre_crop_working = None
        self._pre_crop_rgba = None
        return True

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
            if self._save_rgba is not None:
                self._save_rgba = self._save_rgba.transpose(method)

    def flip_horizontal(self) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self._save_rgba is not None:
            self._save_rgba = self._save_rgba.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    def flip_vertical(self) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if self._save_rgba is not None:
            self._save_rgba = self._save_rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def resize(self, new_size: tuple[int, int]) -> None:
        if self.working_image is None:
            return
        self.working_image = self.working_image.resize(new_size, Image.Resampling.LANCZOS)
        if self._save_rgba is not None:
            self._save_rgba = self._save_rgba.resize(new_size, Image.Resampling.LANCZOS)

    def reset(self) -> None:
        """Reset working image to original (undo all destructive ops)."""
        if self.original_image is not None:
            self.working_image = self._to_rgb_working(self.original_image)
            self._save_rgba = (
                self._original_rgba.copy() if self._original_rgba is not None else None
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
        bg_color: tuple[int, int, int] = (255, 255, 255),
    ) -> Image.Image | None:
        """Get the image scaled for display and with enhancements applied.

        AIDEV-NOTE: Scale FIRST, then enhance — this is ~4x faster than enhance-then-scale
        because the enhancement pipeline operates on fewer pixels.
        When bg_color differs from white and _save_rgba exists, we recomposite
        the true RGBA onto the requested background instead of using the
        white-composited working_image.
        """
        if self.working_image is None:
            return None

        # AIDEV-NOTE: For transparent images, recomposite onto the chosen bg_color
        # so the user can preview transparency against dark or light backgrounds.
        # Falls back to the white-composited working_image for opaque images.
        if self._save_rgba is not None and bg_color != (255, 255, 255):
            base = Image.new("RGB", self._save_rgba.size, bg_color)
            base.paste(self._save_rgba, mask=self._save_rgba.split()[3])
        else:
            base = self.working_image

        w, h = base.size
        display_w = max(1, int(w * zoom))
        display_h = max(1, int(h * zoom))

        # Choose resampling method based on zoom level
        if zoom > 2.0:
            resample = Image.Resampling.NEAREST  # show individual pixels
        else:
            resample = Image.Resampling.LANCZOS

        if zoom == 1.0:
            scaled = base.copy()
        else:
            scaled = base.resize((display_w, display_h), resample)

        return apply_enhancements(scaled, params, zoom=zoom)

    def get_save_image(
        self, params: EnhancementParams, *, preserve_alpha: bool = False
    ) -> Image.Image | None:
        """Get the full-resolution enhanced image for saving.

        AIDEV-NOTE: When preserve_alpha is True and _save_rgba exists, we enhance
        the true RGBA RGB channels (not the white-composited working_image) so that
        semi-transparent pixels like (255,0,0,128) round-trip faithfully instead of
        becoming (255,127,127,128) from white fringing.
        """
        if self.working_image is None:
            return None
        if preserve_alpha and self._save_rgba is not None:
            r, g, b, a = self._save_rgba.split()
            rgb = Image.merge("RGB", (r, g, b))
            enhanced_rgb = apply_enhancements(rgb, params)
            enhanced_rgb.putalpha(a)
            return enhanced_rgb
        return apply_enhancements(self.working_image, params)
