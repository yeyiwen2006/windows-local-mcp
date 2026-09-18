import os
from pathlib import Path

import pytest

from windows_local_mcp.files import Files
from windows_local_mcp.guard import Guard


def test_ads_is_retained_by_rejecting_overwrite(tmp_path):
    p = tmp_path / "download.txt"
    p.write_text("original", encoding="utf-8")
    Path(str(p) + ":Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3", encoding="utf-8")
    fs = Files(Guard(tmp_path / "state"))
    with pytest.raises(ValueError, match="alternate data streams"):
        fs.write(str(p), "new", overwrite=True)
    assert p.read_text(encoding="utf-8") == "original"
    assert "ZoneId=3" in Path(str(p) + ":Zone.Identifier").read_text(encoding="utf-8")


def test_state_directory_acl_and_no_arbitrary_acl_change(tmp_path):
    import win32security
    state = tmp_path / "state"
    Guard(state)
    sd = win32security.GetFileSecurity(str(state), win32security.DACL_SECURITY_INFORMATION)
    assert sd.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
    arbitrary = tmp_path / "personal"
    arbitrary.mkdir()
    (arbitrary / "existing.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="non-service"):
        Guard(arbitrary)


def test_reparse_point_rejected_before_resolve(tmp_path, monkeypatch):
    from types import SimpleNamespace
    fs = Files(Guard(tmp_path / "state"))
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(st_file_attributes=0x400))
    with pytest.raises(ValueError, match="symlink or junction"):
        fs.path(str(tmp_path / "link"), mutation=True)


def test_protected_dacl_is_preserved_on_overwrite(tmp_path):
    import win32api
    import win32con
    import win32security
    import ntsecuritycon
    p = tmp_path / "private.txt"
    p.write_text("private", encoding="utf-8")
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    acl = win32security.ACL()
    acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid)
    win32security.SetNamedSecurityInfo(str(p), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None)
    fs = Files(Guard(tmp_path / "state"))
    fs.write(str(p), "replacement", overwrite=True)
    after = win32security.GetFileSecurity(str(p), win32security.DACL_SECURITY_INFORMATION)
    assert after.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
    result_acl = after.GetSecurityDescriptorDacl()
    assert result_acl.GetAceCount() == 1
    assert result_acl.GetAce(0) == acl.GetAce(0)
