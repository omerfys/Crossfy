"""Map thirds, scoped contact geometry and ledger parity with synthetic settings."""

import copy
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

import app_config
import diagram
import theme
from core import ways
import test_crossing_page_parity as parity
from test_crossing_ledger import band_point, paint, picked


def picked_row(window):
    return picked(window, window._chosen_machine())


class PartEdgeCornersTests(unittest.TestCase):
    setUp = parity.CrossingPageParityTests.setUp
    tearDown = parity.CrossingPageParityTests.tearDown
    _open_window = parity.CrossingPageParityTests._open_window
    _close_window = parity.CrossingPageParityTests._close_window
    _stop_patches = parity.CrossingPageParityTests._stop_patches

    def test_map_click_toggles_the_row_without_a_drag(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        for third in ways.PARTS:
            canvas = window.atlas_canvas
            before = copy.deepcopy(canvas.tiles)
            saved_layout = app_config.load_settings(self.path)["layout"]
            point = band_point(canvas, third)
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(canvas, point + type(point)(30, 20))
            self.assertEqual(canvas.tiles, before)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(picked_row(window), [part for part in ways.PARTS if part != third])
            self.assertEqual(app_config.load_settings(self.path)["layout"], saved_layout)
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=band_point(canvas, third))
            self.assertEqual(picked_row(window), list(ways.PARTS))

    def test_a_picked_third_with_only_a_sliver_of_contact_is_not_lit(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        window._ledger_third(peer, "start")
        layout = copy.deepcopy(window.atlas_canvas.tiles)
        own = window._config.machine_id
        layout[own].update(x=0, y=0, w=300, h=300)
        layout[peer].update(x=300, y=100, w=300, h=110)
        layout[self.peers[1]["id"]].update(x=-300, y=0)
        window._layout_dropped(layout, peer)
        state = window.atlas_canvas.states[peer]
        self.assertEqual(state["thirds"], ["middle", "end"])
        self.assertEqual(state["lit"], ["middle"])
        canvas = window.atlas_canvas
        image = paint(canvas)
        rect, scale = canvas.tile_rect(own), canvas._scale
        from PySide6.QtCore import QPoint
        sliver = QPoint(round(rect.right()), round(rect.top() + 205 * scale))
        self.assertNotEqual(image.pixel(sliver), diagram._colour("signal").rgb())

    def test_unpicked_keeps_the_pick_without_an_inspector_note(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        window._ledger_third(peer, "middle")
        window._ledger_third(peer, "end")
        layout = copy.deepcopy(window.atlas_canvas.tiles)
        own = window._config.machine_id
        layout[own].update(x=0, y=0, w=160, h=120)
        layout[peer].update(x=160, y=80, w=160, h=40)
        window._layout_dropped(layout, peer)
        self.assertEqual(window.atlas_canvas.states[peer]["thirds"], ["start"])
        self.assertEqual(picked_row(window), ["start"])
        self.assertFalse(hasattr(window, "atlas_note"))
        QTest.mouseClick(window.atlas_canvas, Qt.MouseButton.LeftButton, pos=band_point(window.atlas_canvas, "end"))
        self.assertEqual(picked_row(window), ["start", "end"])
        self.assertTrue(window.atlas_canvas.states[peer]["crosses"])

    def test_a_corner_only_machine_has_its_pad_and_no_seam(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_corner(peer, "top_right")
        canvas = window.atlas_canvas
        image = paint(canvas)
        self.assertTrue(canvas.states[peer]["crosses"])
        self.assertEqual(canvas.corner_marks, [(peer, "top_right", 1.0)])
        own = canvas.tile_rect(canvas._own_id())
        self.assertFalse(any(side == "right" for side, *_ in canvas.seam_paths))
        self.assertNotEqual(image.pixel(band_point(canvas, "middle")), diagram._colour("signal").rgb())
        self.assertEqual(image.pixel(round(own.right() + 5), round(own.top())), diagram._colour("signal").rgb())

    def test_edge_off_survives_drop_and_text_restores_whole_edge(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        window._ledger_third(peer, "middle")
        window._ledger_edge(peer)
        window._layout_dropped(copy.deepcopy(window.atlas_canvas.tiles), peer)
        self.assertFalse(ways.has_way(app_config.load_settings(self.path), peer))
        self.assertEqual(picked_row(window), [])
        self.assertTrue(window.atlas_canvas.states[peer]["edge_off"])
        next(chip for chip in window.crossing_ledger.rows[peer].edge_chips.chips.values() if chip.kind == "contact").click()
        self.assertEqual(picked_row(window), list(ways.PARTS))
        self.assertTrue(window.atlas_canvas.states[peer]["crosses"])

    def test_each_side_orients_and_toggles_its_three_bands(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        for side in ways.EDGES:
            layout = copy.deepcopy(window.atlas_canvas.tiles)
            own = window._config.machine_id
            layout[own].update(x=0, y=0, w=160, h=120)
            x, y = {"left": (-160, 0), "right": (160, 0), "top": (0, -120), "bottom": (0, 120)}[side]
            layout[peer].update(x=x, y=y, w=160, h=120)
            layout[self.peers[1]["id"]].update(x=500, y=300)
            window._layout_dropped(layout, peer)
            parity.settle(window)
            row = window.crossing_ledger.rows[peer]
            self.assertEqual([chip.side for chip in row.edge_chips.chips.values() if chip.kind == "contact"], [side])
            for third in ways.PARTS:
                QTest.mouseClick(window.atlas_canvas, Qt.MouseButton.LeftButton, pos=band_point(window.atlas_canvas, third, side))
                self.assertNotIn(third, picked_row(window))
                QTest.mouseClick(window.atlas_canvas, Qt.MouseButton.LeftButton, pos=band_point(window.atlas_canvas, third, side))
                self.assertEqual(picked_row(window), list(ways.PARTS))

    def test_a_grip_on_the_seam_leaves_the_end_band_to_its_third(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        layout = copy.deepcopy(window.atlas_canvas.tiles)
        own = window._config.machine_id
        layout[own].update(x=0, y=0, w=160, h=120)
        layout[peer].update(x=-160, y=0, w=160, h=120)
        layout[self.peers[1]["id"]].update(x=500, y=300)
        window._layout_dropped(layout, peer)
        parity.settle(window)
        canvas = window.atlas_canvas
        band = band_point(canvas, "end", "left")
        grip = canvas._resize_grip_rect(peer)
        self.assertTrue(grip.contains(QPointF(band)))
        self.assertIsNone(canvas._resize_at(QPointF(band)))
        self.assertEqual(canvas._third_at(QPointF(band)), (peer, "end"))
        inside = QPointF(grip.right() - 8, grip.bottom() - 4)
        self.assertEqual(canvas._resize_at(inside), peer)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=inside.toPoint())
        self.assertTrue(canvas._resizing)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=inside.toPoint())

    def test_a_tile_inside_the_band_keeps_its_end_third_and_its_grip(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        layout = copy.deepcopy(window.atlas_canvas.tiles)
        own = window._config.machine_id
        layout[own].update(x=0, y=0, w=160, h=120)
        layout[peer].update(x=160, y=0, w=4, h=120)
        layout[self.peers[1]["id"]].update(x=500, y=300)
        window._layout_dropped(layout, peer)
        parity.settle(window)
        canvas = window.atlas_canvas
        grip = canvas._resize_grip_rect(peer)
        self.assertLessEqual(grip.width(), 5)
        band = band_point(canvas, "end", "right")
        self.assertEqual(canvas._third_at(QPointF(band)), (peer, "end"))
        self.assertIsNone(canvas._resize_at(QPointF(band)))
        outside = QPointF(grip.right() + 8, grip.bottom() + 4)
        self.assertIsNone(canvas._third_at(outside))
        self.assertEqual(canvas._resize_at(outside), peer)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=outside.toPoint())
        self.assertTrue(canvas._resizing)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=outside.toPoint())

    def test_band_is_five_pixels_wide_and_available_when_edge_is_off(self):
        window, peer = self.window, self.peers[0]["id"]
        canvas = window.atlas_canvas
        rect = canvas.tile_rect(window._config.machine_id)
        self.assertEqual(canvas._third_at(QPointF(rect.right() - 5, rect.center().y())), (peer, "middle"))
        self.assertEqual(canvas._third_at(QPointF(rect.right() + 5, rect.center().y())), (peer, "middle"))
        self.assertIsNone(canvas._third_at(QPointF(rect.right() + 5.01, rect.center().y())))
        self.assertEqual(canvas._third_at(band_point(canvas, "middle")), (peer, "middle"))
        window._choose_machine(self.peers[1]["id"])
        self.assertIsNone(canvas._third_at(band_point(canvas, "middle")))

    def test_selected_seam_and_tracks_break_at_the_thirds(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        window._ledger_third(peer, "middle")
        canvas, lines = window.atlas_canvas, []
        original = diagram.QPainter
        class RecordingPainter(original):
            def drawLine(self, *args):
                if len(args) == 2:
                    lines.append((QPointF(args[0]), QPointF(args[1]), self.pen().widthF(), self.pen().color()))
                return super().drawLine(*args)
        with patch.object(diagram, "QPainter", RecordingPainter):
            paint(canvas)
        rect = canvas.tile_rect(window._config.machine_id)
        x, third_height = rect.right(), rect.height() / 3
        seams = [(a, b, width, colour) for a, b, width, colour in lines
                 if abs(a.x() - x) < .01 and abs(b.x() - x) < .01]
        signal = QColor(theme.colour("signal"))
        lit = [(a.y(), b.y()) for a, b, width, colour in seams if width == 4 and colour == signal]
        # At a third boundary the 4pt seam stops half the break gap plus its round cap short.
        inner = diagram.THIRD_GAP / 2 + 2
        expected = [(rect.top() + 2, rect.top() + third_height - inner),
                    (rect.top() + 2 * third_height + inner, rect.bottom() - 2)]
        self.assertEqual(len(lit), len(expected))
        for actual, wanted in zip(lit, expected):
            self.assertAlmostEqual(actual[0], wanted[0])
            self.assertAlmostEqual(actual[1], wanted[1])
        tracks = [(a.y(), b.y()) for a, b, width, colour in seams if width == 2]
        self.assertEqual(len(tracks), 1)
        self.assertAlmostEqual(tracks[0][0], rect.top() + third_height + 2)
        self.assertAlmostEqual(tracks[0][1], rect.top() + 2 * third_height - 2)

    def test_inactive_peers_have_no_corner_mark(self):
        peer = self.peers[0]["id"]
        self.window._ledger_corner(peer, "top_right")
        self.window._canvas_left_out(peer, True)
        paint(self.window.atlas_canvas)
        self.assertFalse(self.window.atlas_canvas.corner_marks)
        self.assertEqual([corner for corner, button in self.window.crossing_ledger.rows[peer].corner_grid.buttons.items()
                          if button.isChecked()], ["top_right"])

    def test_contact_chip_and_corner_buttons_wait_for_a_side_contact(self):
        window, peer = self.window, self.peers[0]["id"]
        layout = copy.deepcopy(window.atlas_canvas.tiles)
        layout[peer].update(x=600, y=300)
        window._layout_dropped(layout, peer)
        row = window.crossing_ledger.rows[peer]
        self.assertFalse(any(chip.kind == "contact" for chip in row.edge_chips.chips.values()))
        self.assertFalse(row.corner_grid.buttons["top_right"].isEnabled())


if __name__ == "__main__":
    unittest.main()
