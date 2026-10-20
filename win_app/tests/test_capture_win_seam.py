import ctypes
import unittest
from unittest.mock import Mock, patch

import capture_win
from core.return_edge import CornerPush, PartEdge, Rect, ReturnEdge


class HookPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MouseData(ctypes.Structure):
    _fields_ = [
        ("pt", HookPoint),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class InternalSeamTests(unittest.TestCase):
    def setUp(self):
        self.left = Rect(0, 0, 100, 100)
        self.right = Rect(100, 0, 100, 100)
        self.monitors = [self.left, self.right]
        self.display_map = {"left": self.left}

    def test_an_armed_display_edge_clips_to_the_source_monitor(self):
        edge = ReturnEdge("right", display="left")
        self.assertEqual(
            capture_win.internal_seam_position((105, 50), self.monitors, self.display_map, [edge]),
            (99, 50),
        )

    def test_only_the_armed_display_edge_holds_and_only_on_its_third(self):
        edge = PartEdge("right", {"start"}, display="left")
        self.assertEqual(
            capture_win.internal_seam_position((105, 20), self.monitors, self.display_map, [edge]),
            (99, 20),
        )
        self.assertIsNone(
            capture_win.internal_seam_position((105, 80), self.monitors, self.display_map, [edge])
        )
        self.assertIsNone(
            capture_win.internal_seam_position((105, 20), self.monitors, self.display_map, [])
        )

    def test_top_and_bottom_seams_are_clipped_too(self):
        upper, lower = Rect(0, 0, 100, 100), Rect(0, 100, 100, 100)
        top_edge = ReturnEdge("top", display="lower")
        bottom_edge = ReturnEdge("bottom", display="upper")
        self.assertEqual(
            capture_win.internal_seam_position((50, 95), [upper, lower], {"lower": lower}, [top_edge]),
            (50, 100),
        )
        self.assertEqual(
            capture_win.internal_seam_position((50, 105), [upper, lower], {"upper": upper}, [bottom_edge]),
            (50, 99),
        )

    def test_scoped_corner_is_checked_on_its_display_when_both_walls_are_internal(self):
        upper_left = Rect(0, 0, 100, 100)
        nominated = Rect(100, 0, 100, 100)
        right = Rect(200, 0, 100, 100)
        below = Rect(100, 100, 100, 100)
        monitors = [upper_left, nominated, right, below]
        corner = CornerPush("bottom_right", "right", display="b0")
        self.assertTrue(corner._at_edge(monitors, (199, 99), {"b0": nominated}))

    def test_mouse_hook_restores_the_cursor_and_swallows_the_seam_move(self):
        on_mouse = Mock(return_value=False)
        on_seam = Mock(return_value=(99, 50))
        hooks = capture_win.Hooks(Mock(), on_mouse, Mock(), on_seam=on_seam)
        user32 = Mock()
        user32.SetCursorPos.return_value = 1
        data = MouseData(HookPoint(105, 50), 0, 0, 0, 0)

        with patch.object(capture_win, "MSLLHOOKSTRUCT", MouseData, create=True), \
                patch.object(capture_win, "user32", user32):
            result = hooks._mouse_proc(capture_win.HC_ACTION, capture_win.WM_MOUSEMOVE, ctypes.byref(data))

        self.assertEqual(result, 1)
        user32.SetCursorPos.assert_called_once_with(99, 50)
        on_mouse.assert_not_called()

    def test_a_set_cursor_failure_fails_open(self):
        on_mouse = Mock(return_value=False)
        hooks = capture_win.Hooks(Mock(), on_mouse, Mock(), on_seam=Mock(return_value=(99, 50)))
        user32 = Mock()
        user32.SetCursorPos.return_value = 0
        user32.CallNextHookEx.return_value = 99
        data = MouseData(HookPoint(105, 50), 0, 0, 0, 0)

        with patch.object(capture_win, "MSLLHOOKSTRUCT", MouseData, create=True), \
                patch.object(capture_win, "user32", user32):
            result = hooks._mouse_proc(capture_win.HC_ACTION, capture_win.WM_MOUSEMOVE, ctypes.byref(data))

        self.assertEqual(result, 99)
        on_mouse.assert_called_once()


if __name__ == "__main__":
    unittest.main()
