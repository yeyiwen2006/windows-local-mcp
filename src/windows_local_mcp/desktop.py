"""Bounded Windows desktop operations using physical virtual-desktop coordinates.

No clipboard, shell, UIAccess, elevation, hooks, or desktop switching is used.
Desktop input is locked to an explicitly focused target process and remains subject to UIPI.
Screenshots never retarget input when the human switches to another application.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from functools import wraps
import io
import math
import os
import threading
import time
from typing import Callable


class DesktopError(RuntimeError):
    """The desktop is unavailable or Windows refused an operation."""


def _clear_expected_foreground(method):
    """Clear an observation even when validation fails before entering _operation."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        finally:
            self.expected_foreground_hwnd = None
    return wrapped


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}.")
    return value


def _duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("duration must be a finite number from 0.05 through 5 seconds.")
    result = float(value)
    if not math.isfinite(result) or not 0.05 <= result <= 5.0:
        raise ValueError("duration must be a finite number from 0.05 through 5 seconds.")
    return result


# Canonical names resolve to (virtual key, extended-key flag, modifier).
_KEYS = {
    "ctrl": (0x11, False, True), "shift": (0x10, False, True),
    "alt": (0x12, False, True), "win": (0x5B, True, True),
    "enter": (0x0D, False, False), "tab": (0x09, False, False),
    "escape": (0x1B, False, False), "space": (0x20, False, False),
    "backspace": (0x08, False, False), "delete": (0x2E, True, False),
    "insert": (0x2D, True, False), "home": (0x24, True, False),
    "end": (0x23, True, False), "pageup": (0x21, True, False),
    "pagedown": (0x22, True, False), "left": (0x25, True, False),
    "up": (0x26, True, False), "right": (0x27, True, False),
    "down": (0x28, True, False), "capslock": (0x14, False, False),
    "printscreen": (0x2C, True, False), "apps": (0x5D, True, False),
}
_KEYS.update({chr(i).lower(): (i, False, False) for i in range(65, 91)})
_KEYS.update({str(i): (0x30 + i, False, False) for i in range(10)})
_KEYS.update({f"f{i}": (0x6F + i, False, False) for i in range(1, 25)})
_ALIASES = {"control": "ctrl", "windows": "win", "super": "win",
            "return": "enter", "esc": "escape", "pgup": "pageup",
            "pgdn": "pagedown", "del": "delete"}

# Only modifiers and mouse buttons are queried; ordinary typed keys are not read.
_INPUT_BLOCKERS = (
    (0xA0, "Left Shift"), (0xA1, "Right Shift"),
    (0xA2, "Left Ctrl"), (0xA3, "Right Ctrl"),
    (0xA4, "Left Alt"), (0xA5, "Right Alt"),
    (0x5B, "Left Windows"), (0x5C, "Right Windows"),
    (0x01, "Left mouse button"), (0x02, "Right mouse button"),
    (0x04, "Middle mouse button"), (0x05, "Mouse X1"), (0x06, "Mouse X2"),
)


def _chord(keys: object) -> list[tuple[str, int, bool, bool]]:
    if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
        raise ValueError("keys must be a list containing 1 to 5 key names.")
    result = []
    for key in keys:
        if not isinstance(key, str) or len(key) > 16:
            raise ValueError("Every key must be a supported key name.")
        name = _ALIASES.get(key.lower(), key.lower())
        if name not in _KEYS:
            raise ValueError(f"Unsupported key: {key!r}; use type_text for characters.")
        if any(item[0] == name for item in result):
            raise ValueError("A chord cannot contain duplicate keys.")
        result.append((name, *_KEYS[name]))
    if sum(not item[3] for item in result) > 1:
        raise ValueError("A chord may contain modifiers and at most one ordinary key.")
    # Press modifiers before the ordinary key even if the caller lists it first.
    return sorted(result, key=lambda item: not item[3])


def _text_units(text: object) -> list[int]:
    if not isinstance(text, str) or not 1 <= len(text) <= 4000:
        raise ValueError("text must contain 1 to 4000 Unicode characters.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text) or "\x7f" in text:
        raise ValueError("text contains unsupported control characters.")
    try:
        raw = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-16-le")
    except UnicodeEncodeError as exc:
        raise ValueError("text contains an unpaired Unicode surrogate.") from exc
    return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]


