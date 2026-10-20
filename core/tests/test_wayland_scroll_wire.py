"""Synthetic libei events through capture and the real sender, without a GUI or portal.

These characterise GH16's reported path; passing is not a physical GNOME reproduction.
"""

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "win_app"))

import capture_portal
import capture_win
import capture_x11
import libei
import sender
from core import owner, protocol


class ScrollPath:
    def __init__(self):
        self.sent = []
        self.sender = sender.LinkSender(None, lambda: {}, links=lambda _: SimpleNamespace(
            live=lambda peer: True, send_input=lambda peer, message: self.sent.append(message) or True))
        self.sender._owner = owner.Owner(bytes(range(16)), lambda: 0)
        self.sender._owner.on = bytes(range(16, 32))
        self.hooks = capture_portal.Hooks(None, self.mouse, None, tokens=object())
        self.hooks._activation = 3
        self.device = object()
        self.hooks._ei_event(("start", self.device, 3))
        self.context = object.__new__(libei.Context)
        self.context._devices = {1: self.device}
        self.context._lib = SimpleNamespace(
            ei_event_get_type=lambda event: event[0],
            ei_event_get_device=lambda event: 1,
            ei_event_get_time=lambda event: 0,
            ei_event_scroll_get_dx=lambda event: event[1],
            ei_event_scroll_get_dy=lambda event: event[2],
            ei_event_scroll_get_discrete_dx=lambda event: event[1],
            ei_event_scroll_get_discrete_dy=lambda event: event[2],
        )

    def mouse(self, message, x, y, data):
        event = capture_win.mouse_event(message, data)
        if event and event[0] == "wheel":
            return self.sender.on_wheel(event[1], event[2])
        return False

    def feed(self, *events):
        for event in events:
            decoded = self.context._read(event)
            if decoded is not None:
                self.hooks._ei_event(decoded)

    def messages(self):
        while not self.sender._outbound.empty():
            action = self.sender._outbound.get_nowait()
            self.sender._deliver(action)
        result, self.sent = self.sent, []
        return result


class WaylandScrollWireTests(unittest.TestCase):
    def test_gnome_discrete_wheel_both_axes_and_directions(self):
        for x, y, want in ((0, 120, (-1, 0)), (0, -120, (1, 0)),
                           (120, 0, (0, -1)), (-120, 0, (0, 1))):
            with self.subTest(x=x, y=y):
                path = ScrollPath()
                path.feed((603, x, y), (100,))
                self.assertEqual(path.messages(), [protocol.scroll_msg(*want, "line")])

    def test_continuous_scroll_preserves_fractional_notches(self):
        path = ScrollPath()
        path.feed((600, 2.5, -5), (100,))
        self.assertEqual(path.messages(), [protocol.scroll_msg(0.5, 0, "line"),
                                           protocol.scroll_msg(0, -0.25, "line")])

    def test_high_resolution_discrete_values_are_not_truncated_to_notches(self):
        path = ScrollPath()
        path.feed((603, 0, 15), (100,))
        self.assertEqual(path.messages(), [protocol.scroll_msg(-0.125, 0, "line")])

    def test_sub_wheel_unit_deltas_accumulate_across_frames(self):
        path = ScrollPath()
        for _ in range(4):
            path.feed((600, 0, 0.03125), (100,))
        messages = path.messages()
        self.assertEqual(len(messages), 1)
        self.assertAlmostEqual(messages[0]["data"]["dy"], -1 / 120)

    def test_a_duplicate_continuous_representation_is_not_counted_twice(self):
        path = ScrollPath()
        path.feed((600, 0, 10), (603, 0, 120), (100,))
        self.assertEqual(path.messages(), [protocol.scroll_msg(-1, 0, "line")])

    def test_stop_and_cancel_do_not_erase_wheel_before_frame(self):
        for end in (601, 602):
            with self.subTest(end=end):
                path = ScrollPath()
                path.feed((603, 0, 120), (end,), (100,))
                self.assertEqual(path.messages(), [protocol.scroll_msg(-1, 0, "line")])

    def test_wheel_waits_for_its_frame(self):
        path = ScrollPath()
        path.feed((603, 0, 120))
        self.assertEqual(path.messages(), [])
        path.feed((100,))
        self.assertEqual(path.messages(), [protocol.scroll_msg(-1, 0, "line")])

    def test_windows_wheel_reaches_the_same_wire_message(self):
        path = ScrollPath()
        path.mouse(0x020A, 0, 0, 0xFF880000)
        self.assertEqual(path.messages(), [protocol.scroll_msg(-1, 0, "line")])

    def test_x11_button_wheel_reaches_the_same_wire_message(self):
        path = ScrollPath()
        hooks = capture_x11.Hooks(None, path.mouse, None)
        hooks._button(5, True, 0, False)
        self.assertEqual(path.messages(), [protocol.scroll_msg(-1, 0, "line")])

    def test_x11_smooth_wheel_reaches_the_same_wire_message(self):
        path = ScrollPath()
        hooks = capture_x11.Hooks(None, path.mouse, None)
        hooks._scrolls = {10: {2: (True, 15.0)}}
        hooks._motion(10, {2: 15.0})
        self.assertEqual(path.messages(), [protocol.scroll_msg(-1, 0, "line")])


if __name__ == "__main__":
    unittest.main()
