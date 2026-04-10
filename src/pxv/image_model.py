"""Three-tier image state model: original -> working -> display.

AIDEV-NOTE: original_image preserves the true loaded image (including alpha/mode).
working_image is always RGB (composited onto white for display), mutated by destructive ops.
_save_rgba keeps the true RGBA pixel values through geometry ops so that semi-transparent
pixels survive round-trip save. Enhancements are applied to _save_rgba's RGB channels on save.
Display image is computed on-the-fly: scale working to display size, then apply enhancements.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageOps

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

    # AIDEV-NOTE: xv-style autocrop tolerance constants.
    # EPSILON: max per-channel difference from background for a pixel to be
    # considered background (~15% of 256). Matches xv's 24-bit EPSILON.
    # MISSPCT: max percentage of foreground pixels allowed in a row/column
    # for it to still be trimmed (handles JPEG artifacts, anti-aliasing).
    _AUTOCROP_EPSILON = 39
    _AUTOCROP_MISSPCT = 6

    def autocrop(self) -> bool:
        """Auto-crop uniform background borders. Returns True if cropping was performed.

        For transparent images, trims fully-transparent borders.
        For RGB images, detects background from the average of the 4 corner pixels
        with xv-style tolerance.
        """
        if self.working_image is None:
            return False
        box = self._find_autocrop_box()
        if box is None:
            return False
        self.crop(box)
        return True

    def _find_autocrop_box(self) -> tuple[int, int, int, int] | None:
        """Determine the bounding box for autocrop, or None if no crop is needed."""
        assert self.working_image is not None

        if self._save_rgba is not None:
            fg_mask = self._autocrop_mask_alpha()
        else:
            fg_mask = self._autocrop_mask_rgb()

        return self._autocrop_scan_edges(fg_mask)

    def _autocrop_mask_alpha(self) -> Image.Image:
        """Build foreground mask from alpha channel (any opacity = foreground)."""
        assert self._save_rgba is not None
        alpha = self._save_rgba.split()[3]
        return alpha.point(lambda a: 255 if a > 0 else 0)

    def _autocrop_mask_rgb(self) -> Image.Image:
        """Build foreground mask using 4-corner averaged background with tolerance."""
        img = self.working_image
        assert img is not None
        w, h = img.size

        # Average all 4 corners for background color
        corners: list[tuple[int, ...]] = [
            img.getpixel((0, 0)),  # type: ignore[list-item]
            img.getpixel((w - 1, 0)),  # type: ignore[list-item]
            img.getpixel((0, h - 1)),  # type: ignore[list-item]
            img.getpixel((w - 1, h - 1)),  # type: ignore[list-item]
        ]
        bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

        # Per-pixel absolute difference from background
        bg_img = Image.new("RGB", img.size, bg)
        diff = ImageChops.difference(img, bg_img)

        # Foreground = any channel differs by more than EPSILON
        lut = [0 if x <= self._AUTOCROP_EPSILON else 255 for x in range(256)]
        r, g, b = diff.split()
        return ImageChops.lighter(
            ImageChops.lighter(r.point(lut), g.point(lut)),
            b.point(lut),
        )

    def _autocrop_scan_edges(self, fg_mask: Image.Image) -> tuple[int, int, int, int] | None:
        """Scan inward from each edge to find the autocrop bounding box.

        A row/column is considered background if its foreground pixel count
        does not exceed MISSPCT percent of the row/column length.
        Returns None if the image is entirely background or already tight.
        """
        w, h = fg_mask.size
        max_miss_row = w * self._AUTOCROP_MISSPCT // 100
        max_miss_col = h * self._AUTOCROP_MISSPCT // 100

        mask_bytes = fg_mask.tobytes()

        # Scan from top
        top = 0
        for y in range(h):
            if mask_bytes[y * w : (y + 1) * w].count(255) > max_miss_row:
                break
            top = y + 1

        if top >= h:
            return None  # entire image is background

        # Scan from bottom
        bottom = h
        for y in range(h - 1, top - 1, -1):
            if mask_bytes[y * w : (y + 1) * w].count(255) > max_miss_row:
                break
            bottom = y

        # Transpose mask for efficient column scanning (column x becomes row x)
        mask_t_bytes = fg_mask.transpose(Image.Transpose.TRANSPOSE).tobytes()

        # Scan from left
        left = 0
        for x in range(w):
            if mask_t_bytes[x * h : (x + 1) * h].count(255) > max_miss_col:
                break
            left = x + 1

        if left >= w:
            return None

        # Scan from right
        right = w
        for x in range(w - 1, left - 1, -1):
            if mask_t_bytes[x * h : (x + 1) * h].count(255) > max_miss_col:
                break
            right = x

        box = (left, top, right, bottom)
        if box == (0, 0, w, h):
            return None  # already tight, nothing to crop
        return box

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
