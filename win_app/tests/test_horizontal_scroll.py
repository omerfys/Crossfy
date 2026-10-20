"""Both scroll axes keep the driving machine's direction on every receiver (WIRE.md section 6,
`scroll`). The wire is the Mac's: Core Graphics axis 1 positive moves the view up, axis 2 positive
moves it left, measured on macOS 27 on 13-10-2026 by handing CGEventCreateScrollWheelEvent's events
to an offscreen NSScrollView. Windows' horizontal wheel, X11's buttons 6 and 7 and libei's dx all
run the other way, which is what reversed horizontal scrolling between a Mac and a PC.

Directions here are where the view moves, right and up positive. The Mac's own setting (natural or
not) is already in the deltas its event tap reads, so each case says how the fingers moved, which
setting turned that into a view movement, and checks the receiver moves its view the same way."""

import unittest

from links_rig import B, Rig

import capture_win
import inject_portal
import inject_x11
import input_injector
from core import protocol

FINGERS = {"left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1)}
X11_BUTTONS = {4: (0, 1), 5: (0, -1), 6: (-1, 0), 7: (1, 0)}


def sign(value):
    return (value > 0) - (value < 0)


def view_for(fingers, natural):
    """Natural scrolling moves the content with the fingers, so the view goes the other way."""
    fx, fy = FINGERS[fingers]
    return (-fx, -fy) if natural else (fx, fy)


def mac_axes(view, size):
    """The (axis 1, axis 2) a Mac reports for a view movement: the wire's (dy, dx)."""
    vx, vy = view
    return vy * size, -vx * size


def mac_view(dy, dx):
    return sign(-dx), sign(dy)


def windows_view(wheel, hwheel):
    return sign(hwheel), sign(wheel)


def x11_view(buttons):
    moves = [X11_BUTTONS[button] for button in buttons]
    return sign(sum(x for x, _ in moves)), sign(sum(y for _, y in moves))


def libei_view(x, y):
    return sign(x), sign(-y)


def wheel_data(notches):
    return (int(notches * capture_win.WHEEL_DELTA) & 0xFFFF) << 16


CASES = [(fingers, natural) for natural in (True, False) for fingers in FINGERS]
MODES = (("pixel", 40.0), ("line", 1))


class MacDrivingAPc(unittest.TestCase):
    """A Mac's scroll as each PC injector posts it."""

    def check(self, view_of_plan):
        for fingers, natural in CASES:
            for mode, size in MODES:
                with self.subTest(fingers=fingers, natural=natural, mode=mode):
                    expected = view_for(fingers, natural)
                    dy, dx = mac_axes(expected, size)
                    self.assertEqual(mac_view(dy, dx), expected)
                    self.assertEqual(view_of_plan(dy, dx, mode), expected)

    def test_windows_scrolls_the_way_the_mac_would(self):
        self.check(lambda dy, dx, mode: windows_view(*input_injector.plan_scroll_units(dy, dx, mode, [0.0, 0.0])))

    def test_x11_scrolls_the_way_the_mac_would(self):
        def view(dy, dx, mode):
            return x11_view(inject_x11.scroll_buttons(*inject_x11.plan_scroll(dy, dx, mode, [0.0, 0.0])))

        self.check(view)

    def test_wayland_scrolls_the_way_the_mac_would(self):
        def view(dy, dx, mode):
            _kind, x, y = inject_portal.scroll_steps(dy, dx, mode, [0.0, 0.0])
            return libei_view(x, y)

        self.check(view)


class PcDrivingOthers(unittest.TestCase):
    """A PC's wheel, from its hook through the sender to the wire, as a Mac and another PC post it.
    The PC's own scrolling setting is already in its wheel's deltas, as the Mac's is in its tap's."""

    def setUp(self):
        self.rig = Rig()
        self.rig.sender.set_redirecting(True)
        self.rig.accept_take()

    def sent_scroll(self, view):
        vx, vy = view
        sent = []
        for message, notches in ((capture_win.WM_MOUSEWHEEL, vy), (capture_win.WM_MOUSEHWHEEL, vx)):
            if notches:
                _kind, dy, dx = capture_win.mouse_event(message, wheel_data(notches))
                self.assertTrue(self.rig.sender.on_wheel(dy, dx))
                sent.append(self.rig.sent(B, protocol.MSG_SCROLL)[-1]["data"])
        self.assertEqual(len(sent), 1)
        return sent[0]

    def test_a_mac_scrolls_the_way_the_pc_would(self):
        for fingers, natural in CASES:
            with self.subTest(fingers=fingers, natural=natural):
                expected = view_for(fingers, natural)
                data = self.sent_scroll(expected)
                self.assertEqual(mac_view(data["dy"], data["dx"]), expected)

    def test_another_pc_scrolls_the_way_the_pc_would(self):
        for fingers, natural in CASES:
            with self.subTest(fingers=fingers, natural=natural):
                expected = view_for(fingers, natural)
                data = self.sent_scroll(expected)
                planned = input_injector.plan_scroll_units(data["dy"], data["dx"], data["mode"], [0.0, 0.0])
                self.assertEqual(windows_view(*planned), expected)
                buttons = inject_x11.scroll_buttons(*inject_x11.plan_scroll(data["dy"], data["dx"], data["mode"], [0.0, 0.0]))
                self.assertEqual(x11_view(buttons), expected)


if __name__ == "__main__":
    unittest.main()
