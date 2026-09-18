"""Validation and cleanup tests. Never capture or interact with the real desktop."""

from contextlib import contextmanager
import ctypes
import math
import os
import threading
import unittest
from unittest.mock import Mock, patch

from windows_local_mcp.desktop import (
    Desktop, DesktopError, _INPUT, _chord, _duration, _integer, _point, _region, _text_units,
)


MONITORS = [
    {"left": -1920, "top": 0, "right": 0, "bottom": 1080},
    {"left": 0, "top": 200, "right": 2560, "bottom": 1640},
]


class ValidationTests(unittest.TestCase):
    def test_physical_coordinates_support_negative_origins_and_reject_gaps(self):
        self.assertEqual(_point(-1920, 0, MONITORS), (-1920, 0))
        self.assertEqual(_point(2559, 1639, MONITORS), (2559, 1639))
        for point in [(2560, 400), (-1921, 0), (1, 100), (True, 300), (1.0, 300)]:
            with self.subTest(point=point), self.assertRaises(ValueError):
                _point(*point, MONITORS)

    def test_region_is_bounded_and_requires_positive_area(self):
        bounds = (-1920, 0, 2560, 1640)
        self.assertEqual(_region(None, bounds), bounds)
        self.assertEqual(_region((-1900, 20, -100, 1000), bounds), (-1900, 20, -100, 1000))
        for region in [(0, 0, 0, 1), (0, 0, 3000, 100), (1, 2, 3), (0, 0, True, 1)]:
            with self.subTest(region=region), self.assertRaises(ValueError):
                _region(region, bounds)

    def test_reject_unbounded_duration_and_non_integer_counts(self):
        self.assertEqual(_duration(5), 5.0)
        for duration in [math.inf, math.nan, -1, 6, True, "1"]:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                _duration(duration)
        for value in [True, 1.5, "1", -1, 101]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _integer(value, "wheel", 0, 100)

    def test_chords_canonicalize_and_press_modifiers_first(self):
        chord = _chord(["a", "Control", "SHIFT"])
        self.assertEqual([item[0] for item in chord], ["ctrl", "shift", "a"])
        for keys in [[], "ctrl+a", ["ctrl", "control"], ["a", "b"], ["未知"], [1]]:
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                _chord(keys)

    def test_unicode_text_preserves_chinese_and_surrogate_pairs(self):
        self.assertEqual(_text_units("中😀\r\n\t"), [0x4E2D, 0xD83D, 0xDE00, 10, 9])
        for text in ["", "\0", "\x1b", "\ud800", "x" * 4001, None]:
            with self.subTest(text=repr(text)[:40]), self.assertRaises(ValueError):
                _text_units(text)

    @unittest.skipUnless(os.name == "nt", "Win32 ABI sizes only apply to Windows")
    def test_sendinput_abi_matches_pointer_width(self):
        self.assertEqual(ctypes.sizeof(_INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


class ReleaseTests(unittest.TestCase):
    """A fake controller proves cancellation cannot leave our modifier keys held."""

    def setUp(self):
        self.desktop = object.__new__(Desktop)

        @contextmanager
        def operation(**_kwargs):
            yield

        self.desktop._operation = operation

    def test_all_modifiers_released_when_emergency_check_interrupts(self):
        events = []

        def fake_key(vk, **kwargs):
            events.append((vk, kwargs))
            if vk == 0x41 and not kwargs.get("cleanup"):
                raise RuntimeError("Paused")

        self.desktop._key = fake_key
        with self.assertRaisesRegex(RuntimeError, "Paused"):
            self.desktop.keypress(["ctrl", "shift", "a"])
        self.assertEqual([vk for vk, args in events if args.get("cleanup")], [0x41, 0x10, 0x11])

    def test_one_cleanup_failure_does_not_skip_other_modifier_releases(self):
        events = []

        def fake_key(vk, **kwargs):
            if kwargs.get("cleanup"):
                events.append(vk)
                if vk == 0x41:
                    raise DesktopError("Input blocked")

        self.desktop._key = fake_key
        with self.assertRaises(DesktopError):
            self.desktop.keypress(["ctrl", "shift", "a"])
        self.assertEqual(events, [0x41, 0x10, 0x11])

    def test_drag_releases_mouse_when_paused(self):
        self.desktop._monitors = lambda: MONITORS
        self.desktop._move = Mock()
        self.desktop._checkpoint = Mock(side_effect=RuntimeError("Paused"))
        events = []
        self.desktop._mouse = lambda flags, **kwargs: events.append((flags, kwargs))
        with self.assertRaisesRegex(RuntimeError, "Paused"):
            self.desktop.drag(-200, 500, 200, 500)
        self.assertEqual(events, [(0x2, {}), (0x4, {"cleanup": True})])

    def test_drag_rejects_a_monitor_gap_before_moving(self):
        self.desktop._monitors = lambda: MONITORS
        self.desktop._move = Mock()
        with self.assertRaises(ValueError):
            self.desktop.drag(-100, 10, 100, 210)
        self.desktop._move.assert_not_called()

    def test_text_stops_on_focus_change_and_releases_last_unit(self):
        self.desktop._user32 = Mock()
        self.desktop._user32.GetForegroundWindow.side_effect = [10, 10, 11]
        self.desktop._checkpoint = Mock()
        self.desktop._key = Mock()
        with self.assertRaisesRegex(DesktopError, "focus changed"):
            self.desktop.type_text("ab")
        self.assertEqual(self.desktop._key.call_count, 2)
        self.assertTrue(self.desktop._key.call_args.kwargs["cleanup"])


class ForegroundObservationTests(unittest.TestCase):
    def setUp(self):
        self.desktop = object.__new__(Desktop)
        self.desktop.expected_foreground_hwnd = 10
        self.desktop.input_target = {
            "hwnd": 10, "root_hwnd": 10, "pid": 100, "title": "Target",
            "creation_time_100ns": 123, "image_path": r"c:\\target.exe",
        }
        self.desktop._window_pid = Mock(return_value=100)
        self.desktop._root_owner = Mock(return_value=10)
        self.desktop._process_identity = Mock(return_value={
            "pid": 100, "creation_time_100ns": 123, "image_path": r"c:\\target.exe",
        })
        self.desktop._lock = threading.RLock()
        self.desktop._ensure_dpi = Mock()
        self.desktop._checkpoint = Mock()
        self.desktop._bounds = Mock(return_value=(0, 0, 100, 100))
        self.desktop._user32 = Mock()
        self.desktop._user32.GetAsyncKeyState.return_value = 0
        self.desktop._user32.GetForegroundWindow.return_value = 10
        image = Mock()
        image.convert.return_value.getextrema.return_value = [(0, 255)] * 3

        def capture(_bbox):
            self.desktop._user32.GetForegroundWindow.return_value = 11
            return image

        self.desktop._capture = capture

    def test_switch_during_black_screen_check_prevents_all_input(self):
        with self.assertRaisesRegex(DesktopError, "since the screenshot"):
            self.desktop.keypress(["ctrl", "a"])
        self.desktop._user32.SendInput.assert_not_called()
        self.assertIsNone(self.desktop.expected_foreground_hwnd)

    def test_key_down_rechecks_focus_after_checkpoint_and_cleanup_is_allowed(self):
        self.desktop._user32.GetForegroundWindow.return_value = 11
        self.desktop._user32.SendInput.return_value = 1
        with self.assertRaisesRegex(DesktopError, "since the screenshot"):
            self.desktop._key(0x41)
        self.desktop._user32.SendInput.assert_not_called()
        self.desktop._key(0x41, flags=2, cleanup=True)
        self.desktop._user32.SendInput.assert_called_once()

    def test_validation_error_clears_expected_foreground(self):
        with self.assertRaises(ValueError):
            self.desktop.keypress([])
        self.assertIsNone(self.desktop.expected_foreground_hwnd)


class TargetLockTests(unittest.TestCase):
    def setUp(self):
        self.desktop = object.__new__(Desktop)
        self.desktop._user32 = Mock()
        self.desktop._user32.GetForegroundWindow.return_value = 10
        self.desktop.input_target = {
            "hwnd": 10, "root_hwnd": 10, "pid": 100, "title": "Editor",
            "creation_time_100ns": 123, "image_path": r"c:\\editor.exe",
        }
        self.desktop._window_pid = Mock(side_effect=lambda hwnd: {10: 100, 11: 100, 12: 100, 20: 200}[hwnd])
        self.desktop._root_owner = Mock(side_effect=lambda hwnd: {10: 10, 11: 10, 12: 12, 20: 20}[hwnd])
        self.desktop._process_identity = Mock(return_value={
            "pid": 100, "creation_time_100ns": 123, "image_path": r"c:\\editor.exe",
        })

    def test_no_target_requires_explicit_focus(self):
        self.desktop.input_target = None
        with self.assertRaisesRegex(DesktopError, "No desktop input target"):
            self.desktop._assert_input_target(10, verify_process=True)

    def test_fresh_screenshot_of_another_program_does_not_retarget_input(self):
        with self.assertRaisesRegex(DesktopError, "locked to"):
            self.desktop._assert_input_target(20, verify_process=True)

    def test_owned_dialog_in_same_target_process_is_allowed(self):
        self.desktop._assert_input_target(11, verify_process=True)

    def test_unrelated_top_level_window_in_same_process_is_rejected(self):
        with self.assertRaisesRegex(DesktopError, "locked to"):
            self.desktop._assert_input_target(12, verify_process=True)

    def test_pid_reuse_or_process_replacement_is_rejected(self):
        self.desktop._process_identity.return_value = {
            "pid": 100, "creation_time_100ns": 999, "image_path": r"c:\\editor.exe",
        }
        with self.assertRaisesRegex(DesktopError, "target process changed"):
            self.desktop._assert_input_target(10, verify_process=True)

    def test_public_target_summary_does_not_expose_executable_path(self):
        self.assertEqual(self.desktop._target_summary(), {"hwnd": 10, "pid": 100, "title": "Editor"})


class InputIdleTests(unittest.TestCase):
    def setUp(self):
        self.desktop = object.__new__(Desktop)
        self.desktop._checkpoint = Mock()
        self.desktop._assert_expected_foreground = Mock()
        self.desktop._assert_input_target = Mock()
        self.desktop._user32 = Mock()
        self.now = 0.0
        self.clock = patch("windows_local_mcp.desktop.time.monotonic", side_effect=lambda: self.now)
        self.sleep = patch("windows_local_mcp.desktop.time.sleep", side_effect=self.advance)
        self.clock.start()
        self.sleep.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.sleep.stop)

    def advance(self, seconds):
        self.now += seconds

    def test_transient_mouse_press_waits_for_stable_release(self):
        self.desktop._held_inputs = lambda: ["Left mouse button"] if self.now < 0.2 else []
        self.desktop._wait_for_released_inputs()
        self.assertGreaterEqual(self.now, 0.3)
        self.assertLess(self.now, 1.0)
        self.desktop._user32.SendInput.assert_not_called()

    def test_persistent_modifier_is_named_and_never_force_released(self):
        self.desktop._held_inputs = lambda: ["Left Ctrl", "Right Alt"]
        with self.assertRaisesRegex(DesktopError, "Left Ctrl, Right Alt"):
            self.desktop._wait_for_released_inputs()
        self.assertAlmostEqual(self.now, 1.0)
        self.desktop._user32.SendInput.assert_not_called()

    def test_pause_interrupts_idle_wait(self):
        self.desktop._held_inputs = lambda: ["Left mouse button"]
        self.desktop._checkpoint.side_effect = [None, PermissionError("Paused")]
        with self.assertRaisesRegex(PermissionError, "Paused"):
            self.desktop._wait_for_released_inputs()
        self.assertLess(self.now, 0.1)
        self.desktop._user32.SendInput.assert_not_called()

    def test_only_high_bit_means_currently_held(self):
        self.desktop._user32.GetAsyncKeyState.side_effect = lambda key: -32767 if key == 0x5B else 1
        self.assertEqual(self.desktop._held_inputs(), ["Left Windows"])


if __name__ == "__main__":
    unittest.main()
