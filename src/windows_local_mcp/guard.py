"""Operator stop, serialized actions and content-free local audit records."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from . import __version__

PROJECT = Path(__file__).resolve().parents[2]


def state_directory() -> Path:
    return Path(os.environ.get("WINDOWS_LOCAL_MCP_STATE", str(PROJECT / ".local"))).absolute()


class Guard:
    def __init__(self, state: Path | None = None):
        raw_state = state or state_directory()
        if raw_state.is_symlink() or raw_state.is_junction():
            raise ValueError("State directory must not be a symlink or junction")
        self.state = raw_state.resolve()
        if self.state == Path(self.state.anchor) or self.state == Path.home() or self.state == PROJECT or self.state in PROJECT.parents:
            raise ValueError("State must be a dedicated service directory")
        marker = self.state / ".windows-local-mcp-state"
        if self.state.exists() and self.state != PROJECT / ".local" and not marker.exists() and any(self.state.iterdir()):
            raise ValueError("Refusing to change permissions of an existing non-service directory")
        self.state.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import win32api
            import win32con
            import win32security
            import ntsecuritycon
            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
            try:
                sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            finally:
                token.Close()
            acl = win32security.ACL()
            for principal in (sid, win32security.ConvertStringSidToSid("S-1-5-18")):
                acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 3, ntsecuritycon.FILE_ALL_ACCESS, principal)
            win32security.SetNamedSecurityInfo(str(self.state), win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, acl, None)
        marker.write_text("windows-local-mcp\n", encoding="utf-8")
        self.paused_file = self.state / "PAUSED"
        self.stopped = threading.Event()
        self.lock = threading.RLock()
        self.hotkey_ready = False
        self.hotkey_error: str | None = None
        self._hotkey_thread_id = None

    def check(self) -> None:
        if self.stopped.is_set() or self.paused_file.exists():
            raise PermissionError("Service paused locally. The operator must resume it on this PC.")

    def pause(self) -> dict:
        # Set the in-memory flag first, including when disk writing fails.
        self.stopped.set()
        self.paused_file.write_text("paused\n", encoding="utf-8")
        self.stopped.clear()  # The persistent marker now owns the paused state.
        return {"paused": True}

    def status(self) -> dict:
        return {
            "version": __version__,
            "paused": self.stopped.is_set() or self.paused_file.exists(),
            "permissions": "all local files accessible to the current Windows user",
            "transport": "stdio only; authenticate the remote caller using Secure MCP Tunnel",
            "hotkey": "Ctrl+Alt+F11", "hotkey_registered": self.hotkey_ready,
            "hotkey_error": self.hotkey_error,
            "audit_directory": str(self.state / "audit"),
            "backup_directory": str(self.state / "backups"),
        }

    def audit(self, record: dict) -> None:
        folder = self.state / "audit"
        folder.mkdir(exist_ok=True)
        now = datetime.now(timezone.utc)
        record = {"utc": now.isoformat(), **record}
        # Callers supply only explicit metadata, never tool argument dictionaries.
        with (folder / f"{now:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    @contextmanager
    def action(self, name: str, metadata: dict | None = None):
        with self.lock:
            self.check()
            event = {"id": uuid4().hex, "tool": name, **(metadata or {})}
            # If the audit cannot be written, refuse to perform the action.
            self.audit({**event, "result": "started"})
            try:
                yield
            except BaseException as exc:
                self.audit({**event, "result": "failed", "error_type": type(exc).__name__})
                raise
            else:
                self.audit({**event, "result": "completed"})

    def start_hotkey(self) -> None:
        if os.name != "nt":
            self.hotkey_error = "Windows is required"
            return
        ready = threading.Event()

        def listen():
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.GetMessageW.restype = wintypes.BOOL
            self._hotkey_thread_id = kernel32.GetCurrentThreadId()
            # F12 is reserved by Windows. MOD_NOREPEAT | MOD_CONTROL | MOD_ALT.
            if not user32.RegisterHotKey(None, 1, 0x4003, 0x7A):
                self.hotkey_error = f"Registration failed ({ctypes.get_last_error()}); use Pause.ps1"
                ready.set()
                return
            self.hotkey_ready = True
            ready.set()
            msg = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == 0x0312:
                        try:
                            self.pause()
                        except OSError:
                            pass  # The in-memory stop flag is already set.
            finally:
                user32.UnregisterHotKey(None, 1)
                self.hotkey_ready = False

        threading.Thread(target=listen, name="emergency-stop", daemon=True).start()
        ready.wait(2)
        if not self.hotkey_ready and not self.hotkey_error:
            self.hotkey_error = "Hotkey registration timed out; use Pause.ps1"

    def close(self) -> None:
        if os.name == "nt" and self._hotkey_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, 0x0012, 0, 0)
