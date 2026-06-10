"""Enhancement parameters and the image enhancement pipeline.

AIDEV-NOTE: The apply_enhancements pipeline order matters:
  Contrast -> Saturation -> Hue rotation -> Combined LUT (brightness+gamma+RGB+levels+curves) -> Blur -> Sharpen
The combined LUT merges brightness, gamma, per-channel color balance, and levels into a single
Image.point() call with a 768-entry lookup table for performance.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter

from pxv.tone import (
    IDENTITY_CURVE,
    CurvePoints,
    LevelsChannel,
    compose_luts,
    curve_lut,
    levels_lut,
)


@dataclass
class EnhancementParams:
    """All enhancement slider values. Defaults are identity (no change)."""

    brightness: float = 1.0  # 0.0-3.0
    contrast: float = 1.0  # 0.0-3.0
    gamma: float = 1.0  # 0.1-5.0
    saturation: float = 1.0  # 0.0-3.0
    hue_offset: int = 0  # 0-359 degrees
    r_balance: float = 1.0  # 0.0-2.0
    g_balance: float = 1.0  # 0.0-2.0
    b_balance: float = 1.0  # 0.0-2.0
    sharpen: float = 1.0  # 0.0-3.0
    blur: float = 0.0  # 0.0-10.0
    levels_master: LevelsChannel = LevelsChannel()
    levels_r: LevelsChannel = LevelsChannel()
    levels_g: LevelsChannel = LevelsChannel()
    levels_b: LevelsChannel = LevelsChannel()
    curve_master: CurvePoints = IDENTITY_CURVE
    curve_r: CurvePoints = IDENTITY_CURVE
    curve_g: CurvePoints = IDENTITY_CURVE
    curve_b: CurvePoints = IDENTITY_CURVE

    def is_identity(self) -> bool:
        """Return True if all parameters are at their default (no-op) values."""
        return (
            self.brightness == 1.0
            and self.contrast == 1.0
            and self.gamma == 1.0
            and self.saturation == 1.0
            and self.hue_offset == 0
            and self.r_balance == 1.0
            and self.g_balance == 1.0
            and self.b_balance == 1.0
            and self.sharpen == 1.0
            and self.blur == 0.0
            and self.levels_master.is_identity()
            and self.levels_r.is_identity()
            and self.levels_g.is_identity()
            and self.levels_b.is_identity()
            and self.curve_master == IDENTITY_CURVE
            and self.curve_r == IDENTITY_CURVE
            and self.curve_g == IDENTITY_CURVE
            and self.curve_b == IDENTITY_CURVE
        )

    def reset(self) -> None:
        """Reset all parameters to defaults."""
        self.brightness = 1.0
        self.contrast = 1.0
        self.gamma = 1.0
        self.saturation = 1.0
        self.hue_offset = 0
        self.r_balance = 1.0
        self.g_balance = 1.0
        self.b_balance = 1.0
        self.sharpen = 1.0
        self.blur = 0.0
        self.levels_master = LevelsChannel()
        self.levels_r = LevelsChannel()
        self.levels_g = LevelsChannel()
        self.levels_b = LevelsChannel()
        self.curve_master = IDENTITY_CURVE
        self.curve_r = IDENTITY_CURVE
        self.curve_g = IDENTITY_CURVE
        self.curve_b = IDENTITY_CURVE


# AIDEV-NOTE: Slider metadata used by the enhancement dialog to build sliders.
# Format: (attr_name, label, from_, to, default, resolution, is_int)
SLIDER_SPECS: list[tuple[str, str, float, float, float, float, bool]] = [
    ("brightness", "Brightness", 0.0, 3.0, 1.0, 0.01, False),
    ("contrast", "Contrast", 0.0, 3.0, 1.0, 0.01, False),
    ("gamma", "Gamma", 0.1, 5.0, 1.0, 0.01, False),
    ("sharpen", "Sharpen", 0.0, 3.0, 1.0, 0.01, False),
    ("blur", "Blur", 0.0, 10.0, 0.0, 0.1, False),
]

COLOR_SLIDER_SPECS: list[tuple[str, str, float, float, float, float, bool]] = [
    ("saturation", "Saturation", 0.0, 3.0, 1.0, 0.01, False),
    ("hue_offset", "Hue", 0, 359, 0, 1, True),
    ("r_balance", "Red", 0.0, 2.0, 1.0, 0.01, False),
    ("g_balance", "Green", 0.0, 2.0, 1.0, 0.01, False),
    ("b_balance", "Blue", 0.0, 2.0, 1.0, 0.01, False),
]


def _build_lut(
    brightness: float, gamma: float, r_bal: float, g_bal: float, b_bal: float
) -> list[int]:
    """Build a 768-entry LUT combining brightness, gamma, and per-channel balance.

    AIDEV-NOTE: This merges three operations into one Image.point() call.
    The LUT has 256 entries per channel (R, G, B) = 768 total.
    Formula per channel: clamp(((i/255)^(1/gamma) * brightness * channel_balance) * 255)
    """
    lut: list[int] = []
    inv_gamma = 1.0 / gamma if gamma != 0 else 1.0
    for channel_bal in (r_bal, g_bal, b_bal):
        for i in range(256):
            val = (i / 255.0) ** inv_gamma * brightness * channel_bal
            lut.append(max(0, min(255, int(val * 255 + 0.5))))
    return lut


def _apply_hue_rotation(img: Image.Image, offset: int) -> Image.Image:
    """Rotate hue by offset degrees (0-359) via HSV conversion."""
    if offset == 0:
        return img
    hsv = img.convert("HSV")
    h, s, v = hsv.split()
    # AIDEV-NOTE: Hue channel is 0-255 in Pillow's HSV, mapping to 0-360 degrees.
    # We shift by (offset / 360) * 256 and wrap with modulo.
    shift = int(offset * 256 / 360 + 0.5)
    lut = [(i + shift) % 256 for i in range(256)]
    h = h.point(lut)
    result = Image.merge("HSV", (h, s, v))
    return result.convert("RGB")


def apply_enhancements(
    img: Image.Image, params: EnhancementParams, *, zoom: float = 1.0
) -> Image.Image:
    """Apply the full enhancement pipeline to an image. Returns a new image.

    AIDEV-NOTE: zoom scales the blur radius so the preview (scale-then-enhance)
    approximates the save (enhance at full res). At 50% zoom the image has half the
    pixels, so halving the radius produces an equivalent visual blur. Sharpen uses
    ImageEnhance.Sharpness — a fixed 3x3 convolution with no radius — so it CANNOT be
    scaled the same way; its strength is pixel-relative, which means the live Sharpen
    preview is only approximate and may differ from the full-resolution saved result.
    """
    if params.is_identity():
        return img.copy()

    result = img

    # 1. Contrast
    if params.contrast != 1.0:
        result = ImageEnhance.Contrast(result).enhance(params.contrast)

    # 2. Saturation
    if params.saturation != 1.0:
        result = ImageEnhance.Color(result).enhance(params.saturation)

    # 3. Hue rotation
    if params.hue_offset != 0:
        result = _apply_hue_rotation(result, params.hue_offset)

    # 4. Combined LUT pass (brightness + gamma + RGB balance + levels + curves)
    levels_active = not (
        params.levels_master.is_identity()
        and params.levels_r.is_identity()
        and params.levels_g.is_identity()
        and params.levels_b.is_identity()
    )
    curves_active = not (
        params.curve_master == IDENTITY_CURVE
        and params.curve_r == IDENTITY_CURVE
        and params.curve_g == IDENTITY_CURVE
        and params.curve_b == IDENTITY_CURVE
    )
    needs_lut = (
        params.brightness != 1.0
        or params.gamma != 1.0
        or params.r_balance != 1.0
        or params.g_balance != 1.0
        or params.b_balance != 1.0
        or levels_active
        or curves_active
    )
    if needs_lut:
        base = _build_lut(
            params.brightness, params.gamma, params.r_balance, params.g_balance, params.b_balance
        )
        if levels_active or curves_active:
            # AIDEV-NOTE: Fixed composition order per the 2026-06-10 design:
            # base (brightness+gamma+balance) -> master levels -> channel
            # levels -> master curve -> channel curve.
            master_lv = levels_lut(params.levels_master)
            master_cv = curve_lut(params.curve_master)
            lut: list[int] = []
            channel_tone = (
                (params.levels_r, params.curve_r),
                (params.levels_g, params.curve_g),
                (params.levels_b, params.curve_b),
            )
            for idx, (ch_lv, ch_cv) in enumerate(channel_tone):
                lut.extend(
                    compose_luts(
                        base[idx * 256 : (idx + 1) * 256],
                        master_lv,
                        levels_lut(ch_lv),
                        master_cv,
                        curve_lut(ch_cv),
                    )
                )
        else:
            lut = base
        result = result.point(lut)

    # 5. Blur (radius scaled by zoom for preview parity)
    # AIDEV-NOTE: Gate only on the unscaled slider value, not on the zoom-scaled
    # radius — otherwise at low zoom the blur is silently dropped from the preview
    # while the full-resolution save still applies it.
    if params.blur > 0.0:
        result = result.filter(ImageFilter.GaussianBlur(radius=params.blur * zoom))

    # 6. Sharpen
    if params.sharpen != 1.0:
        result = ImageEnhance.Sharpness(result).enhance(params.sharpen)

    return result
