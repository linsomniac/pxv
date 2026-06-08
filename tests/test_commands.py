"""Display-free tests for pure command logic (no Tk root)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pxv import commands
from pxv.file_list import FileList


def _stub_app(n: int, *, load_ok: bool) -> tuple[SimpleNamespace, list[int]]:
    fl = FileList([Path(f"img{i}.png") for i in range(n)])
    loaded: list[int] = []

    def load_current() -> bool:
        loaded.append(fl.index)
        return load_ok

    app = SimpleNamespace(file_list=fl, browser=None, load_current=load_current)
    return app, loaded


def test_cmd_show_index_jumps_and_loads() -> None:
    app, loaded = _stub_app(3, load_ok=True)
    commands.cmd_show_index(app, 2)
    assert app.file_list.index == 2
    assert loaded == [2]


def test_cmd_show_index_out_of_range_is_noop() -> None:
    app, loaded = _stub_app(2, load_ok=True)
    commands.cmd_show_index(app, 5)
    assert app.file_list.index == 0
    assert loaded == []


def test_cmd_show_index_rolls_back_on_failed_load() -> None:
    app, loaded = _stub_app(3, load_ok=False)
    app.file_list.index = 0
    commands.cmd_show_index(app, 2)
    assert app.file_list.index == 0  # rolled back to the still-displayed image
    assert loaded == [2]
