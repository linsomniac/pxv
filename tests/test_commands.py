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

    app = SimpleNamespace(
        file_list=fl,
        browser=None,
        load_current=load_current,
        annotation_palette=None,
        annotations_unsaved=False,
    )
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


def test_keybindings_table_lists_browse() -> None:
    from pxv.dialogs import KEYBINDINGS

    keys = [k for k, _desc in KEYBINDINGS]
    assert "b" in keys


def test_keybindings_lists_draw_key_distinct_from_background_toggle() -> None:
    from pxv.dialogs import KEYBINDINGS

    by_key = {k: desc for k, desc in KEYBINDINGS if k}
    assert "draw" in by_key["d"].lower()  # KeyError here = the d row is missing
    assert "background" in by_key["D"].lower()  # D keeps its own, distinct row


def test_keybindings_has_draw_mode_section() -> None:
    from pxv.dialogs import KEYBINDINGS

    descriptions = [desc for _key, desc in KEYBINDINGS]
    assert any("drawing palette is open" in d for d in descriptions)  # section header
    by_key = {k: desc for k, desc in KEYBINDINGS if k}
    assert "1-8" in by_key  # the stable tool numbering
    assert "Delete / Backspace" in by_key


# --- draw-mode command gating (annotation_gate) -------------------------------


class _StubPalette:
    def __init__(self, dragging: bool = False) -> None:
        self.is_dragging = dragging
        self.ended: list[bool] = []

    def _end_session(self, bake: bool) -> None:
        self.ended.append(bake)


def _gate_app(*, palette: object | None = None, unsaved: bool = False) -> SimpleNamespace:
    app = SimpleNamespace(
        annotation_palette=palette,
        annotations_unsaved=unsaved,
        titles=[],
    )
    app.show_temp_title = app.titles.append
    return app


def test_gate_mutate_consumes_with_hint_while_palette_open() -> None:
    app = _gate_app(palette=_StubPalette())
    assert commands.annotation_gate(app, "mutate") is False
    assert "drawing palette" in app.titles[0]
    assert commands.annotation_gate(_gate_app(), "mutate") is True


def test_gate_zoom_consumed_only_during_drag() -> None:
    assert (
        commands.annotation_gate(_gate_app(palette=_StubPalette(dragging=True)), "zoom") is False
    )
    assert commands.annotation_gate(_gate_app(palette=_StubPalette()), "zoom") is True
    assert commands.annotation_gate(_gate_app(), "zoom") is True


def test_gate_navigate_consumed_during_drag() -> None:
    app = _gate_app(palette=_StubPalette(dragging=True), unsaved=True)
    assert commands.annotation_gate(app, "navigate") is False
    assert app.annotations_unsaved is True  # no prompt, no teardown mid-drag


def test_gate_navigate_prompts_then_discards(monkeypatch: object) -> None:
    answers = iter([False, True])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        commands, "messagebox", SimpleNamespace(askyesno=lambda *a, **k: next(answers))
    )
    palette = _StubPalette()
    app = _gate_app(palette=palette, unsaved=True)
    assert commands.annotation_gate(app, "navigate") is False  # declined
    assert app.annotations_unsaved is True and palette.ended == []
    assert commands.annotation_gate(app, "navigate") is True  # confirmed
    assert app.annotations_unsaved is False
    assert palette.ended == [False]  # session cancelled, never baked


def test_gate_navigate_silently_ends_empty_session() -> None:
    palette = _StubPalette()
    app = _gate_app(palette=palette, unsaved=False)
    assert commands.annotation_gate(app, "navigate") is True  # nothing at stake
    assert palette.ended == [False]  # but no orphaned canvas state either


def test_gate_navigate_clears_post_bake_flag_without_session(monkeypatch: object) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        commands, "messagebox", SimpleNamespace(askyesno=lambda *a, **k: True)
    )
    app = _gate_app(palette=None, unsaved=True)  # baked, then closed the palette
    assert commands.annotation_gate(app, "navigate") is True
    assert app.annotations_unsaved is False  # no re-prompt on the next image


def test_cmd_open_consumed_during_annotation_drag() -> None:
    app = SimpleNamespace(
        annotation_palette=_StubPalette(dragging=True), annotations_unsaved=False
    )
    # Must return before touching the file dialog — calling it headless would raise.
    commands.cmd_open(app)


def test_cmd_show_index_prompts_through_the_gate(monkeypatch: object) -> None:
    prompts: list[bool] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        commands,
        "messagebox",
        SimpleNamespace(askyesno=lambda *a, **k: prompts.append(True) or True),
    )
    app, loaded = _stub_app(3, load_ok=True)
    app.annotations_unsaved = True  # the Visual Schnauzer activation path is gated too
    commands.cmd_show_index(app, 2)
    assert prompts == [True]
    assert app.annotations_unsaved is False
    assert loaded == [2]
