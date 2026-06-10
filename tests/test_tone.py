"""Tests for the pure tone-mapping math (levels, LUT composition, auto-levels)."""

from __future__ import annotations

from pxv.tone import LevelsChannel, levels_lut

IDENTITY = list(range(256))


def test_levels_channel_identity() -> None:
    assert LevelsChannel().is_identity()
    assert not LevelsChannel(in_black=1).is_identity()
    assert not LevelsChannel(gamma=2.0).is_identity()
    assert not LevelsChannel(out_white=200).is_identity()


def test_levels_lut_identity() -> None:
    assert levels_lut(LevelsChannel()) == IDENTITY


def test_levels_lut_endpoints_and_clamp() -> None:
    lut = levels_lut(LevelsChannel(in_black=64, in_white=192))
    assert lut[0] == 0 and lut[64] == 0  # at/below the black point
    assert lut[192] == 255 and lut[255] == 255  # at/above the white point
    assert lut[128] == 128  # midpoint stays put at gamma 1


def test_levels_lut_gamma_brightens_midtones() -> None:
    lut = levels_lut(LevelsChannel(gamma=2.0))
    # t**(1/2): input 64 (t~0.251) -> ~0.501 -> ~128
    assert 126 <= lut[64] <= 130
    assert lut[0] == 0 and lut[255] == 255


def test_levels_lut_output_range() -> None:
    lut = levels_lut(LevelsChannel(out_black=64, out_white=192))
    assert lut[0] == 64 and lut[255] == 192


def test_levels_lut_inverted_output() -> None:
    lut = levels_lut(LevelsChannel(out_black=255, out_white=0))
    assert lut[0] == 255 and lut[255] == 0


def test_levels_lut_degenerate_span_guard() -> None:
    lut = levels_lut(LevelsChannel(in_black=128, in_white=128))
    assert all(0 <= v <= 255 for v in lut)  # must not divide by zero
