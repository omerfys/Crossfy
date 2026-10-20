import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AtlasCanvasTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

    def test_per_screen_desk_canvas_keeps_a0_b0_a1_and_b1_grouped_by_machine(self):
        from diagram import AtlasCanvas
        from core.tests.crossing_harness import per_screen_layout

        tiles = per_screen_layout("home", "peer")
        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 360)
        canvas.set_tiles(tiles, {"home": "This PC", "peer": "Studio Mac"},
                         {"home": {}, "peer": {"state": "edge", "crosses": True}},
                         "peer", own_id="home")

        a0, a1 = canvas.display_rect("home", "0"), canvas.display_rect("home", "1")
        b0, b1 = canvas.display_rect("peer", "0"), canvas.display_rect("peer", "1")
        self.assertLess(a0.center().x(), b0.center().x())
        self.assertLess(b0.center().x(), a1.center().x())
        self.assertGreater(b1.top(), b0.top())

    def test_split_b1_offset_draws_past_the_nominal_group_bounds(self):
        from diagram import AtlasCanvas
        from core.tests.crossing_harness import per_screen_layout

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 360)
        labels = {"home": "This PC", "peer": "Studio Mac"}
        statuses = {"home": {}, "peer": {"state": "edge", "crosses": True}}
        for offset in (80, 120):
            with self.subTest(b1_offset=offset):
                tiles = per_screen_layout("home", "peer", b1_x=offset)
                canvas.set_tiles(tiles, labels, statuses, "peer", own_id="home")
                group = canvas.tile_rect("peer")
                b1 = canvas.display_rect("peer", "1")
                if offset < 100:
                    self.assertLess(b1.left(), group.left())
                else:
                    self.assertGreater(b1.right(), group.right())

    def test_this_pc_tile_shows_platform_and_linked_status(self):
        import sys

        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC"}, {}, "home", own_id="home")

        state = canvas.states["home"]
        self.assertEqual(state["detail"], "Linux" if sys.platform.startswith("linux") else "Windows")
        self.assertTrue(state["linked"])

    def test_this_pc_tile_keeps_its_machine_name_as_the_own_tile_detail(self):
        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC"}, {"home": {"detail": "Studio PC"}}, "home", own_id="home")

        self.assertEqual(canvas.states["home"]["detail"], "Studio PC")

    def test_this_pc_name_is_painted_in_a_single_display_tile(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage

        from diagram import AtlasCanvas
        import theme

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(480, 268)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100,
                                    "displays": {"main": {"x": 0, "y": 0, "w": 1728, "h": 1117}}}},
                         {"home": "This PC"}, {"home": {"state": "this"}}, "home", own_id="home")
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        canvas.render(image)

        rect = canvas.tile_rect("home")
        ink = QColor(theme.colour("ink"))
        visible_ink = any(
            (lambda pixel: abs(pixel.red() - ink.red()) < 24 and abs(pixel.green() - ink.green()) < 24
             and abs(pixel.blue() - ink.blue()) < 24)(image.pixelColor(x, y))
            for y in range(max(0, int(rect.top()) + 6), min(image.height(), int(rect.top()) + 30))
            for x in range(max(0, int(rect.left()) + 20), min(image.width(), int(rect.right()) - 20)))
        self.assertTrue(visible_ink)

    def test_internal_display_frames_are_drawn_only_for_multiple_displays(self):
        from unittest.mock import patch
        from PySide6.QtCore import Qt, QRectF
        from PySide6.QtGui import QImage

        import diagram
        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(480, 268)
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        rounded_rects = []
        original = diagram.QPainter

        class RecordingPainter(original):
            def drawRoundedRect(self, *args):
                rounded_rects.append(QRectF(args[0]))
                return super().drawRoundedRect(*args)

        def internal_frames(displays):
            rounded_rects.clear()
            canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100, "displays": displays}},
                             {"home": "This PC"}, {"home": {"state": "this"}}, "home", own_id="home")
            with patch.object(diagram, "QPainter", RecordingPainter):
                canvas.render(image)
            tile = canvas.tile_rect("home")
            return [rect for rect in rounded_rects
                    if rect.left() >= tile.left() + 1 and rect.top() >= tile.top() + 1
                    and rect.right() <= tile.right() - 1 and rect.bottom() <= tile.bottom() - 1]

        one = {"main": {"x": 0, "y": 0, "w": 1728, "h": 1117}}
        two = {"left": {"x": 0, "y": 0, "w": 1728, "h": 1117},
               "right": {"x": 1728, "y": 0, "w": 1728, "h": 1117}}
        self.assertEqual(internal_frames(one), [])
        self.assertEqual(len(internal_frames(two)), 2)

    def _wrapping_canvas(self, **states):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(880, 260)
        tiles = {"home": {"x": 0, "y": 0, "w": 160, "h": 100}, "a": {"x": 160, "y": 0, "w": 160, "h": 100},
                 "b": {"x": -160, "y": 0, "w": 160, "h": 100}}
        base = {"a": {"state": "edge", "thirds": ["start", "middle", "end"], "linked": True},
                "b": {"state": "edge", "thirds": ["start", "middle", "end"], "linked": True}}
        for peer, extra in states.items():
            base[peer].update(extra)
        canvas.set_tiles(tiles, {"home": "This PC", "a": "MacBook Pro", "b": "Studio Linux"}, base, "a", own_id="home")
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        canvas.render(image)
        return canvas, canvas.tile_rect("home")

    def test_each_wrap_around_side_draws_a_seam_and_a_label(self):
        canvas, rect = self._wrapping_canvas(a={"wraps": [{"display": None, "side": "left", "parts": ["start", "middle", "end"]},
                                                          {"display": None, "side": "top", "parts": ["start", "middle", "end"]}]})
        seams = {side: (one, two, alpha) for side, one, two, alpha, _width in canvas.seam_paths if side in ("left", "top")}
        one, two, alpha = seams["left"]
        self.assertAlmostEqual((one.x(), one.y(), two.y()), (rect.left(), rect.top() + 2, rect.bottom() - 2))
        self.assertEqual(alpha, 1.0)
        one, two, _alpha = seams["top"]
        self.assertAlmostEqual((one.y(), one.x(), two.x()), (rect.top(), rect.left() + 2, rect.right() - 2))
        self.assertEqual({(side, text) for _peer, side, text, kept, _alpha in canvas.wrap_marks if not kept},
                         {("left", "wraps to MacBook Pro"), ("top", "wraps to MacBook Pro")})

    def test_no_wrap_label_ever_lands_on_the_name_the_detail_line_or_another_label(self):
        """rc4 on the Mac: wrap labels over the tile's name, and three of them stacked when one machine
        wrapped Top, Right and Bottom. Every set of sides for one machine at every height, and for two."""
        import itertools
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QFontMetrics, QImage

        import theme
        import tokens
        from diagram import AtlasCanvas

        sets = [list(sides) for count in range(0, 5)
                for sides in itertools.combinations(("left", "right", "top", "bottom"), count)]
        cases = [(height, sides, []) for height in (60, 70, 80, 90, 100, 130, 180) for sides in sets[1:]]
        cases += [(100, sides, others) for sides in sets for others in sets[1:]]
        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(880, 400)
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        for height, sides, others in cases:
            tiles = {"home": {"x": 0, "y": 0, "w": 160, "h": height}, "a": {"x": 160, "y": 0, "w": 160, "h": height},
                     "b": {"x": -160, "y": 0, "w": 160, "h": height}}
            states = {"a": {"state": "edge", "thirds": ["start", "middle", "end"], "linked": True, "wraps": sides},
                      "b": {"state": "edge", "thirds": ["start", "middle", "end"], "linked": True, "wraps": others}}
            canvas.set_tiles(tiles, {"home": "This PC", "a": "MacBook Pro", "b": "Studio Linux"}, states, "a",
                             own_id="home")
            image.fill(Qt.GlobalColor.transparent)
            canvas.render(image)
            rect = canvas.tile_rect("home")
            title = canvas._title_rect("home", rect)
            name = QFontMetrics(theme.font(tokens.TYPE["body"], 650)).horizontalAdvance("This PC")
            fixed = [QRectF(title.center().x() - name / 2, title.top(), name, title.height()),
                     QRectF(rect.left() + 24, rect.top() + 31, rect.width() - 32, 16)]
            boxes = [box for _side, _text, box in canvas.wrap_label_rects]
            with self.subTest(height=height, sides=sides, others=others):
                for index, box in enumerate(boxes):
                    self.assertTrue(rect.contains(box), (rect, box))
                    for other in fixed + boxes[index + 1:]:
                        self.assertFalse(box.intersects(other), (box, other))
                if rect.height() >= 100:
                    self.assertEqual(len(boxes), bool(sides) + bool(others))

    def test_a_wrap_around_seam_stops_thirteen_pixels_short_of_a_corner_pad(self):
        canvas, rect = self._wrapping_canvas(a={"wraps": ["left", "bottom"], "corners": ["top_left", "bottom_right"]})
        seams = {side: (one, two) for side, one, two, _alpha, _width in canvas.seam_paths if side in ("left", "bottom")}
        self.assertAlmostEqual(seams["left"][0].y(), rect.top() + 13)
        self.assertAlmostEqual(seams["left"][1].y(), rect.bottom() - 2)
        self.assertAlmostEqual(seams["bottom"][0].x(), rect.left() + 2)
        self.assertAlmostEqual(seams["bottom"][1].x(), rect.right() - 13)

    def test_wrap_seams_follow_the_offline_and_not_selected_opacities(self):
        canvas, _rect = self._wrapping_canvas(a={"wraps": ["left"], "linked": False}, b={"wraps": ["right"]})
        alphas = {peer: alpha for peer, _side, _text, _kept, alpha in canvas.wrap_marks}
        self.assertAlmostEqual(alphas["a"], .55)
        self.assertAlmostEqual(alphas["b"], .7)

    def test_a_kept_side_is_a_dashed_faint_seam_with_its_own_label(self):
        canvas, rect = self._wrapping_canvas(a={"kept_wraps": ["bottom"], "edge_off": True})
        (peer, side, text, kept, alpha), = canvas.wrap_marks
        self.assertEqual((peer, side, text, kept, alpha), ("a", "bottom", "wrap kept, Edge off", True, .35))

    def test_one_pad_per_corner_of_every_machine_at_full_and_quiet_opacity(self):
        canvas, _rect = self._wrapping_canvas(a={"corners": ["top_left", "bottom_right"]}, b={"corners": ["top_right"]})
        self.assertEqual(set(canvas.corner_marks), {("a", "top_left", 1.0), ("a", "bottom_right", 1.0), ("b", "top_right", .55)})

    def test_the_tile_says_crosses_for_any_wrap_or_corner_and_edge_off_otherwise(self):
        from PySide6.QtGui import QColor
        from diagram import outcome_for_tile
        import theme

        def foot_is_signal(canvas, peer):
            rect = canvas.tile_rect(peer)
            image = canvas.grab().toImage()
            signal = QColor(theme.colour("signal"))
            return any(abs(image.pixelColor(x, y).red() - signal.red()) < 20 and abs(image.pixelColor(x, y).blue() - signal.blue()) < 20
                       for y in range(int(rect.bottom()) - 24, int(rect.bottom()) - 8)
                       for x in range(int(rect.left()) + 40, int(rect.right()) - 40))
        wrapped, _rect = self._wrapping_canvas(b={"crosses": True, "wraps": ["right"]})
        self.assertTrue(foot_is_signal(wrapped, "b"))
        off, _rect = self._wrapping_canvas(b={"crosses": False, "edge_off": True})
        self.assertFalse(foot_is_signal(off, "b"))
        self.assertEqual(outcome_for_tile("edge", False), "Edge off")
        self.assertEqual(outcome_for_tile("edge", True), "Crosses")

    def test_drag_compiles_layout_and_refuses_overlap_at_nearest_free_snap(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        from diagram import AtlasCanvas
        from core import ways

        drops = []
        settings = {"machine_id": "home", "peers": [{"id": "peer", "side": "right"}], "zones": []}

        def compile_drop(tiles, moved):
            result = ways.compile_layout(settings, tiles, moved=moved)
            refused = result
            if not result["accepted"]:
                tiles[moved] = result["snap"][moved]
                result = ways.compile_layout(settings, tiles)
            drops.append((tiles, moved, result, refused))

        canvas = AtlasCanvas(on_drop=compile_drop)
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 300)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}},
                         "home")
        canvas.show()
        self.app.processEvents()
        start = canvas.tile_rect("peer").center().toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, start + QPoint(-120, 0), 10)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(-120, 0))
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0][1], "peer")
        self.assertTrue(drops[0][2]["accepted"])
        self.assertFalse(drops[0][3]["accepted"])
        self.assertFalse(ways._overlaps(drops[0][0]["peer"], drops[0][0]["home"]))
        self.assertEqual(drops[0][0]["peer"], drops[0][3]["snap"]["peer"])

    def test_alt_click_splits_a_display_and_drag_moves_only_that_display(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        from diagram import AtlasCanvas

        drops = []
        canvas = AtlasCanvas(on_drop=lambda tiles, moved: drops.append((tiles, moved)))
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 300)
        canvas.set_tiles({
            "home": {"x": 0, "y": 0, "w": 160, "h": 100},
            "peer": {"x": 172, "y": 0, "w": 160, "h": 100,
                     "displays": {"left": {"x": 0, "y": 0, "w": 100, "h": 100},
                                  "right": {"x": 100, "y": 0, "w": 100, "h": 100}}},
        }, {"home": "This PC", "peer": "Studio"}, {"peer": {"state": "edge"}}, "home")
        canvas.show()
        self.app.processEvents()

        point = canvas.display_rect("peer", "right").center().toPoint()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, pos=point)
        self.assertIn("right", canvas.tiles["peer"]["display_offsets"])
        self.assertEqual(drops[-1][1], "peer")

        before_tile = dict(canvas.tiles["peer"])
        point = canvas.display_rect("peer", "right").center().toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(canvas, point + QPoint(40, 0), 10)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=point + QPoint(40, 0))
        self.assertEqual(canvas.tiles["peer"]["x"], before_tile["x"])
        self.assertGreater(canvas.tiles["peer"]["display_offsets"]["right"]["x"], 0)

    def test_arrow_moves_focused_tile_a_third_and_announces_sentence(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        canvas.resize(720, 300)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"},
                         {"peer": {"state": "edge", "announcement": "Crosses on the right."}}, "peer")
        self.addCleanup(canvas.deleteLater)
        canvas.show()
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key.Key_Down)
        self.assertEqual(canvas.tiles["peer"]["y"], 33)
        self.assertIn("Studio PC, right of This PC, bottom third.", canvas.accessibleDescription())

    def test_rename_cancel_and_save_actions(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from diagram import AtlasCanvas

        renamed = []
        canvas = AtlasCanvas(on_rename=lambda peer, name: renamed.append((peer, name)))
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 300)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}}, "home")
        canvas.begin_rename("peer")
        canvas.rename_edit.setText("Studio")
        QTest.keyClick(canvas.rename_edit, Qt.Key.Key_Escape)
        self.assertEqual(renamed, [])
        canvas.begin_rename("peer")
        canvas.rename_edit.setText("Studio")
        QTest.keyClick(canvas.rename_edit, Qt.Key.Key_Return)
        self.assertEqual(renamed, [("peer", "Studio")])

    def test_clearing_a_rename_restores_the_machine_name(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from diagram import AtlasCanvas

        renamed = []
        canvas = AtlasCanvas(on_rename=lambda peer, name: renamed.append((peer, name)))
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 300)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}}, "home")
        canvas.begin_rename("peer")
        canvas.rename_edit.clear()
        QTest.keyClick(canvas.rename_edit, Qt.Key.Key_Return)

        self.assertEqual(renamed, [("peer", "")])

    def test_leave_out_and_put_back_move_the_machine_between_canvas_and_shelf(self):
        from diagram import AtlasCanvas

        calls = []
        canvas = AtlasCanvas(on_leave_out=lambda peer, left: calls.append((peer, left)))
        self.addCleanup(canvas.deleteLater)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}}, "home")
        canvas.set_left_out({"peer"}, {"peer": True})
        self.assertIn("peer", canvas.shelf_ids)
        canvas.put_back("peer")
        self.assertEqual(calls, [("peer", False)])

    def test_not_in_use_machines_are_shelved_without_becoming_left_out(self):
        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}}, "peer")
        canvas.set_left_out(set(), {"peer": False})

        self.assertIn("peer", canvas.shelf_ids)
        self.assertNotIn("peer", canvas.left_out_ids)

    def test_shelf_tiles_cannot_be_hit_or_renamed_on_the_canvas(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 300)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 0, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Shelf"}, {}, "home", own_id="home")
        canvas.set_left_out({"peer"})
        canvas.show()
        point = canvas.tile_rect("peer").center().toPoint()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNone(canvas._drag)
        self.assertEqual(canvas.selected, "home")
        QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNone(canvas._rename_peer)

    def test_drag_keeps_the_map_transform_until_release(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(360, 268)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 160, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Peer"}, {}, "peer", own_id="home")
        canvas.show()
        point = canvas.tile_rect("peer").center().toPoint()
        scale, origin = canvas._scale, canvas._origin
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(canvas, point + QPoint(80, 0))
        self.assertEqual(canvas._scale, scale)
        self.assertEqual(canvas._origin, origin)
        self.assertTrue(canvas.hasMouseTracking())

    def test_pressing_this_machine_never_changes_the_selected_peer(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from diagram import AtlasCanvas

        selected = []
        canvas = AtlasCanvas(on_select=selected.append)
        self.addCleanup(canvas.deleteLater)
        canvas.resize(720, 300)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}}, "peer",
                         own_id="home")
        canvas.show()
        self.app.processEvents()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.tile_rect("home").center().toPoint())

        self.assertEqual(canvas.selected, "peer")
        self.assertEqual(selected, [])

    def test_shortcut_mode_and_tile_cycle_ticks_persist(self):
        from diagram import AtlasCanvas
        from widgets import Choice

        ticks = []
        modes = []
        canvas = AtlasCanvas(on_cycle=lambda peer, enabled: ticks.append((peer, enabled)))
        self.addCleanup(canvas.deleteLater)
        canvas.set_tiles({"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                          "peer": {"x": 172, "y": 0, "w": 160, "h": 100}},
                         {"home": "This PC", "peer": "Studio PC"}, {"peer": {"state": "edge"}}, "home",
                         cycle_mode="ticked")
        canvas.set_cycle("peer", False)
        self.assertEqual(ticks, [("peer", False)])
        choice = Choice((("last", "Last machine"), ("next", "Next in order"),
                         ("ticked", "Next among ticked")), 3, "last", on_change=modes.append)
        choice._buttons["ticked"].click()
        self.assertEqual(modes, ["ticked"])
