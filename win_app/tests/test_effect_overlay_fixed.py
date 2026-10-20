import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

import effect_overlay
from core import effects


class FakeTimer:
    def __init__(self):
        self.active = False

    def isActive(self):
        return self.active

    def start(self):
        self.active = True

    def setInterval(self, _interval):
        pass

    def stop(self):
        self.active = False


class Frames:
    def __init__(self, frames, busy=True):
        self.values = iter(frames)
        self.busy_values = iter(busy) if isinstance(busy, (list, tuple)) else None
        self.busy = busy[0] if self.busy_values is not None else busy

    def frames(self, *_args):
        if self.busy_values is not None:
            self.busy = next(self.busy_values, self.busy)
        return next(self.values, [])


class FixedGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def overlay(self, fixed=True, desk=QRect(0, 0, 320, 200)):
        overlay = effect_overlay.EffectOverlay(fixed_geometry=fixed)
        overlay._timer = FakeTimer()
        overlay._desk = QRect(desk)
        overlay._displays = [(0.0, 0.0, float(desk.width()), float(desk.height()))]
        overlay._fx = effects.effect("discharge")
        overlay._palette = app_palette()
        return overlay

    def test_discharge_keeps_desktop_geometry_and_stays_visible_through_departure_and_arrival(self):
        desk = QRect(0, 0, 320, 200)
        overlay = self.overlay(desk=desk)
        now = [10.0]
        geometries = []
        visibility = []
        with mock.patch.object(effect_overlay.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(effect_overlay, "desktop_box", return_value=QRect(desk)), \
             mock.patch.object(effect_overlay, "system_reduced_motion", return_value=False), \
             mock.patch.object(effect_overlay, "system_dark", return_value=True):
            overlay.configure("discharge", "signal")
            overlay.push("right", 1.0, True, effect_overlay.QPointF(319, 100))
            for step in range(1, 55):
                now[0] = 10.0 + step * 0.05
                overlay._tick()
                geometries.append(QRect(overlay.geometry()))
                if overlay.player.busy:
                    visibility.append(not overlay.isHidden())
            now[0] = 13.0
            overlay.arrive("edge", "left", effect_overlay.QPointF(1, 100))
            for step in range(1, 55):
                now[0] = 13.0 + step * 0.05
                overlay._tick()
                geometries.append(QRect(overlay.geometry()))
                if overlay.player.busy:
                    visibility.append(not overlay.isHidden())
        overlay.stop()
        self.assertTrue(geometries)
        self.assertTrue(all(frame == desk for frame in geometries))
        self.assertTrue(all(visibility))

    def test_each_dirty_update_covers_current_pen_bounds_and_the_previous_frame(self):
        overlay = self.overlay()
        frame1 = [bounded_fill(10, 20, 30, 40), bounded_fill(45, 50, 60, 70)]
        frame2 = [bounded_fill(210, 120, 235, 145)]
        overlay.player = Frames([frame1, frame2])
        updates = []
        overlay.update = lambda rect=None: updates.append(QRect(rect))
        with mock.patch.object(effect_overlay.time, "monotonic", return_value=1.0):
            overlay._tick()
            overlay._tick()
        self.assertEqual(len(updates), 2)
        for pen in frame1:
            x0, y0, x1, y1 = pen.bounds
            expected = QRect(int(x0) - 2, int(y0) - 2, int(x1 - x0) + 4, int(y1 - y0) + 4)
            self.assertTrue(updates[0].contains(expected))
        previous = QRect(8, 18, 54, 54)
        self.assertTrue(updates[1].contains(previous))
        self.assertTrue(updates[1].contains(QRect(208, 118, 29, 29)))

    def test_fixed_and_resized_overlays_render_the_same_desktop_pixels(self):
        desk = QRect(0, 0, 320, 200)
        pens = [bounded_fill(40, 30, 90, 75), bounded_fill(70, 55, 120, 100)]
        fixed = self.overlay(True, desk)
        fixed.setGeometry(desk)
        fixed._pens, fixed._offset = pens, (0.0, 0.0)
        resized = self.overlay(False, desk)
        resized.setGeometry(QRect(38, 28, 84, 74))
        resized._pens, resized._offset = pens, (38.0, 28.0)

        images = []
        for widget, offset in ((fixed, QPoint(0, 0)), (resized, QPoint(38, 28))):
            image = QImage(desk.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            widget.render(painter, offset)
            painter.end()
            images.append(image)
        fixed.hide()
        resized.hide()
        self.assertEqual(images[0], images[1])

    def test_finished_effect_updates_the_last_dirty_rect_then_hides(self):
        overlay = self.overlay()
        last = [bounded_fill(25, 35, 80, 90)]
        overlay.player = Frames([last, []], busy=[True, False])
        requests = []
        real_update = overlay.update

        def record_update(rect=None):
            requests.append(QRect(rect))
            real_update(rect)

        overlay.update = record_update
        with mock.patch.object(effect_overlay.time, "monotonic", return_value=2.0):
            overlay._tick()
            self.app.processEvents()
            self.assertFalse(overlay.isHidden())
            overlay._tick()
            image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            overlay.render(painter, QPoint(0, 0))
            painter.end()
            self.assertEqual(image.pixelColor(50, 60).alpha(), 0)
            self.app.processEvents()
        self.assertTrue(requests[-1].contains(QRect(23, 33, 59, 59)))
        self.assertTrue(overlay.isHidden())
        overlay.stop()

    def test_spark_effect_departures_and_arrivals_draw_around_supplied_points(self):
        desk = QRect(0, 0, 320, 200)
        centre = (160.0, 100.0)
        edge_points = {
            "left": (1.0, 57.0), "right": (318.0, 143.0),
            "top": (73.0, 1.0), "bottom": (247.0, 198.0),
        }
        now = [10.0]
        with mock.patch.object(effect_overlay.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(effect_overlay, "desktop_box", return_value=QRect(desk)), \
             mock.patch.object(effect_overlay, "system_reduced_motion", return_value=False), \
             mock.patch.object(effect_overlay, "system_dark", return_value=True), \
             mock.patch.object(effect_overlay.QCursor, "pos", return_value=QPoint(160, 100)):
            for style in ("flint", "filings", "discharge"):
                for edge, location in edge_points.items():
                    for phase in ("departure", "arrival"):
                        overlay = self.overlay(True, desk)
                        overlay.configure(style, "signal")
                        point = effect_overlay.QPointF(*location)
                        if phase == "departure":
                            overlay.push(edge, 1.0, True, point)
                        else:
                            overlay.arrive("edge", edge, point)
                        drawn = []
                        for step in range(1, 7):
                            now[0] += 0.05
                            overlay._tick()
                            drawn.extend(pen.bounds for pen in overlay._pens if hasattr(pen, "bounds"))
                        overlay.stop()
                        self.assertTrue(drawn, (style, edge, phase))
                        self.assertTrue(any(distance_to_bounds(location, bounds) <= 60 for bounds in drawn),
                                        (style, edge, phase, location))
                        self.assertFalse(any(contains(centre, bounds) for bounds in drawn),
                                         (style, edge, phase, centre))


def bounded_fill(x0, y0, x1, y1):
    pen = effects.Pen()
    pen.fillRect(x0, y0, x1 - x0, y1 - y0)
    pen.bounds = (float(x0), float(y0), float(x1), float(y1))
    return pen


def app_palette():
    return [(1.0, 0.1, 0.0, 1.0), (1.0, 0.8, 0.1, 1.0)]


def distance_to_bounds(point, bounds):
    x0, y0, x1, y1 = bounds
    dx = max(x0 - point[0], 0.0, point[0] - x1)
    dy = max(y0 - point[1], 0.0, point[1] - y1)
    return (dx * dx + dy * dy) ** 0.5


def contains(point, bounds):
    x0, y0, x1, y1 = bounds
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1


if __name__ == "__main__":
    unittest.main()
