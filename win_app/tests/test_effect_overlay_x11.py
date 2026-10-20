import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import effect_overlay_x11
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
import effect_overlay
from core import effects


def recorded_frame(pens):
    def value(item):
        if isinstance(item, effects.Gradient):
            return vars(item)
        if isinstance(item, (tuple, list)):
            return [value(part) for part in item]
        return item
    return [(pen.bounds, getattr(pen, "clip", None), value(pen.ops)) for pen in pens]


def transparent_image(size):
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    return image


class HelperWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_helper_windows_bypass_shell_window_tracking(self):
        overlay, glow = effect_overlay_x11.create_overlays()
        for widget in (overlay, glow):
            self.assertEqual(widget.windowType(), Qt.WindowType.ToolTip)
            self.assertTrue(widget.windowFlags() & Qt.WindowType.X11BypassWindowManagerHint)
            self.assertTrue(widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
            self.assertTrue(widget.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            widget.close()

    def test_completed_effect_clears_without_unmapping(self):
        overlay, glow = effect_overlay_x11.create_overlays()
        overlay.show()
        overlay._dirty_rect = QRect(10, 20, 30, 40)
        updates = []
        overlay.update = lambda rect: updates.append(QRect(rect))
        overlay._clear_fixed()
        self.assertEqual(updates, [QRect(10, 20, 30, 40)])
        self.assertFalse(overlay._hide_after_paint)
        self.assertFalse(overlay.isHidden())
        self.assertFalse(overlay._timer.isActive())
        overlay.stop()
        self.assertTrue(overlay.isHidden())
        glow.close()

    def test_next_effect_reuses_the_transparent_mapped_surface(self):
        overlay, glow = effect_overlay_x11.create_overlays()
        overlay.configure("discharge", "signal")
        overlay.show = mock.Mock(wraps=overlay.show)
        now = [10.0]
        with mock.patch.object(effect_overlay.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(effect_overlay, "system_reduced_motion", return_value=False):
            for start in (10.0, 20.0):
                now[0] = start
                overlay.arrive("edge", "left", QPointF(1, 100))
                for step in range(1, 100):
                    now[0] = start + step * 0.05
                    overlay._tick()
                    if not overlay.player.busy:
                        break
                self.assertFalse(overlay.player.busy)
                image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0xffffffff)
                painter = QPainter(image)
                overlay.render(painter, QPoint(0, 0))
                painter.end()
                self.assertEqual(image, transparent_image(image.size()))
                self.assertFalse(overlay.isHidden())
        overlay.show.assert_called_once()
        overlay.stop()
        glow.close()

    def test_helper_size_and_lifetime_match_native_at_each_scale(self):
        now = [10.0]
        for scale in (1, 2):
            desk = QRect(0, 0, 1920 // scale, 1080 // scale)
            screen = mock.Mock()
            screen.geometry.return_value = desk
            screen.devicePixelRatio.return_value = scale
            screen.refreshRate.return_value = 60.0
            with mock.patch.object(effect_overlay.QGuiApplication, "screens", return_value=[screen]), \
                 mock.patch.object(effect_overlay, "desktop_box", return_value=desk), \
                 mock.patch.object(effect_overlay.time, "monotonic", side_effect=lambda: now[0]), \
                 mock.patch.object(effect_overlay, "system_reduced_motion", return_value=False), \
                 mock.patch.object(effect_overlay, "system_dark", return_value=True):
                for style in ("flint", "filings", "discharge"):
                    for phase in ("departure", "arrival"):
                        helper, glow = effect_overlay_x11.create_overlays()
                        native = effect_overlay.EffectOverlay()
                        now[0] = 10.0
                        point = QPointF(desk.width() - 2, desk.height() * 0.4)
                        for widget in (helper, native):
                            widget.configure(style, "signal", "long", "large", 1.35, 0.052)
                            if phase == "departure":
                                widget.push("right", 1.0, True, point)
                            else:
                                widget.arrive("edge", "right", point)
                        drawn = False
                        for step in range(100):
                            now[0] = 10.0 + step * 0.05
                            helper._tick()
                            native._tick()
                            self.assertEqual(recorded_frame(helper._pens), recorded_frame(native._pens),
                                             (scale, style, phase, step))
                            self.assertEqual(helper.player.busy, native.player.busy)
                            if helper._pens:
                                drawn = True
                                self.assertFalse(helper.isHidden())
                            if not helper.player.busy:
                                break
                        self.assertTrue(drawn)
                        self.assertFalse(helper.player.busy)
                        for widget in (helper, native, glow):
                            widget.close()


class FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)

    def flush(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self, returncode=None):
        self.stdin = FakeStdin()
        self.stdout = None
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = -1


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.process = FakeProcess()
        self.failed = []
        self.proxy = effect_overlay_x11.EffectOverlayX11Proxy(
            on_failure=lambda: self.failed.append(True), popen=lambda *args, **kwargs: self.process
        )

    def test_calls_write_the_helper_protocol(self):
        self.proxy.configure("flint", "ocean", "long", "large", 1.35, 0.052)
        self.proxy.push("right", 0.7, False, part="end")
        self.proxy.arrive("edge", "left", 768, 432, [0, 0, 1536, 864])
        self.proxy.crossed_in()
        self.proxy.switched(384, 216, [0, 0, 1536, 864], "match")
        self.proxy.configure_glow("beam", "sunset", "short", "small", 0.75, 0.03)
        self.proxy.set_pressure("bottom", 1.0, True, "start")
        self.proxy.stop()

        self.assertEqual([json.loads(line) for line in self.process.stdin.lines], [
            {"op": "effect_configure", "style": "flint", "colour": "ocean", "length": "long", "size": "large",
             "effect_pace": 1.35, "size_fraction": 0.052, "divisor": 1},
            {"op": "push", "edge": "right", "pressure": 0.7, "crossed": False, "part": "end"},
            {"op": "arrive", "method": "edge", "edge": "left", "x": 768, "y": 432, "desk": [0, 0, 1536, 864]},
            {"op": "crossed_in"},
            {"op": "switched", "x": 384, "y": 216, "desk": [0, 0, 1536, 864], "choice": "match"},
            {"op": "glow_configure", "style": "beam", "colour": "sunset", "length": "short", "size": "small",
             "effect_pace": 0.75, "size_fraction": 0.03, "divisor": 1},
            {"op": "glow_pressure", "edge": "bottom", "pressure": 1.0, "crossed": True, "part": "start"},
            {"op": "stop"},
        ])

    def test_the_frame_rate_divisor_reaches_the_helper_process(self):
        import frame_clock
        self.addCleanup(frame_clock.set_divisor, 1)
        frame_clock.set_divisor(4)
        self.proxy.configure("flint", "ocean")
        sent = json.loads(self.process.stdin.lines[-1])
        self.assertEqual(sent["divisor"], 4)
        frame_clock.set_divisor(1)
        overlay, glow = mock.Mock(), mock.Mock()
        effect_overlay_x11.dispatch(sent, overlay, glow, None)
        self.assertEqual(frame_clock.divisor(), 4)

    def test_push_with_cursor_serialises_the_cursor_and_desktop_bounds(self):
        self.proxy.push("right", 0.7, False, cursor=QPointF(1590, 440), desk=QRect(100, -20, 1600, 900))

        self.assertEqual(json.loads(self.process.stdin.lines[0]), {
            "op": "push", "edge": "right", "pressure": 0.7, "crossed": False, "part": None,
            "x": 1590, "y": 440, "desk": [100, -20, 1600, 900],
        })

    def test_push_without_cursor_keeps_the_existing_protocol(self):
        self.proxy.push("right", 0.7, False, part="end")

        self.assertEqual(json.loads(self.process.stdin.lines[0]), {
            "op": "push", "edge": "right", "pressure": 0.7, "crossed": False, "part": "end",
        })

    def test_helper_exit_marks_proxy_failed_once(self):
        self.proxy.configure("flint", "ocean")
        self.process.returncode = 1
        self.proxy.check_process()
        self.proxy.check_process()

        self.assertTrue(self.proxy.failed)
        self.assertEqual(self.failed, [True])

    @unittest.skipIf(sys.platform == "win32", "select() on a pipe is POSIX only; the helper runs only on Linux")
    def test_helper_failure_message_marks_proxy_failed(self):
        read_fd, write_fd = os.pipe()
        self.process.stdout = os.fdopen(read_fd, "r")
        os.write(write_fd, b"failed effect\n")
        os.close(write_fd)

        self.proxy.configure("flint", "ocean")
        self.proxy.check_process()

        self.assertTrue(self.proxy.failed)
        self.assertEqual(self.failed, [True])

    def test_helper_start_failure_marks_proxy_failed(self):
        proxy = effect_overlay_x11.EffectOverlayX11Proxy(
            on_failure=lambda: self.failed.append(True),
            popen=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
        )
        proxy.configure("flint", "ocean")

        self.assertTrue(proxy.failed)
        self.assertEqual(self.failed, [True])

    def test_timer_polls_fast_while_showing_slowly_while_idle_and_stops_once_failed(self):
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        self.proxy.configure("flint", "ocean")
        timer = self.proxy._timer
        self.assertIsNotNone(timer)
        self.assertEqual((timer.isActive(), timer.interval()), (True, 100))
        self.proxy._on_timer()
        self.assertEqual((timer.isActive(), timer.interval()), (True, 1000), "idle, the helper is still watched")
        self.proxy.push("right", 0.7, False)
        self.assertEqual((timer.isActive(), timer.interval()), (True, 100))
        self.proxy._on_timer()
        self.assertEqual(timer.interval(), 100, "still showing")
        self.proxy.stop()
        self.assertEqual((timer.isActive(), timer.interval()), (True, 1000))
        self.proxy.arrive("edge", "left", 768, 432, [0, 0, 1536, 864])
        self.assertEqual(timer.interval(), 100)
        self.process.returncode = 1
        self.proxy._on_timer()
        self.assertTrue(self.proxy.failed)
        self.assertFalse(timer.isActive())
class DispatchTests(unittest.TestCase):
    def test_dispatch_maps_points_by_fraction_and_calls_the_overlays(self):
        overlay = mock.Mock()
        glow = mock.Mock()
        commands = [
            {"op": "effect_configure", "style": "flint", "colour": "ocean", "length": "normal", "size": "medium",
             "effect_pace": 1.4, "size_fraction": 0.055},
            {"op": "push", "edge": "right", "pressure": 0.5, "crossed": False, "part": None,
             "x": 778, "y": 452, "desk": [10, 20, 1536, 864]},
            {"op": "arrive", "method": "edge", "edge": "left", "x": 768, "y": 432, "desk": [0, 0, 1536, 864]},
            {"op": "crossed_in"},
            {"op": "switched", "x": 384, "y": 216, "desk": [0, 0, 1536, 864], "choice": "match"},
            {"op": "glow_configure", "style": "beam", "colour": "sunset", "length": "short", "size": "small",
             "effect_pace": 0.8, "size_fraction": 0.025},
            {"op": "glow_pressure", "edge": "bottom", "pressure": 1.0, "crossed": True, "part": "end"},
            {"op": "stop"},
        ]

        class Bounds:
            def x(self): return 100
            def y(self): return -50
            def width(self): return 3072
            def height(self): return 1728

        for command in commands[:-1]:
            effect_overlay_x11.dispatch(command, overlay, glow, Bounds(), lambda x, y: (x, y))

        self.assertEqual(overlay.configure.call_args.args,
                         ("flint", "ocean", "normal", "medium", 1.4, 0.055))
        self.assertEqual(overlay.push.call_args, mock.call("right", 0.5, False, cursor=(1636, 814), part=None))
        effect_overlay_x11.dispatch(
            {"op": "push", "edge": "left", "pressure": 0.2, "crossed": False}, overlay, glow, Bounds(),
            lambda x, y: (x, y)
        )
        self.assertEqual(overlay.push.call_args, mock.call("left", 0.2, False, part=None))
        self.assertEqual(overlay.arrive.call_args.args, ("edge", "left", (1636, 814)))
        self.assertEqual(overlay.switched.call_args.args, ((868, 382), "match"))
        self.assertEqual(glow.configure.call_args.args,
                         ("beam", "sunset", "short", "small", 0.8, 0.025))
        self.assertEqual(glow.set_pressure.call_args, mock.call("bottom", 1.0, True, "end"))
        overlay.crossed_in.assert_called_once_with()
        self.assertTrue(effect_overlay_x11.dispatch(commands[-1], overlay, glow, Bounds()))
        overlay.stop.assert_called_once_with()
        glow.hide.assert_called_once_with()


class BridgeSelectionTests(unittest.TestCase):
    def test_proxy_is_selected_only_for_wayland_with_display(self):
        available = effect_overlay_x11.available
        self.assertTrue(available(True, {"DISPLAY": ":0"}))
        self.assertFalse(available(True, {}))
        self.assertFalse(available(False, {"DISPLAY": ":0"}))


if __name__ == "__main__":
    unittest.main()
