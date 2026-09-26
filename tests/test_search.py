import codecs
from pathlib import Path

import pytest

from windows_local_mcp.files import Files
from windows_local_mcp.guard import Guard
from windows_local_mcp import search as searching


@pytest.fixture
def fs(tmp_path):
    guard = Guard(tmp_path / "state")
    yield Files(guard)
    guard.close()


def test_recursive_literal_search_and_name_filter(fs, tmp_path):
    folder = tmp_path / "nested"
    folder.mkdir()
    target = folder / "中文.py"
    target.write_bytes("第一行\r\n值 = '你好🙂 [x]'\r\n第三行\n".encode())
    (folder / "ignored.txt").write_text("你好🙂 [x]", encoding="utf-8")
    result = searching.search_text(fs, str(tmp_path), "你好🙂 [x]", name_pattern="*.py")
    assert [(item["path"], item["line"], item["column"]) for item in result["results"]] == [
        (str(target), 2, 6)]
    assert result["results"][0]["text"] == "值 = '你好🙂 [x]'"
    assert result["results"][0]["version"].startswith("v1:")
    assert result["skipped"]["protected_or_inaccessible"] == 1
    found = searching.search_files(fs, str(tmp_path), "*.py")
    assert [r["path"] for r in found["results"]] == [str(target)]


@pytest.mark.parametrize("encoding,data", [
    ("utf-8-sig", codecs.BOM_UTF8 + "中文🙂\n目标".encode()),
    ("utf-16", codecs.BOM_UTF16_BE + "中文🙂\n目标".encode("utf-16-be")),
    ("gb18030", "中文🙂\n目标".encode("gb18030")),
])
def test_search_supported_encodings(fs, tmp_path, encoding, data):
    path = tmp_path / "encoded.txt"
    path.write_bytes(data)
    result = searching.search_text(fs, str(tmp_path), "目标", encoding=encoding)
    assert result["results"][0]["line"] == 2
    assert result["results"][0]["text"] == "目标"


def test_excluded_directories_can_be_requested_explicitly(fs, tmp_path):
    folder = tmp_path / "node_modules"
    folder.mkdir()
    (folder / "found.txt").write_text("needle", encoding="utf-8")
    assert searching.search_text(fs, str(tmp_path), "needle")["results"] == []
    result = searching.search_text(fs, str(tmp_path), "needle", exclude_dirs=[])
    assert len(result["results"]) == 1
    assert result["skipped"]["protected_or_inaccessible"] == 1


def test_links_and_service_state_are_not_searched(fs, tmp_path):
    (fs.guard.state / "private.txt").write_text("needle", encoding="utf-8")
    with pytest.raises(PermissionError):
        searching.search_files(fs, str(fs.guard.state))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("needle", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    result = searching.search_text(fs, str(root), "needle")
    assert result["results"] == []
    assert result["skipped"]["link"] == 1
    with pytest.raises(ValueError, match="root"):
        searching.search_files(fs, str(link))


def test_limits_are_explicit_and_snippets_show_late_matches(fs, tmp_path):
    (tmp_path / "long.txt").write_text("x" * 1000 + "needle\nneedle\n", encoding="utf-8")
    result = searching.search_text(fs, str(tmp_path), "needle", max_results=1)
    assert result["truncated"] and result["stop_reason"] == "result_limit"
    row = result["results"][0]
    assert row["column"] == 1001 and "needle" in row["text"]
    assert len(row["text"]) <= 400 and row["snippet_truncated"]
    limited = searching.search_text(fs, str(tmp_path), "needle", max_bytes=1)
    assert limited["truncated"] and limited["stop_reason"] == "byte_limit"
    assert limited["bytes_read"] == 0


def test_invalid_and_binary_files_are_skipped_not_lossily_decoded(fs, tmp_path):
    (tmp_path / "binary").write_bytes(b"needle\0")
    (tmp_path / "bad").write_bytes(b"needle\xff")
    result = searching.search_text(fs, str(tmp_path), "needle")
    assert result["results"] == []
    assert result["skipped"]["binary"] == 1
    assert result["skipped"]["decode_error"] == 1
    assert not result["complete"]


def test_scan_time_entry_and_output_limits(fs, tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("needle", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle", encoding="utf-8")
    result = searching.search_files(fs, str(tmp_path), max_entries=1)
    assert result["stop_reason"] == "entry_limit" and result["entries_scanned"] == 1
    monkeypatch.setattr(searching, "MAX_RESULT_CHARS", 1)
    assert searching.search_files(fs, str(tmp_path))["stop_reason"] == "output_limit"
    times = iter((0, 2))
    monkeypatch.setattr(searching.time, "monotonic", lambda: next(times))
    assert searching.search_files(fs, str(tmp_path), timeout_seconds=1)["stop_reason"] == "time_limit"


def test_pause_during_file_read_is_not_swallowed_as_skip(fs, tmp_path, monkeypatch):
    (tmp_path / "large.txt").write_text("needle\n" * 20000, encoding="utf-8")
    original = searching.Search.read
    def pause_before_read(search, *args):
        fs.guard.pause()
        return original(search, *args)
    monkeypatch.setattr(searching.Search, "read", pause_before_read)
    with pytest.raises(PermissionError, match="paused"):
        searching.search_text(fs, str(tmp_path), "needle")


def test_changed_files_do_not_return_stale_matches(fs, tmp_path, monkeypatch):
    path = tmp_path / "race.txt"
    path.write_text("needle", encoding="utf-8")
    original = searching.Search.read
    def change_before_read(search, candidate, before, budget):
        candidate.write_text("changed externally", encoding="utf-8")
        return original(search, candidate, before, budget)
    monkeypatch.setattr(searching.Search, "read", change_before_read)
    result = searching.search_text(fs, str(tmp_path), "needle")
    assert not result["results"] and result["skipped"]["changed"] == 1


def test_case_insensitive_literal_search(fs, tmp_path):
    (tmp_path / "case.txt").write_text("Some NEEDLE?", encoding="utf-8")
    assert not searching.search_text(fs, str(tmp_path), "needle?")["results"]
    result = searching.search_text(fs, str(tmp_path), "needle?", case_sensitive=False)
    assert result["results"][0]["column"] == 6


@pytest.mark.parametrize("kwargs", [
    {"max_results": 0}, {"max_entries": -1}, {"timeout_seconds": 31},
    {"name_pattern": "../*"}, {"exclude_dirs": ["a/b"]},
])
def test_invalid_search_bounds_rejected(fs, tmp_path, kwargs):
    with pytest.raises(ValueError):
        searching.search_files(fs, str(tmp_path), **kwargs)
