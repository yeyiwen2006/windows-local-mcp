from __future__ import annotations

import codecs
import os
from pathlib import Path

import anyio
import pytest

from windows_local_mcp.files import Files, MAX_WRITE
from windows_local_mcp.guard import Guard
from windows_local_mcp.server import build_server
from windows_local_mcp.text_edit import replace_text_bytes


@pytest.fixture
def fs(tmp_path):
    return Files(Guard(tmp_path / "state"))


@pytest.mark.parametrize("encoding,bom,codec", [
    ("utf-8", b"", "utf-8"),
    ("utf-8-sig", codecs.BOM_UTF8, "utf-8"),
    ("utf-16", codecs.BOM_UTF16_LE, "utf-16-le"),
    ("utf-16", codecs.BOM_UTF16_BE, "utf-16-be"),
    ("gb18030", b"", "gb18030"),
])
def test_edit_preserves_encoding_bom_and_line_endings(fs, tmp_path, encoding, bom, codec):
    p = tmp_path / "中文.txt"
    original = bom + "第一行\r\n旧🙂文本\n末行".encode(codec)
    p.write_bytes(original)
    read = fs.read_text(str(p), encoding=encoding)
    result = fs.edit_text(str(p), "旧🙂文本", "新的中文🙂", read["version"], encoding)
    assert p.read_bytes() == bom + "第一行\r\n新的中文🙂\n末行".encode(codec)
    assert Path(result["backup_path"]).read_bytes() == original
    assert result["changed"] is True and result["replacements"] == 1
    assert (result["start_line"], result["end_line"], result["new_end_line"]) == (2, 2, 2)
    assert result["version"] == fs.info(str(p))["version"] != read["version"]
    assert "text" not in result


def test_multiline_and_deletion_summary(fs, tmp_path):
    p = tmp_path / "lines.txt"
    p.write_bytes(b"one\rtwo\rthree\nfour")
    result = fs.edit_text(str(p), "two\rthree", "new\nline\nextra", fs.info(str(p))["version"])
    assert (result["start_line"], result["end_line"], result["new_end_line"]) == (2, 3, 4)
    result = fs.edit_text(str(p), "new\nline\nextra", "", result["version"])
    assert p.read_bytes() == b"one\r\nfour"
    assert result["replacements"] == 1


def test_crlf_line_summary_counts_one_line_break():
    data, summary = replace_text_bytes(b"first\r\nlast", "first\r\n", "new\r\n", "utf-8")
    assert data == b"new\r\nlast"
    assert (summary["start_line"], summary["end_line"], summary["new_end_line"]) == (1, 1, 1)


@pytest.mark.parametrize("original,old,new", [
    (codecs.BOM_UTF8 + b"old", "\ufeffold", "new"),
    (b"old", "old", "\ufeffnew"),
])
def test_explicit_utf8_cannot_change_bom_state(original, old, new):
    with pytest.raises(ValueError, match="byte-order mark"):
        replace_text_bytes(original, old, new, "utf-8")


@pytest.mark.parametrize("contents,old,error", [
    ("abc", "", "empty"), ("abc", "missing", "not found"),
    ("repeat repeat", "repeat", "exactly once"), ("aaa", "aa", "overlapping"),
])
def test_rejected_match_leaves_original_and_no_backup(fs, tmp_path, contents, old, error):
    p = tmp_path / "input.txt"
    p.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        fs.edit_text(str(p), old, "new", fs.info(str(p))["version"])
    assert p.read_text(encoding="utf-8") == contents
    assert not (fs.guard.state / "backups").exists()


def test_identical_replacement_is_noop(fs, tmp_path):
    p = tmp_path / "same.txt"
    p.write_bytes(codecs.BOM_UTF8 + b"same\r\n")
    before = fs.info(str(p))
    result = fs.edit_text(str(p), "same", "same", before["version"])
    assert result["changed"] is False and result["replacements"] == 0
    assert result["backup_path"] is None and result["version"] == before["version"]
    assert result["modified_ns"] == before["modified_ns"]


def test_version_catches_change_with_restored_mtime(fs, tmp_path):
    p = tmp_path / "stale.txt"
    p.write_text("old", encoding="utf-8")
    before = fs.info(str(p))
    p.write_text("external old", encoding="utf-8")
    os.utime(p, ns=(p.stat().st_atime_ns, before["modified_ns"]))
    with pytest.raises(ValueError, match="changed"):
        fs.edit_text(str(p), "old", "new", before["version"])
    assert p.read_text(encoding="utf-8") == "external old"


