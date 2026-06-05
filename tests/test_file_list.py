"""Tests for the file list and CLI path expansion (file_list.py)."""

from __future__ import annotations

from pathlib import Path

from pxv.file_list import FileList, expand_paths


def test_navigation_wraps() -> None:
    fl = FileList([Path("a"), Path("b"), Path("c")])
    assert fl.current() == Path("a")
    assert fl.next() == Path("b")
    assert fl.next() == Path("c")
    assert fl.next() == Path("a")  # wrap forward
    assert fl.prev() == Path("c")  # wrap backward


def test_position_str_and_count() -> None:
    fl = FileList([Path("a"), Path("b")])
    assert fl.position_str() == "1/2"
    fl.next()
    assert fl.position_str() == "2/2"
    assert fl.count() == 2


def test_empty_list_is_safe() -> None:
    fl = FileList([])
    assert fl.current() is None
    assert fl.next() is None
    assert fl.prev() is None
    assert fl.position_str() == "0/0"
    assert fl.count() == 0


def test_index_setter_wraps() -> None:
    fl = FileList([Path("a"), Path("b"), Path("c")])
    fl.index = 5
    assert fl.index == 2
    fl.index = -1
    assert fl.index == 2


def test_add_deduplicates_by_resolved_path(tmp_path: Path) -> None:
    f1 = tmp_path / "a.png"
    f1.write_bytes(b"")
    f2 = tmp_path / "b.png"
    f2.write_bytes(b"")
    fl = FileList([])
    fl.add(f1)
    fl.add(f1)  # duplicate -> selects existing, no new entry
    assert fl.count() == 1
    fl.add(f2)
    assert fl.count() == 2
    assert fl.index == 1  # newly added becomes current


def test_expand_paths_directory_sorted_and_filtered(tmp_path: Path) -> None:
    (tmp_path / "b.png").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")  # non-image, must be filtered out
    result = expand_paths([str(tmp_path)])
    assert [p.name for p in result] == ["a.jpg", "b.png"]


def test_expand_paths_dedups_first_wins(tmp_path: Path) -> None:
    f = tmp_path / "a.png"
    f.write_bytes(b"")
    result = expand_paths([str(f), str(f)])
    assert len(result) == 1


def test_expand_paths_reports_missing(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "nope.png"
    result = expand_paths([str(missing)])
    assert result == []
    assert "skipping nonexistent" in capsys.readouterr().err
