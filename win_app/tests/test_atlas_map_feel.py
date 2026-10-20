import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AtlasMapFeelTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from diagram import AtlasCanvas

        self.app = QApplication.instance() or QApplication([])
        self.drops = mock.Mock()
        self.canvas = AtlasCanvas(on_drop=self.drops)
        self.addCleanup(self.canvas.deleteLater)
        self.canvas.resize(720, 268)
        self.canvas.set_tiles(
            {"home": {"x": 80, "y": 50, "w": 160, "h": 100},
             "peer": {"x": 240, "y": 72, "w": 120, "h": 60}},
            {"home": "This PC", "peer": "Studio PC"},
            {"peer": {"state": "edge", "crosses": True}}, "peer", own_id="home")

    def test_arrangement_box_centres_and_refits_after_a_peer_moves(self):
        canvas = self.canvas
        def box():
            rects = [canvas.tile_rect(peer) for peer in canvas.tiles]
            left, top = min(rect.left() for rect in rects), min(rect.top() for rect in rects)
            right, bottom = max(rect.right() for rect in rects), max(rect.bottom() for rect in rects)
            return left, top, right, bottom

        before = box()
        self.assertAlmostEqual((before[0]+before[2])/2, canvas.width()/2)
        self.assertAlmostEqual((before[1]+before[3])/2, canvas.height()/2)
        self.assertAlmostEqual(canvas._scale, min((canvas.width()-24)/280, (canvas.height()-24)/100, 1.0))
        before_scale = canvas._scale
        canvas.tiles["peer"].update(x=500, y=280)
        canvas._geometry()
        after = box()
        self.assertNotEqual(after, before)
        self.assertAlmostEqual((after[0]+after[2])/2, canvas.width()/2)
        self.assertAlmostEqual((after[1]+after[3])/2, canvas.height()/2)
        self.assertNotEqual(canvas._scale, before_scale)
        canvas._drag = "peer"
        frozen = (canvas.tile_rect("home"), canvas._scale)
        canvas.tiles["peer"].update(x=-400, y=-250)
        canvas._geometry()
        self.assertEqual((canvas.tile_rect("home"), canvas._scale), frozen)

    def test_recentre_places_peer_and_commits_once(self):
        canvas = self.canvas
        self.assertFalse(canvas.recentre_button.isHidden())
        self.assertEqual(canvas.recentre_button.accessibleName(), "Recentre Studio PC")
        canvas.recentre_button.click()
        self.assertEqual(canvas.tiles["peer"], {"x": 240, "y": 70, "w": 120, "h": 60})
        self.drops.assert_called_once()
        layout, peer = self.drops.call_args.args
        self.assertEqual(peer, "peer")
        self.assertEqual(layout[peer], canvas.tiles[peer])
        self.assertTrue(canvas.recentre_button.isHidden())

    def test_preview_exists_only_within_the_release_radius_and_leaves_tile_at_pointer(self):
        canvas = self.canvas
        canvas._drag = "peer"
        canvas.tiles["peer"].update(x=256, y=70)
        dropped = dict(canvas.tiles["peer"])
        self.assertEqual(canvas.snap_preview(), {"x": 240, "y": 70, "w": 120, "h": 60})
        self.assertEqual(canvas.tiles["peer"], dropped)
        canvas.tiles["peer"]["x"] = 259
        self.assertIsNone(canvas.snap_preview())
        canvas._drag_display = "screen"
        canvas.tiles["peer"]["x"] = 240
        self.assertIsNone(canvas.snap_preview())

    def test_c_key_recentres(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier, "c")
        self.canvas.keyPressEvent(event)
        self.assertEqual(self.canvas.tiles["peer"]["y"], 70)
        self.drops.assert_called_once()

    def test_release_commits_the_preview_with_the_larger_centre_radius(self):
        from PySide6.QtCore import QPointF

        canvas = self.canvas
        canvas._drag = "peer"
        canvas.tiles["peer"].update(x=256, y=70)
        target = canvas.snap_preview()
        event = mock.Mock()
        event.position.return_value = QPointF(400, 150)
        canvas.mouseReleaseEvent(event)
        self.drops.assert_called_once()
        self.assertEqual(self.drops.call_args.args[0]["peer"], target)