def test_read_detects_change_during_read(fs, tmp_path, monkeypatch):
    p = tmp_path / "read.txt"
    p.write_text("before\n", encoding="utf-8")
    changed = False
    check = fs.guard.check

    def external_change():
        nonlocal changed
        check()
        if not changed:
            changed = True
            p.write_text("external longer\n", encoding="utf-8")

    monkeypatch.setattr(fs.guard, "check", external_change)
    with pytest.raises(ValueError, match="being read"):
        fs.read_text(str(p))


def test_change_between_edit_read_and_commit_is_rejected(fs, tmp_path, monkeypatch):
    p = tmp_path / "window.txt"
    p.write_text("old", encoding="utf-8")
    version = fs.info(str(p))["version"]
    commit = fs._write_bytes

    def external_change(*args, **kwargs):
        p.write_text("external edit", encoding="utf-8")
        return commit(*args, **kwargs)

    monkeypatch.setattr(fs, "_write_bytes", external_change)
    with pytest.raises(ValueError, match="changed"):
        fs.edit_text(str(p), "old", "new", version)
    assert p.read_text(encoding="utf-8") == "external edit"


@pytest.mark.parametrize("backup_changes_file", [False, True])
def test_edit_backup_failure_or_external_change_preserves_original(fs, tmp_path, monkeypatch, backup_changes_file):
    p = tmp_path / "backup.txt"
    p.write_text("old", encoding="utf-8")
    version = fs.info(str(p))["version"]
    backup = fs.backup

    def fail_or_change(path):
        if not backup_changes_file:
            raise OSError("disk full")
        result = backup(path)
        path.write_text("external during backup", encoding="utf-8")
        return result

    monkeypatch.setattr(fs, "backup", fail_or_change)
    with pytest.raises((OSError, ValueError)):
        fs.edit_text(str(p), "old", "new", version)
    assert p.read_text(encoding="utf-8") == ("external during backup" if backup_changes_file else "old")


def test_edit_rejects_invalid_encoding_and_size(fs, tmp_path):
    p = tmp_path / "invalid.txt"
    p.write_bytes(b"\xffold")
    with pytest.raises(UnicodeDecodeError):
        fs.edit_text(str(p), "old", "new", fs.info(str(p))["version"])
    assert p.read_bytes() == b"\xffold"
    p.write_bytes(b"a" * (MAX_WRITE + 1))
    with pytest.raises(ValueError, match="8 MiB"):
        fs.edit_text(str(p), "a", "b", fs.info(str(p))["version"])
    p.write_bytes(b"old")
    with pytest.raises(ValueError, match="8 MiB"):
        fs.edit_text(str(p), "old", "a" * (MAX_WRITE + 1), fs.info(str(p))["version"])
    assert p.read_bytes() == b"old"


def test_edit_respects_pause_and_protected_path(fs, tmp_path):
    p = tmp_path / "file.txt"
    p.write_text("old", encoding="utf-8")
    version = fs.info(str(p))["version"]
    fs.guard.pause()
    with pytest.raises(PermissionError, match="paused"):
        fs.edit_text(str(p), "old", "new", version)
    with pytest.raises(PermissionError, match="local-operator"):
        fs.edit_text(str(fs.guard.state / "PAUSED"), "paused", "new", version)


def test_edit_tool_schema_and_content_free_audit(fs, tmp_path):
    server, _runtime = build_server(fs.guard)
    p = tmp_path / "mcp.txt"
    p.write_text("private old body", encoding="utf-8")

    async def invoke():
        tools = {tool.name: tool for tool in await server.list_tools()}
        edit = tools["edit_text_file"]
        assert edit.annotations.readOnlyHint is False
        assert "expected_version" in edit.inputSchema["required"]
        await server.call_tool("edit_text_file", {"path": str(p), "old_text": "private old body",
                                                "new_text": "private new body",
                                                "expected_version": fs.info(str(p))["version"]})

    anyio.run(invoke)
    assert p.read_text(encoding="utf-8") == "private new body"
    audit = next((fs.guard.state / "audit").glob("*.jsonl")).read_text(encoding="utf-8")
    assert "private old body" not in audit and "private new body" not in audit
