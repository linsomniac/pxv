"""Tests for the pxv command-line entry point.

AIDEV-NOTE: argparse's ``--version`` action prints and raises SystemExit before
``tk.Tk()`` is constructed, so this runs headlessly with no display.
"""

from __future__ import annotations

import pytest

import pxv
from pxv.app import _build_parser, main
from pxv.slideshow import DEFAULT_SLIDESHOW_SECONDS


def test_slideshow_absent_is_none() -> None:
    args = _build_parser().parse_args([])
    assert args.slideshow is None
    assert args.fullscreen is False


def test_slideshow_bare_flag_uses_default() -> None:
    args = _build_parser().parse_args(["--slideshow"])
    assert args.slideshow == DEFAULT_SLIDESHOW_SECONDS


def test_slideshow_with_value() -> None:
    args = _build_parser().parse_args(["--slideshow", "2"])
    assert args.slideshow == 2.0


def test_fullscreen_flag() -> None:
    args = _build_parser().parse_args(["--fullscreen"])
    assert args.fullscreen is True


def test_version_flag_prints_version_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pxv", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    output = capsys.readouterr()
    assert f"pxv {pxv.__version__}" in (output.out + output.err)