def _point(x: object, y: object, monitors: list[dict]) -> tuple[int, int]:
    x = _integer(x, "x", -(2**31), 2**31 - 1)
    y = _integer(y, "y", -(2**31), 2**31 - 1)
    if not any(m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"]
               for m in monitors):
        raise ValueError("Coordinates must lie on a connected monitor in physical pixels.")
    return x, y


def _region(region: object, bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if region is None:
        return bounds
    if not isinstance(region, (tuple, list)) or len(region) != 4:
        raise ValueError("region must contain left, top, right, bottom.")
    left, top, right, bottom = (
        _integer(value, "region coordinate", -(2**31), 2**31 - 1) for value in region)
    if not (bounds[0] <= left < right <= bounds[2]
            and bounds[1] <= top < bottom <= bounds[3]):
        raise ValueError("region must be a positive rectangle inside the virtual desktop.")
    return left, top, right, bottom


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class _MONITORINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class Desktop:
    """One serialized desktop controller, with caller-supplied emergency stop checks.

    Instantiation initializes DPI awareness but sends no input and captures no pixels.
    Public operations are safe to call from different worker threads; each worker is
    explicitly made per-monitor aware before reading or moving screen coordinates.
    """

    expected_foreground_hwnd: int | None = None

    def __init__(self, check: Callable[[], None]):
        if os.name != "nt":
            raise DesktopError("Desktop control requires Windows 10 version 1703 or later.")
        if not callable(check):
            raise TypeError("check must be callable.")
        self._check = check
        self.expected_foreground_hwnd = None
        self.input_target: dict | None = None
        self._lock = threading.RLock()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self._configure()
        # This may return access denied when another component already selected DPI
        # awareness. The thread context below still provides physical coordinates.
        self._user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self._ensure_dpi()

    def _configure(self) -> None:
        u = self._user32
        signatures = {
            "SetProcessDpiAwarenessContext": ([ctypes.c_void_p], wintypes.BOOL),
            "SetThreadDpiAwarenessContext": ([ctypes.c_void_p], ctypes.c_void_p),
            "GetSystemMetrics": ([ctypes.c_int], ctypes.c_int),
            "OpenInputDesktop": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseDesktop": ([wintypes.HANDLE], wintypes.BOOL),
            "GetUserObjectInformationW": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "SystemParametersInfoW": ([wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT], wintypes.BOOL),
            "SendInput": ([wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int], wintypes.UINT),
            "GetAsyncKeyState": ([ctypes.c_int], wintypes.SHORT),
            "GetForegroundWindow": ([], wintypes.HWND),
            "IsWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "IsIconic": ([wintypes.HWND], wintypes.BOOL),
            "ShowWindowAsync": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetMonitorInfoW": ([wintypes.HANDLE, ctypes.POINTER(_MONITORINFOEX)], wintypes.BOOL),
        }
        try:
            for name, (args, result) in signatures.items():
                function = getattr(u, name)
                function.argtypes, function.restype = args, result
        except AttributeError as exc:
            raise DesktopError("Windows 10 version 1703 or later is required.") from exc
        self._monitor_callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        u.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                         self._monitor_callback, wintypes.LPARAM]
        u.EnumDisplayMonitors.restype = wintypes.BOOL
        self._window_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._window_callback, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
        k = self._kernel32
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.GetProcessTimes.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME)]
        k.GetProcessTimes.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL

        self._wts.WTSQuerySessionInformationW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        self._wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
        self._wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        self._wts.WTSFreeMemory.restype = None

    def _ensure_dpi(self) -> None:
        if not self._user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise DesktopError("Windows refused the per-monitor DPI context.")

    def _assert_desktop(self) -> None:
        # OpenInputDesktop alone is insufficient: it can succeed for a disconnected
        # session. Require WTSActive as well, without switching desktops or sessions.
        pointer, count = ctypes.c_void_p(), wintypes.DWORD()
        ok = self._wts.WTSQuerySessionInformationW(
            None, 0xFFFFFFFF, 8, ctypes.byref(pointer), ctypes.byref(count))
        try:
            if not ok or not pointer.value or count.value < ctypes.sizeof(ctypes.c_int):
                raise DesktopError("Cannot verify the interactive Windows session.")
            if ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int)).contents.value != 0:
                raise DesktopError("Windows session is disconnected or not active.")
        finally:
            if pointer.value:
                self._wts.WTSFreeMemory(pointer)
        desktop = self._user32.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            raise DesktopError("Input desktop unavailable; unlock Windows and dismiss UAC locally.")
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if not self._user32.GetUserObjectInformationW(
                desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
            ) or name.value.casefold() != "default":
                raise DesktopError("Input is refused on locked or secure Windows desktops.")
        finally:
            self._user32.CloseDesktop(desktop)
        screensaver = wintypes.BOOL()
        if not self._user32.SystemParametersInfoW(0x0072, 0, ctypes.byref(screensaver), 0):
            raise DesktopError("Cannot verify whether the screen saver is active.")
        if screensaver.value:
            raise DesktopError("Screen saver is active; restore the desktop locally.")

    def _checkpoint(self) -> None:
        self._check()
        self._assert_desktop()

    def _assert_expected_foreground(self) -> None:
        expected = self.expected_foreground_hwnd
        if expected is not None and int(self._user32.GetForegroundWindow() or 0) != expected:
            raise DesktopError("Foreground focus changed since the screenshot; take a fresh screenshot before input.")

    def _window_pid(self, hwnd: int) -> int:
        if not hwnd or not self._user32.IsWindow(hwnd):
            raise DesktopError("Target window disappeared.")
        pid = wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
            raise DesktopError("Cannot identify the target window process.")
        return int(pid.value)

    def _process_identity(self, pid: int) -> dict:
        handle = self._kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            raise DesktopError("Cannot verify the target process identity.")
        try:
            creation, exit_time, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            if not self._kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel), ctypes.byref(user)
            ):
                raise DesktopError("Cannot verify the target process creation time.")
            image = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(image))
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
                raise DesktopError("Cannot verify the target process executable path.")
            created = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            return {"pid": int(pid), "creation_time_100ns": created,
                    "image_path": os.path.normcase(image.value)}
        finally:
            self._kernel32.CloseHandle(handle)

    def _target_summary(self) -> dict | None:
        if not self.input_target:
            return None
        return {"hwnd": self.input_target["hwnd"], "pid": self.input_target["pid"],
                "title": self.input_target["title"]}

    def _target_matches_window(self, hwnd: int, *, verify_process: bool = False) -> bool:
        target = self.input_target
        if not target:
            return False
        try:
            pid = self._window_pid(hwnd)
            if pid != target["pid"]:
                return False
            if verify_process:
                identity = self._process_identity(pid)
                return (identity["creation_time_100ns"] == target["creation_time_100ns"]
                        and identity["image_path"] == target["image_path"])
            return True
        except DesktopError:
            return False

    def _assert_input_target(self, hwnd: int | None = None, *, verify_process: bool = False) -> None:
        target = self.input_target
        if not target:
            raise DesktopError(
                "No desktop input target is locked. Call desktop_windows, then desktop_focus_window "
                "before sending mouse or keyboard input.")
        foreground = int(hwnd if hwnd is not None else (self._user32.GetForegroundWindow() or 0))
        if not self._target_matches_window(foreground, verify_process=verify_process):
            title = target.get("title") or "(untitled window)"
            raise DesktopError(
                f"Desktop input is locked to {title!r} (PID {target['pid']}). "
                "The current foreground window belongs to another program or the target process changed. "
                "Screenshots do not change the input target. Return to the locked application or explicitly "
                "call desktop_focus_window to choose a new target.")

    def target_summary(self) -> dict | None:
        with self._operation():
            return self._target_summary()

    def validate_input_target(self, hwnd: int) -> dict:
        with self._operation():
            current = int(self._user32.GetForegroundWindow() or 0)
            if current != hwnd:
                raise DesktopError("Foreground focus changed since the screenshot; take a fresh screenshot before input.")
            self._assert_input_target(hwnd, verify_process=True)
            return self._target_summary() or {}

    def _held_inputs(self) -> list[str]:
        return [label for key, label in _INPUT_BLOCKERS
                if self._user32.GetAsyncKeyState(key) & 0x8000]

    def _wait_for_released_inputs(self, *, enforce_target: bool = True) -> None:
        # A click approving a tool, or a preceding SendInput key-up, can still be
        # in flight. Wait briefly for a stable idle state, without releasing any
        # keys on the user's behalf or overriding a real held key.
        deadline = time.monotonic() + 1.0
        idle_since = None
        last_held = []
        while True:
            self._checkpoint()
            self._assert_expected_foreground()
            if enforce_target:
                self._assert_input_target()
            held = self._held_inputs()
            now = time.monotonic()
            if held:
                last_held = held
                idle_since = None
            elif idle_since is None:
                idle_since = now
            elif now - idle_since >= 0.1:
                return
            if now >= deadline:
                names = ", ".join(held or last_held) or "an unsettled modifier/button state"
                raise DesktopError(
                    f"Input did not become idle within 1 second. Last detected held input: {names}. "
                    "Release it locally, take a fresh screenshot, then retry. No input was sent.")
            time.sleep(min(0.02, deadline - now))

    @contextmanager
    def _operation(self, *, input_action: bool = False, enforce_target: bool = True):
        with self._lock:
            try:
                self._ensure_dpi()
                self._checkpoint()
                if input_action:
                    self._wait_for_released_inputs(enforce_target=enforce_target)
                    if enforce_target:
                        self._assert_input_target(verify_process=True)
                    image = self._capture(self._bounds())
                    try:
                        if max(high for low, high in image.convert("RGB").getextrema()) <= 8:
                            raise DesktopError("Screen capture is black; input is refused until the desktop is visible.")
                    finally:
                        image.close()
                    self._checkpoint()
                    self._assert_expected_foreground()
                    if enforce_target:
                        self._assert_input_target(verify_process=True)
                yield
            finally:
                if input_action:
                    self.expected_foreground_hwnd = None

    def _bounds(self) -> tuple[int, int, int, int]:
        left, top, width, height = (self._user32.GetSystemMetrics(index)
                                    for index in (76, 77, 78, 79))
        if width <= 0 or height <= 0 or width * height > 64_000_000:
            raise DesktopError("The virtual desktop is unavailable or exceeds 64 million pixels.")
        return left, top, left + width, top + height

    def _monitors(self) -> list[dict]:
        result, failed = [], []

        def collect(handle, _dc, _rect, _data):
            info = _MONITORINFOEX()
            info.cbSize = ctypes.sizeof(info)
            if not self._user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                failed.append(True)
                return False
            rect = info.rcMonitor
            result.append({"device": info.szDevice, "left": rect.left, "top": rect.top,
                           "right": rect.right, "bottom": rect.bottom,
                           "width": rect.right - rect.left, "height": rect.bottom - rect.top,
                           "primary": bool(info.dwFlags & 1)})
            return True

        if not self._user32.EnumDisplayMonitors(None, None, self._monitor_callback(collect), 0) or failed:
            raise DesktopError("Windows failed to enumerate connected monitors.")
        if not result:
            raise DesktopError("No connected monitors were found.")
        return result

    def monitors(self) -> list[dict]:
        with self._operation():
            return self._monitors()

    def foreground_window(self) -> int:
        """Return the current foreground handle without changing the foreground."""
        with self._operation():
            return int(self._user32.GetForegroundWindow() or 0)

    def _window(self, hwnd: int) -> dict:
        title, rect = ctypes.create_unicode_buffer(1024), wintypes.RECT()
        self._user32.GetWindowTextW(hwnd, title, len(title))
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise DesktopError("Window disappeared or its rectangle cannot be read.")
        pid = self._window_pid(hwnd)
        return {"hwnd": int(hwnd), "title": title.value, "pid": pid,
                "left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom,
                "minimized": bool(self._user32.IsIconic(hwnd)),
                "foreground": hwnd == self._user32.GetForegroundWindow()}

    def windows(self) -> list[dict]:
        with self._operation():
            result = []

            def collect(hwnd, _data):
                if len(result) >= 256:
                    return False
                if self._user32.IsWindowVisible(hwnd):
                    try:
                        info = self._window(hwnd)
                        if info["title"]:
                            result.append(info)
                    except DesktopError:
                        pass  # Windows can close between enumeration and inspection.
                return True

            ok = self._user32.EnumWindows(self._window_callback(collect), 0)
            if not ok and len(result) < 256:
                raise DesktopError("Windows failed to enumerate visible windows.")
            return result

    @_clear_expected_foreground
    def focus_window(self, hwnd: int) -> dict:
        _integer(hwnd, "hwnd", 1, 2 ** (8 * ctypes.sizeof(ctypes.c_void_p)) - 1)
        with self._operation(input_action=True, enforce_target=False):
            if not self._user32.IsWindow(hwnd) or not self._user32.IsWindowVisible(hwnd):
                raise ValueError("hwnd must identify an existing visible window.")
            if self._user32.IsIconic(hwnd):
                self._user32.ShowWindowAsync(hwnd, 9)
            self._checkpoint()
            self._user32.SetForegroundWindow(hwnd)
            deadline = time.monotonic() + 0.5
            while self._user32.GetForegroundWindow() != hwnd:
                self._checkpoint()
                if time.monotonic() >= deadline:
                    raise DesktopError("Windows refused foreground focus; select the target window locally.")
                time.sleep(0.025)
            info = self._window(hwnd)
            identity = self._process_identity(info["pid"])
            self.input_target = {"hwnd": int(hwnd), "title": info["title"], **identity}
            return {**info, "input_target_locked": True}

    def _capture(self, bbox: tuple[int, int, int, int]):
        from PIL import ImageGrab
        try:
            return ImageGrab.grab(bbox=bbox, all_screens=True, include_layered_windows=True)
        except Exception as exc:
            raise DesktopError("Windows screen capture failed; the desktop must be unlocked and visible.") from exc

    def screenshot(self, region: tuple[int, int, int, int] | None = None,
                   max_width: int = 1600) -> tuple[bytes, dict]:
        _integer(max_width, "max_width", 64, 3840)
        with self._operation():
            bbox = _region(region, self._bounds())
            foreground = int(self._user32.GetForegroundWindow() or 0)
            image = self._capture(bbox)
            try:
                native_width, native_height = image.size
                scale = min(1.0, max_width / native_width,
                            math.sqrt(4_000_000 / (native_width * native_height)))
                output_size = max(1, round(native_width * scale)), max(1, round(native_height * scale))
                if output_size != image.size:
                    from PIL import Image
                    resized = image.resize(output_size, Image.Resampling.LANCZOS)
                    image.close()
                    image = resized
                output = io.BytesIO()
                image.save(output, format="PNG")
                self._checkpoint()
                if int(self._user32.GetForegroundWindow() or 0) != foreground:
                    raise DesktopError("Foreground focus changed during capture; take a fresh screenshot.")
                return output.getvalue(), {
                    "left": bbox[0], "top": bbox[1], "native_width": native_width,
                    "native_height": native_height, "output_width": image.width,
                    "output_height": image.height, "scale": image.width / native_width,
                    "scale_x": image.width / native_width, "scale_y": image.height / native_height,
                    "foreground_hwnd": foreground,
                    "input_target": self._target_summary(),
                    "input_allowed": self._target_matches_window(foreground, verify_process=True),
                    "coordinate_space": "physical_virtual_desktop",
                    "coordinate_mapping": "x = left + image_x / scale_x; y = top + image_y / scale_y",
                }
            finally:
                image.close()

    def _send(self, event: _INPUT, *, cleanup: bool = False) -> None:
        if not cleanup:
            self._checkpoint()
            self._assert_expected_foreground()
            self._assert_input_target()
        if self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)) != 1:
            raise DesktopError("Windows refused input; locked or elevated applications cannot be controlled.")

    def _mouse(self, flags: int, *, x: int = 0, y: int = 0, data: int = 0,
               cleanup: bool = False) -> None:
        self._send(_INPUT(type=0, mi=_MOUSEINPUT(x, y, data & 0xFFFFFFFF, flags, 0, 0)), cleanup=cleanup)

    def _key(self, vk: int, *, scan: int = 0, flags: int = 0, cleanup: bool = False) -> None:
        self._send(_INPUT(type=1, ki=_KEYBDINPUT(vk, scan, flags, 0, 0)), cleanup=cleanup)

    def _move(self, x: int, y: int) -> None:
        left, top, right, bottom = self._bounds()
        # Pixel centers avoid rounding to the neighboring pixel on large desktops.
        nx = min(65535, int(((x - left) + 0.5) * 65536 / (right - left)))
        ny = min(65535, int(((y - top) + 0.5) * 65536 / (bottom - top)))
        self._mouse(0x0001 | 0x8000 | 0x4000, x=nx, y=ny)

    @_clear_expected_foreground
    def move(self, x: int, y: int) -> dict:
        with self._operation(input_action=True):
            x, y = _point(x, y, self._monitors())
            self._move(x, y)
            return {"x": x, "y": y}

    @_clear_expected_foreground
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
        if not isinstance(button, str) or button not in ("left", "right", "middle"):
            raise ValueError("button must be left, right, or middle.")
        _integer(clicks, "clicks", 1, 3)
        with self._operation(input_action=True):
            x, y = _point(x, y, self._monitors())
            self._move(x, y)
            down, up = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}[button]
            for index in range(clicks):
                try:
                    self._mouse(down)
                finally:
                    self._mouse(up, cleanup=True)
                if index + 1 < clicks:
                    self._checkpoint()
                    time.sleep(0.08)
            return {"x": x, "y": y, "button": button, "clicks": clicks}

    @_clear_expected_foreground
    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> dict:
        duration = _duration(duration)
        with self._operation(input_action=True):
            monitors = self._monitors()
            _point(x1, y1, monitors)
            _point(x2, y2, monitors)
            steps = max(2, math.ceil(duration * 40))
            path = [(round(x1 + (x2 - x1) * i / steps), round(y1 + (y2 - y1) * i / steps))
                    for i in range(1, steps + 1)]
            for x, y in path:
                _point(x, y, monitors)
            self._move(x1, y1)
            start = time.monotonic()
            try:
                self._mouse(0x2)
                for index, (x, y) in enumerate(path, 1):
                    self._checkpoint()
                    remaining = start + duration * index / steps - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(remaining, 0.05))
                    self._move(x, y)
            finally:
                self._mouse(0x4, cleanup=True)
            return {"from": [x1, y1], "to": [x2, y2], "duration": duration}

    @_clear_expected_foreground
    def scroll(self, x: int, y: int, vertical: int = 0, horizontal: int = 0) -> dict:
        _integer(vertical, "vertical", -100, 100)
        _integer(horizontal, "horizontal", -100, 100)
        if vertical == 0 and horizontal == 0:
            raise ValueError("At least one scroll direction must be nonzero.")
        with self._operation(input_action=True):
            x, y = _point(x, y, self._monitors())
            self._move(x, y)
            if vertical:
                self._mouse(0x0800, data=vertical * 120)
            if horizontal:
                self._mouse(0x1000, data=horizontal * 120)
            return {"x": x, "y": y, "vertical": vertical, "horizontal": horizontal,
                    "units": "wheel notches; positive means up/right"}

    @_clear_expected_foreground
    def keypress(self, keys: list[str]) -> dict:
        chord = _chord(keys)
        with self._operation(input_action=True):
            pressed = []
            try:
                for _name, vk, extended, _modifier in chord:
                    # Record before sending so cleanup still runs on a partial failure.
                    pressed.append((vk, extended))
                    self._key(vk, flags=1 if extended else 0)
            finally:
                first_error = None
                for vk, extended in reversed(pressed):
                    try:
                        self._key(vk, flags=2 | (1 if extended else 0), cleanup=True)
                    except DesktopError as exc:
                        first_error = first_error or exc
                if first_error:
                    raise first_error
            return {"keys": [item[0] for item in chord]}

    @_clear_expected_foreground
    def type_text(self, text: str) -> dict:
        units = _text_units(text)
        with self._operation(input_action=True):
            foreground = self._user32.GetForegroundWindow()
            if not foreground:
                raise DesktopError("No foreground window can receive text.")
            deadline = time.monotonic() + 20
            for index, unit in enumerate(units):
                if time.monotonic() > deadline:
                    raise DesktopError(f"Text entry stopped after {index} UTF-16 units because the 20 second limit elapsed.")
                self._checkpoint()
                if self._user32.GetForegroundWindow() != foreground:
                    raise DesktopError(f"Text entry stopped after {index} UTF-16 units because foreground focus changed.")
                # Newlines/tabs use real keys; other code points use UTF-16 units,
                # including surrogate pairs for emoji and supplementary characters.
                vk, scan, flags = ((0x0D, 0, 0) if unit == 10 else
                                   (0x09, 0, 0) if unit == 9 else (0, unit, 4))
                try:
                    self._key(vk, scan=scan, flags=flags)
                finally:
                    self._key(vk, scan=scan, flags=flags | 2, cleanup=True)
            return {"characters": len(text), "utf16_units": len(units), "clipboard_used": False}
