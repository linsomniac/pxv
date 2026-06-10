"""Tests for the enhancement params and pipeline (enhancements.py)."""

from __future__ import annotations

from PIL import Image

from pxv.enhancements import (
    EnhancementParams,
    _apply_hue_rotation,
    _build_lut,
    apply_enhancements,
)
from pxv.tone import IDENTITY_CURVE, LevelsChannel


def test_is_identity_default() -> None:
    assert EnhancementParams().is_identity() is True


def test_is_identity_false_when_changed() -> None:
    p = EnhancementParams()
    p.brightness = 1.5
    assert p.is_identity() is False


def test_reset_returns_to_identity() -> None:
    p = EnhancementParams()
    p.brightness = 2.0
    p.blur = 3.0
    p.hue_offset = 90
    p.reset()
    assert p.is_identity() is True


def test_build_lut_identity() -> None:
    lut = _build_lut(1.0, 1.0, 1.0, 1.0, 1.0)
    assert len(lut) == 768
    assert lut == list(range(256)) * 3


def test_build_lut_brightness_doubles_and_clamps() -> None:
    lut = _build_lut(2.0, 1.0, 1.0, 1.0, 1.0)
    assert lut[50] == 100
    assert lut[200] == 255  # clamped at 255


def test_build_lut_per_channel_balance() -> None:
    lut = _build_lut(1.0, 1.0, 0.5, 1.0, 1.0)
    assert lut[100] == 50  # red channel halved
    assert lut[256 + 100] == 100  # green channel unchanged


def test_build_lut_gamma_brightens_midtones() -> None:
    lut = _build_lut(1.0, 2.0, 1.0, 1.0, 1.0)
    assert lut[0] == 0
    assert lut[255] == 255
    assert lut[64] > 64  # gamma > 1 lifts midtones


def test_hue_rotation_zero_is_noop() -> None:
    img = Image.new("RGB", (2, 2), (255, 0, 0))
    assert _apply_hue_rotation(img, 0) is img


def test_hue_rotation_shifts_red_toward_cyan() -> None:
    img = Image.new("RGB", (2, 2), (255, 0, 0))
    out = _apply_hue_rotation(img, 180)
    r, g, b = out.getpixel((0, 0))
    assert r < g and r < b  # red is no longer the dominant channel


def test_apply_enhancements_identity_returns_equal_copy() -> None:
    img = Image.new("RGB", (4, 4), (90, 120, 150))
    out = apply_enhancements(img, EnhancementParams())
    assert out is not img
    assert out.tobytes() == img.tobytes()


def test_apply_enhancements_brightness_raises_values() -> None:
    img = Image.new("RGB", (4, 4), (100, 100, 100))
    p = EnhancementParams()
    p.brightness = 1.5
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0))[0] > 100


def test_blur_applied_even_at_low_zoom() -> None:
    # Regression (1.0.1): blur must gate on the slider value, not the zoom-scaled
    # radius, so a nonzero blur still applies when zoom < 1.
    img = Image.new("RGB", (10, 10), (0, 0, 0))
    img.paste(Image.new("RGB", (5, 10), (255, 255, 255)), (5, 0))  # sharp vertical edge
    sharp = apply_enhancements(img, EnhancementParams(), zoom=0.5)
    p = EnhancementParams()
    p.blur = 2.0
    blurred = apply_enhancements(img, p, zoom=0.5)
    assert blurred.tobytes() != sharp.tobytes()


def test_params_identity_covers_levels() -> None:
    p = EnhancementParams()
    assert p.is_identity()
    p.levels_r = LevelsChannel(in_black=10)
    assert not p.is_identity()
    p.reset()
    assert p.is_identity()


def test_apply_enhancements_master_levels() -> None:
    img = Image.new("RGB", (2, 2), (64, 128, 192))
    p = EnhancementParams()
    p.levels_master = LevelsChannel(in_black=64, in_white=192)
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0)) == (0, 128, 255)


def test_apply_enhancements_per_channel_levels() -> None:
    img = Image.new("RGB", (2, 2), (100, 100, 100))
    p = EnhancementParams()
    p.levels_r = LevelsChannel(out_black=255, out_white=0)  # invert R only
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0)) == (155, 100, 100)


def test_apply_enhancements_master_before_channel_levels() -> None:
    # Master maps 128 -> 50 (out_white=100); the R channel's in_black=100 then
    # cuts 50 to 0. The reversed order would give R ~18, so this pins the
    # spec's fixed composition order: master levels BEFORE channel levels.
    img = Image.new("RGB", (1, 1), (128, 128, 128))
    p = EnhancementParams()
    p.levels_master = LevelsChannel(out_white=100)
    p.levels_r = LevelsChannel(in_black=100)
    out = apply_enhancements(img, p)
    px = out.getpixel((0, 0))
    assert px[0] == 0
    assert px[1] == 50 and px[2] == 50  # master only on G/B


def test_params_identity_covers_curves() -> None:
    p = EnhancementParams()
    assert p.is_identity()
    p.curve_g = ((0, 0), (128, 200), (255, 255))
    assert not p.is_identity()
    p.reset()
    assert p.is_identity()
    assert p.curve_g == IDENTITY_CURVE


def test_apply_enhancements_master_curve_inverts() -> None:
    img = Image.new("RGB", (2, 2), (10, 100, 200))
    p = EnhancementParams()
    p.curve_master = ((0, 255), (255, 0))
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0)) == (245, 155, 55)


def test_apply_enhancements_levels_before_curves() -> None:
    # Levels map 128 -> 50 (out_white=100); the master curve's flat-200 floor
    # then lifts everything to 200. Reversed order would curve first
    # (128 stays under the flat) then compress 200 -> 78. Pins the spec order:
    # levels before curves.
    img = Image.new("RGB", (1, 1), (128, 128, 128))
    p = EnhancementParams()
    p.levels_master = LevelsChannel(out_white=100)
    p.curve_master = ((0, 200), (255, 255))
    out = apply_enhancements(img, p)
    assert out.getpixel((0, 0))[0] >= 200


def test_apply_enhancements_lut_resolution_independent() -> None:
    # The whole tone stack is per-pixel: the same color must map identically
    # at any image size (this is why preview == save for LUT-only params).
    p = EnhancementParams()
    p.levels_master = LevelsChannel(in_black=20, gamma=1.7)
    p.curve_r = ((0, 0), (100, 180), (255, 255))
    small = apply_enhancements(Image.new("RGB", (2, 2), (90, 140, 30)), p)
    large = apply_enhancements(Image.new("RGB", (64, 64), (90, 140, 30)), p)
    assert small.getpixel((0, 0)) == large.getpixel((32, 32))
