"""Tests for the pure tone-mapping math (levels, LUT composition, auto-levels)."""

from __future__ import annotations

import pytest

from pxv.tone import (
    IDENTITY_CURVE,
    LevelsChannel,
    auto_levels,
    compose_luts,
    curve_lut,
    equalize_curve,
    gamma_to_mid,
    gray_balance_gammas,
    levels_lut,
    mid_to_gamma,
)

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


def test_compose_luts() -> None:
    assert compose_luts(IDENTITY, IDENTITY) == IDENTITY
    invert = [255 - i for i in range(256)]
    assert compose_luts(invert, invert) == IDENTITY
    half = [i // 2 for i in range(256)]
    assert compose_luts(half, invert)[0] == 255  # invert(half(0))
    assert compose_luts(invert, half)[0] == 127  # half(invert(0))


def test_auto_levels_finds_black_white_points() -> None:
    hist = [0] * 768
    for c in range(3):
        hist[c * 256 + 30] = 100
        hist[c * 256 + 220] = 100
    r, g, b = auto_levels(hist, clip_percent=0.5)
    for ch in (r, g, b):
        assert ch.in_black == 30
        assert ch.in_white == 220
        assert ch.gamma == 1.0 and ch.out_black == 0 and ch.out_white == 255


def test_auto_levels_empty_histogram_is_identity() -> None:
    r, g, b = auto_levels([0] * 768)
    assert r.is_identity() and g.is_identity() and b.is_identity()


def test_auto_levels_degenerate_single_bin() -> None:
    hist = [0] * 768
    hist[128] = 1000  # R only; G/B empty
    r, g, b = auto_levels(hist)
    assert r.is_identity()  # hi <= lo -> identity fallback
    assert g.is_identity() and b.is_identity()


def test_gamma_mid_roundtrip() -> None:
    for gamma in (0.2, 0.5, 1.0, 2.0, 5.0):
        x = gamma_to_mid(0, 255, gamma)
        assert mid_to_gamma(0, 255, x) == pytest.approx(gamma, rel=1e-3)


def test_mid_to_gamma_clamps_at_extremes() -> None:
    assert mid_to_gamma(0, 255, 0.0) == 10.0  # far left -> max gamma
    assert mid_to_gamma(0, 255, 255.0) == 0.1  # far right -> min gamma


def test_auto_levels_skips_hot_pixels_via_accumulation() -> None:
    # 3 hot pixels at 255 are under the 0.5% clip budget and must be skipped;
    # a regression replacing the accumulation with "first nonzero bin" fails here.
    hist = [0] * 768
    for c in range(3):
        hist[c * 256 + 50] = 10000
        hist[c * 256 + 150] = 10000
        hist[c * 256 + 255] = 3
    r, g, b = auto_levels(hist, clip_percent=0.5)
    for ch in (r, g, b):
        assert ch.in_black == 50
        assert ch.in_white == 150


def test_levels_lut_monotonic_for_normal_params() -> None:
    for ch in (
        LevelsChannel(),
        LevelsChannel(in_black=30, in_white=200),
        LevelsChannel(gamma=0.4),
        LevelsChannel(gamma=2.5, in_black=10, in_white=240, out_black=20, out_white=235),
    ):
        lut = levels_lut(ch)
        assert all(lut[i + 1] >= lut[i] for i in range(255)), ch


def test_curve_lut_identity() -> None:
    assert curve_lut(IDENTITY_CURVE) == IDENTITY


def test_curve_lut_two_point_inversion() -> None:
    lut = curve_lut(((0, 255), (255, 0)))
    assert lut == [255 - i for i in range(256)]


def test_curve_lut_s_curve_monotone_no_overshoot() -> None:
    lut = curve_lut(((0, 0), (64, 16), (192, 239), (255, 255)))
    assert lut[0] == 0 and lut[255] == 255
    assert lut[64] == 16 and lut[192] == 239  # interpolant passes through points
    assert all(lut[i + 1] >= lut[i] for i in range(255))  # no overshoot wiggles


def test_curve_lut_solarize_allowed() -> None:
    lut = curve_lut(((0, 0), (128, 255), (255, 0)))
    assert lut[0] == 0 and lut[128] == 255 and lut[255] == 0
    assert all(lut[i + 1] >= lut[i] for i in range(127))  # rises to the peak
    assert all(lut[i + 1] <= lut[i] for i in range(128, 255))  # falls after it


def test_curve_lut_flat_extension_outside_x_range() -> None:
    lut = curve_lut(((50, 100), (200, 150)))
    assert lut[0] == 100 and lut[49] == 100
    assert lut[201] == 150 and lut[255] == 150


def test_curve_lut_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        curve_lut(((0, 0),))
    with pytest.raises(ValueError):
        curve_lut(((0, 0), (0, 255)))  # x not strictly increasing


def test_equalize_curve_two_spike_histogram() -> None:
    hist = [0] * 256
    hist[50] = 100
    hist[200] = 100
    points = list(equalize_curve(hist))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    assert xs[0] == 0 and xs[-1] == 255
    assert all(xs[i + 1] > xs[i] for i in range(len(xs) - 1))
    assert ys[0] == 0 and ys[-1] == 255
    # Between the spikes the CDF plateaus at 0.5 -> y == 128.
    assert all(y == 128 for x, y in points if 64 <= x <= 191)


def test_equalize_curve_flat_histogram_is_near_identity() -> None:
    points = equalize_curve([100] * 256)
    assert all(abs(y - x) <= 2 for x, y in points)


def test_equalize_curve_empty_histogram_is_identity() -> None:
    assert equalize_curve([0] * 256) == IDENTITY_CURVE


def test_equalize_curve_feeds_curve_lut() -> None:
    hist = [0] * 256
    hist[50] = 100
    hist[200] = 100
    lut = curve_lut(equalize_curve(hist))
    assert len(lut) == 256 and all(0 <= v <= 255 for v in lut)


def test_gray_balance_neutral_sample_is_identity() -> None:
    assert gray_balance_gammas((128, 128, 128)) == (1.0, 1.0, 1.0)


def test_gray_balance_neutralizes_a_cast() -> None:
    sample = (200, 128, 100)
    gr, gg, gb = gray_balance_gammas(sample)
    assert gr < 1.0 < gb  # red too bright -> darken; blue too dark -> brighten
    # Applying the per-channel gammas maps each sampled channel near the mean.
    outs = [levels_lut(LevelsChannel(gamma=g))[v] for g, v in ((gr, 200), (gg, 128), (gb, 100))]
    assert max(outs) - min(outs) <= 3


def test_gray_balance_extreme_channels_fall_back_to_identity() -> None:
    # Channels at 0 or 255 (or an extreme mean) can't be gamma-balanced.
    gr, _gg, gb = gray_balance_gammas((0, 128, 255))
    assert gr == 1.0 and gb == 1.0
    assert gray_balance_gammas((255, 255, 255)) == (1.0, 1.0, 1.0)
