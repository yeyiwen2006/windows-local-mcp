"""Headless launch errors must not require dismissing a Windows dialog."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time

import pytest

from test_commands import commands, launch, finish, WINDOWS


@pytest.mark.parametrize("kind", ["dos", "small-offset", "past-end", "wrong-signature"])
@WINDOWS
def test_malformed_pe_is_rejected_before_createprocess(commands, tmp_path, monkeypatch, kind):
    import _winapi
    image = bytearray(128)
    image[:2] = b"MZ"
    image[60:64] = (64).to_bytes(4, "little")
    image[64:68] = b"PE\0\0"
    if kind == "dos":
        image[64:68] = b"NE\0\0"
    elif kind == "small-offset":
        image[60:64] = (4).to_bytes(4, "little")
    elif kind == "past-end":
        image[60:64] = (10000).to_bytes(4, "little")
    else:
        image[64:68] = b"xxxx"
    executable = tmp_path / "malformed.exe"
    executable.write_bytes(image)
    def never_called(*args, **kwargs):
        pytest.fail("Invalid images must be rejected before the native launch API")
    monkeypatch.setattr(_winapi, "CreateProcess", never_called)
    with pytest.raises(OSError):
        commands.start(str(executable), [], str(tmp_path))
    assert commands.status()["running"] == 0


@WINDOWS
def test_native_launch_restores_this_threads_error_mode(commands, tmp_path, monkeypatch):
    import _winapi
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetThreadErrorMode.argtypes = []
    kernel.GetThreadErrorMode.restype = wintypes.DWORD
    before = kernel.GetThreadErrorMode()
    calls = []
    def fail(*args, **kwargs):
        calls.append(kernel.GetThreadErrorMode())
        raise OSError("synthetic native launch failure")
    monkeypatch.setattr(_winapi, "CreateProcess", fail)
    with pytest.raises(OSError, match="synthetic"):
        launch(commands, tmp_path, "print('not run')")
    assert calls == [before | 0x8003]
    assert kernel.GetThreadErrorMode() == before
    assert commands.status()["running"] == 0


@WINDOWS
def test_timeout_before_resume_does_not_execute_command(commands, tmp_path, monkeypatch):
    from windows_local_mcp.commands import WindowsProcess
    original = WindowsProcess.__init__
    def slow_creation(self, *args, **kwargs):
        original(self, *args, **kwargs)
        time.sleep(1.1)
    monkeypatch.setattr(WindowsProcess, "__init__", slow_creation)
    marker = tmp_path / "must-not-run"
    job = launch(commands, tmp_path, f"from pathlib import Path;Path({str(marker)!r}).touch()", timeout_seconds=1)
    result = finish(commands, job)
    assert result["state"] == "timed_out" and not result["success"]
    assert not marker.exists()
