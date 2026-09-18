import base64
import json
from pathlib import Path

import pytest

from windows_local_mcp.files import Files, valid_local_path
from windows_local_mcp.guard import Guard, PROJECT


@pytest.fixture
def fs(tmp_path):
    return Files(Guard(tmp_path / "state"))


def test_chinese_replace_backup_and_conflict(fs, tmp_path):
    p = tmp_path / "中文文件.txt"
    with fs.guard.action("write", {"path": str(p)}):
        first = fs.write(str(p), "你好，世界\n第一版")
    with pytest.raises(FileExistsError):
        fs.write(str(p), "must not replace")
    with pytest.raises(ValueError, match="changed"):
        fs.write(str(p), "must not replace", overwrite=True, expected_modified_ns=1)
    replacement = fs.write(str(p), "第二版🙂", overwrite=True, expected_modified_ns=first["modified_ns"])
    assert p.read_text(encoding="utf-8") == "第二版🙂"
    assert Path(replacement["backup_path"]).read_text(encoding="utf-8") == "你好，世界\n第一版"
    assert fs.read_text(str(p))["text"] == "第二版🙂"


def test_backup_failure_preserves_original(fs, tmp_path, monkeypatch):
    p = tmp_path / "file.txt"
    p.write_text("original", encoding="utf-8")
    monkeypatch.setattr(fs, "backup", lambda p: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        fs.write(str(p), "changed", overwrite=True)
    assert p.read_text(encoding="utf-8") == "original"


def test_changed_during_backup_is_not_overwritten(fs, tmp_path, monkeypatch):
    p = tmp_path / "race.txt"
    p.write_text("before", encoding="utf-8")
    original_backup = fs.backup
    def changed(path):
        result = original_backup(path)
        path.write_text("concurrent editor change", encoding="utf-8")
        return result
    monkeypatch.setattr(fs, "backup", changed)
    with pytest.raises(ValueError, match="during backup"):
        fs.write(str(p), "our change", overwrite=True)
    assert p.read_text(encoding="utf-8") == "concurrent editor change"


def test_binary_and_text_pagination(fs, tmp_path):
    p = tmp_path / "bytes.bin"
    fs.write(str(p), base64.b64encode(bytes(range(256))).decode(), encoding="base64")
    result = fs.read_binary(str(p), 10, 20)
    assert base64.b64decode(result["base64"]) == bytes(range(10, 30))
    assert result["next_offset"] == 30
    txt = tmp_path / "lines.txt"
    txt.write_text("第一行\n第二行\n第三行", encoding="utf-8")
    assert fs.read_text(str(txt), 1, 2)["next_line"] == 3
    assert fs.read_text(str(txt), 3, 2)["text"] == "第三行"


@pytest.mark.parametrize("path", ["relative.txt", r"C:relative.txt", r"\\server\share\x", r"\\.\PhysicalDrive0", r"C:\x.txt:stream", r"C:\NUL", "C:\\ambiguous.\\file"])
def test_special_windows_paths_rejected(path):
    with pytest.raises(ValueError):
        valid_local_path(path)


def test_control_paths_and_directory_tree_are_protected(fs):
    for value in (fs.guard.state, fs.guard.state / "credentials.json"):
        with pytest.raises(PermissionError):
            fs.path(str(value))
    with pytest.raises(PermissionError):
        fs.path(str(PROJECT / "pyproject.toml"), mutation=True)
    for value in (Path.home(), Path(PROJECT.anchor), PROJECT.parent):
        with pytest.raises(PermissionError):
            fs.protect_tree(value)


def test_recycle_failure_never_permanently_deletes(fs, tmp_path, monkeypatch):
    p = tmp_path / "retain.txt"
    p.write_text("keep", encoding="utf-8")
    monkeypatch.setattr("send2trash.send2trash", lambda _: (_ for _ in ()).throw(OSError("unavailable")))
    with pytest.raises(OSError):
        fs.recycle(str(p))
    assert p.exists()


def test_pause_blocks_and_audit_excludes_contents(fs, tmp_path):
    p = tmp_path / "audit.txt"
    with fs.guard.action("write_file", {"path": str(p), "characters": 20}):
        fs.write(str(p), "private body 中文")
    record = next((fs.guard.state / "audit").glob("*.jsonl")).read_text(encoding="utf-8")
    assert "private body" not in record
    assert len(record.splitlines()) == 2
    fs.guard.pause()
    with pytest.raises(PermissionError):
        with fs.guard.action("write_file"):
            fs.write(str(p), "bad", overwrite=True)
    assert p.read_text(encoding="utf-8") == "private body 中文"
    fs.guard.paused_file.unlink()
    fs.guard.check()
