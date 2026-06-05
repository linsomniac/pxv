"""Tests for the pxv command-line entry point.

AIDEV-NOTE: argparse's ``--version`` action prints and raises SystemExit before
``tk.Tk()`` is constructed, so this runs headlessly with no display.
"""

from __future__ import annotations

import pytest

import pxv
from pxv.app import main


def test_version_flag_prints_version_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pxv", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    output = capsys.readouterr()
    assert f"pxv {pxv.__version__}" in (output.out + output.err)
