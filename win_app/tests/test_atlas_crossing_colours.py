import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AtlasCrossingColoursTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        import diagram

        self.app = QApplication.instance() or QApplication([])
        self.canvas = diagram.AtlasCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.canvas.resize(720, 268)
        self.canvas.set_tiles(
            {"home": {"x": 80, "y": 50, "w": 160, "h": 100},
             "peer": {"x": 240, "y": 50, "w": 160, "h": 100}},
            {"home": "This PC", "peer": "Studio PC"},
            {"peer": {"state": "edge", "crosses": True, "linked": True}},
            "peer", own_id="home")

    def painted_tiles(self):
        from PySide6.QtGui import QPen
        import diagram

        painter = mock.Mock()
        borders = []
        pen = None

        def set_pen(value):
            nonlocal pen
            pen = value

        def rounded_rect(rect, *_args):
            if isinstance(pen, QPen):
                borders.append((rect, pen.color(), pen.widthF()))

        painter.setPen.side_effect = set_pen
        painter.drawRoundedRect.side_effect = rounded_rect
        with mock.patch.object(diagram, "QPainter", return_value=painter):
            self.canvas.paintEvent(None)
        return borders, painter

    def test_selected_and_own_tile_borders_are_neutral(self):
        import diagram

        borders, _painter = self.painted_tiles()
        for key, role, width in (("peer", "ink_2", 2), ("home", "edge", 1)):
            border = next(item for item in borders if item[0] == self.canvas.tile_rect(key))
            self.assertEqual(border[1], diagram._colour(role))
            self.assertNotEqual(border[1], diagram._colour("signal"))
            self.assertEqual(border[2], width)

    def test_crossing_peer_has_crosses_foot_in_signal(self):
        import diagram

        for state in ("edge", "part", "corner"):
            with self.subTest(state=state):
                self.canvas.states["peer"] = {"state": state, "crosses": True}
                _borders, painter = self.painted_tiles()
                calls = painter.method_calls
                foot_index = next(index for index, call in enumerate(calls)
                                  if call[0] == "drawText" and call[1][-1] == "Crosses")
                pen = next(call[1][0] for call in reversed(calls[:foot_index]) if call[0] == "setPen")
                self.assertEqual(pen, diagram._colour("signal"))

    def test_peer_without_a_crossing_has_no_crosses_foot(self):
        for crosses in ({}, {"crosses": False}):
            with self.subTest(crosses=crosses):
                self.canvas.states["peer"] = {"state": "edge", **crosses}
                _borders, painter = self.painted_tiles()
                feet = [call.args[-1] for call in painter.drawText.call_args_list]
                self.assertIn("Edge off", feet)
                self.assertNotIn("Crosses", feet)

    def test_outcome_rule_matches_the_mac_for_disabled_and_indirect_crossings(self):
        import diagram

        for state, crosses, own, name, expected in (
                ("edge", True, False, "", "Crosses"),
                ("edge", False, False, "", "Edge off"),
                ("gap", True, False, "", "Drag to connect"),
                ("between", False, False, "Studio", "Crosses to Studio"),
                ("between", False, False, "", "Set elsewhere"),
                ("set-elsewhere", False, False, "Studio", "Set on Studio"),
                ("set_elsewhere", False, False, "Studio", "Set on Studio"),
                ("edge", True, True, "", "")):
            with self.subTest(state=state, crosses=crosses, own=own, name=name):
                self.assertEqual(diagram.outcome_for_tile(state, crosses, own, name), expected)

    def test_contact_is_four_pixels_with_round_caps_and_two_pixel_insets(self):
        from PySide6.QtCore import Qt

        canvas = self.canvas
        painter = mock.Mock()
        own = canvas.tiles["home"]
        rect = canvas.tile_rect("home")
        canvas._paint_contact(painter, own, rect, ("right", 50, 150))
        pen = painter.setPen.call_args.args[0]
        self.assertEqual(pen.widthF(), 4)
        self.assertEqual(pen.capStyle(), Qt.PenCapStyle.RoundCap)
        start, end = painter.drawLine.call_args.args
        self.assertEqual(start.x(), rect.right())
        self.assertEqual(end.x(), rect.right())
        self.assertEqual(start.y(), rect.top() + 2)
        self.assertEqual(end.y(), rect.bottom() - 2)

    def test_corner_crossing_dot_has_seven_pixel_diameter(self):
        painter = mock.Mock()
        self.canvas._paint_contact(painter, self.canvas.tiles["home"],
                                   self.canvas.tile_rect("home"), ("corner", "top_right", ""))
        self.assertEqual(painter.drawEllipse.call_args.args[1:], (3.5, 3.5))

    def test_rendered_seam_is_distinct_from_selected_border(self):
        import diagram

        image = self.canvas.grab().toImage()
        seam = self.canvas.tile_rect("home")
        x, y = round(seam.right()), round(seam.center().y())
        self.assertEqual(image.pixelColor(x, y), diagram._colour("signal"))
        self.assertEqual(image.pixelColor(x - 1, y), diagram._colour("signal"))
        self.assertNotEqual(image.pixelColor(x + 3, y), diagram._colour("signal"))
