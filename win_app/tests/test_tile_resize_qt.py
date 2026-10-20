"""Manual tile resize gestures; written for Qt, never run by the edits-only task."""

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TileResizeQtTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from diagram import AtlasCanvas

        self.app = QApplication.instance() or QApplication([])
        self.drops = mock.Mock(return_value=True)
        self.canvas = AtlasCanvas(on_drop=self.drops)
        self.addCleanup(self.canvas.deleteLater)
        self.canvas.resize(240, 268)
        self.canvas.on_announce = mock.Mock()
        self.canvas.on_leave_out = mock.Mock()
        self.canvas.set_tiles(
            {"home": {"x": 0, "y": 0, "w": 160, "h": 100},
             "peer": {"x": 160, "y": 0, "w": 160, "h": 100}},
            {"home": "This PC", "peer": "Studio PC with a very long name"},
            {}, "peer", own_id="home")

    def mouse_event(self, kind, point):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QMouseEvent

        return QMouseEvent(getattr(QEvent.Type, kind), point, point,
                           Qt.MouseButton.NoButton if kind == "MouseMove" else Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton if kind != "MouseButtonRelease" else Qt.MouseButton.NoButton,
                           Qt.KeyboardModifier.NoModifier)

    def drag(self, dx, dy, peer="peer"):
        from PySide6.QtCore import QPointF

        canvas = self.canvas
        start = canvas._resize_grip_rect(peer).center()
        end = start + QPointF(dx, dy)
        canvas.mousePressEvent(self.mouse_event("MouseButtonPress", start))
        canvas.mouseMoveEvent(self.mouse_event("MouseMove", end))
        self.drops.assert_not_called()
        canvas.mouseReleaseEvent(self.mouse_event("MouseButtonRelease", end))

    def test_grip_drag_uses_map_scale_keeps_aspect_and_commits_one_drop(self):
        from PySide6.QtCore import Qt
        from core import ways

        canvas = self.canvas
        before = copy.deepcopy(canvas.tiles)
        scale = canvas._scale
        self.assertLess(scale, 1)
        with mock.patch.object(ways, "resize_from_drag", wraps=ways.resize_from_drag) as resize:
            self.drag(32 * scale, 20 * scale)
        resize.assert_called_once()
        source, dx, dy = resize.call_args.args
        self.assertEqual(source, before["peer"])
        self.assertAlmostEqual(dx, 32)
        self.assertAlmostEqual(dy, 20)
        self.drops.assert_called_once()
        tiles, peer = self.drops.call_args.args
        self.assertEqual(peer, "peer")
        self.assertEqual(tiles[peer], {"x": 160, "y": 0, "w": 192, "h": 120})
        self.assertEqual(tiles["home"], before["home"])
        self.assertEqual(tiles[peer]["w"] / tiles[peer]["h"], 1.6)
        canvas.on_announce.assert_called_once_with("Studio PC with a very long name resized.")
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_drag_clamps_at_both_limits(self):
        from core import ways

        for delta, limit in ((-10000, ways.RESIZE_MIN), (10000, ways.RESIZE_MAX)):
            with self.subTest(limit=limit):
                self.drops.reset_mock()
                self.drag(delta, delta)
                self.drops.assert_called_once()
                tile = self.drops.call_args.args[0]["peer"]
                self.assertEqual(max(tile["w"], tile["h"]), limit)
                self.assertEqual(tile["w"] / tile["h"], 1.6)
                self.canvas.on_leave_out.assert_not_called()

    def test_drag_resizes_display_offsets_without_mutating_the_start_tile(self):
        canvas = self.canvas
        canvas.tiles["peer"].update(
            displays={"main": {"x": 0, "y": 0, "w": 160, "h": 100}},
            display_offsets={"main": {"x": -16, "y": -8}})
        canvas._geometry()
        before = copy.deepcopy(canvas.tiles["peer"])
        self.drag(80 * canvas._scale, 50 * canvas._scale)
        tile = self.drops.call_args.args[0]["peer"]
        self.assertEqual((tile["w"], tile["h"]), (240, 150))
        self.assertEqual(tile["display_offsets"], {"main": {"x": -24, "y": -12}})
        self.assertEqual(tile["displays"], before["displays"])
        self.assertEqual(canvas._tile_start, before)

    def test_resize_freezes_geometry_and_does_not_show_a_move_snap_preview(self):
        from PySide6.QtCore import QPointF, Qt

        canvas = self.canvas
        start = canvas._resize_grip_rect("peer").center()
        geometry = (canvas._scale, canvas.tile_rect("home"))
        canvas.mousePressEvent(self.mouse_event("MouseButtonPress", start))
        canvas.mouseMoveEvent(self.mouse_event("MouseMove", start + QPointF(10, 10)))
        self.assertEqual((canvas._scale, canvas.tile_rect("home")), geometry)
        self.assertIsNone(canvas.snap_preview())
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)
        self.drops.assert_not_called()

    def test_grip_is_visible_for_selection_or_hover_and_clears_on_leave(self):
        from PySide6.QtCore import QEvent, Qt

        canvas = self.canvas
        canvas.selected = "home"
        self.assertIsNone(canvas._resize_grip_rect("peer"))
        event = self.mouse_event("MouseMove", canvas.tile_rect("peer").center())
        canvas.mouseMoveEvent(event)
        grip = canvas._resize_grip_rect("peer")
        self.assertIsNotNone(grip)
        canvas.mouseMoveEvent(self.mouse_event("MouseMove", grip.center()))
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)
        canvas.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertIsNone(canvas._resize_grip_rect("peer"))

    def test_no_grip_or_keyboard_resize_when_read_only_or_shelved(self):
        canvas = self.canvas
        for restriction in ("read_only", "left_out", "not_in_use", "dormant"):
            with self.subTest(restriction=restriction):
                canvas.read_only = restriction == "read_only"
                canvas.set_left_out({"peer"} if restriction == "left_out" else set(),
                                    {"peer": False} if restriction == "not_in_use" else {},
                                    {"peer"} if restriction == "dormant" else set())
                before = copy.deepcopy(canvas.tiles)
                self.assertIsNone(canvas._resize_grip_rect("peer"))
                self.key("Right")
                self.assertEqual(canvas.tiles, before)
        self.drops.assert_not_called()

    def test_machine_grip_does_not_cover_another_machines_split_display(self):
        canvas = self.canvas
        canvas.tiles["home"].update(
            displays={"main": {"x": 0, "y": 0, "w": 160, "h": 100}},
            display_offsets={"main": {"x": 160, "y": 0}})
        canvas._geometry()
        self.assertIsNone(canvas._resize_grip_rect("peer"))
        split = canvas.display_rect("home", "main")
        self.assertIsNone(canvas._resize_at(split.bottomRight()))

    def key(self, direction, alt=True):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        self.canvas.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, getattr(Qt.Key, "Key_" + direction),
            Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier))

    def test_alt_arrows_resize_by_an_eighth_and_leave_position_unchanged(self):
        from core import ways

        for direction, sign in (("Right", 1), ("Down", 1), ("Left", -1), ("Up", -1)):
            with self.subTest(direction=direction):
                before = copy.deepcopy(self.canvas.tiles["peer"])
                long_side = max(before["w"], before["h"])
                self.drops.reset_mock()
                with mock.patch.object(ways, "resize_tile", wraps=ways.resize_tile) as resize:
                    self.key(direction)
                resize.assert_called_once_with(before, long_side + sign * long_side / 8)
                self.drops.assert_called_once()
                tile = self.drops.call_args.args[0]["peer"]
                self.assertEqual((tile["x"], tile["y"]), (before["x"], before["y"]))
                self.assertEqual(tile, ways.resize_tile(before, long_side + sign * long_side / 8))

    def test_own_tile_can_resize_but_plain_arrows_do_not_move_it(self):
        self.canvas.selected = "home"
        self.key("Left")
        self.drops.assert_called_once()
        self.assertEqual(self.drops.call_args.args[0]["home"], {"x": 0, "y": 0, "w": 140, "h": 88})
        self.drops.reset_mock()
        self.key("Right", alt=False)
        self.drops.assert_not_called()
        self.drag(14 * self.canvas._scale, 0, peer="home")
        self.drops.assert_called_once()

    def test_profile_resize_is_not_a_profile_click_even_with_a_short_drag(self):
        self.canvas.profile_mode = True
        self.canvas.on_edit_machine = mock.Mock()
        self.drag(1, 1)
        self.drops.assert_called_once()
        self.canvas.on_edit_machine.assert_not_called()

    def test_small_tile_resize_grip_does_not_steal_the_cycle_tick(self):
        canvas = self.canvas
        canvas.cycle_mode = "ticked"
        canvas.on_cycle = mock.Mock()
        canvas.resize(480, 268)
        for height in (44, 50, 40):
            with self.subTest(height=height):
                canvas.tiles["peer"].update(w=100, h=height)
                canvas._geometry()
                rect = canvas.tile_rect("peer")
                grip = canvas._resize_grip_rect("peer")
                box = canvas._cycle_box(rect)
                self.assertFalse(grip.intersects(box))
                point = box.center()
                canvas.mousePressEvent(self.mouse_event("MouseButtonPress", point))
                self.assertIsNone(canvas._drag)
                self.assertFalse(canvas._resizing)
        self.assertEqual(canvas.on_cycle.call_count, 3)
        self.drops.assert_not_called()

    def test_rejected_resize_is_not_announced_as_success(self):
        self.drops.return_value = False
        self.key("Right")
        self.drops.assert_called_once()
        self.canvas.on_announce.assert_not_called()

    def test_small_tile_keeps_full_name_in_tooltip_and_accessible_description(self):
        from PySide6.QtGui import QFontMetrics
        import theme
        import tokens

        self.drag(-10000, -10000)
        canvas = self.canvas
        name = canvas.labels["peer"]
        title = canvas._title_rect("peer", canvas.tile_rect("peer"))
        self.assertLess(title.width(), QFontMetrics(theme.font(tokens.TYPE["body"], 650)).horizontalAdvance(name))
        canvas.mouseMoveEvent(self.mouse_event("MouseMove", canvas.tile_rect("peer").center()))
        self.assertEqual(canvas.toolTip(), name)
        self.assertIn(name, canvas.accessibleDescription())
        self.assertIn("size can be changed", canvas.accessibleDescription())


class TileResizePageQtTests(unittest.TestCase):
    def setUp(self):
        import test_crossing_page_parity as fixture

        fixture.CrossingPageParityTests.setUp(self)

    def _open_window(self):
        import test_crossing_page_parity as fixture

        fixture.CrossingPageParityTests._open_window(self)

    def tearDown(self):
        import test_crossing_page_parity as fixture

        fixture.CrossingPageParityTests._close_window(self)

    def _stop_patches(self):
        import test_crossing_page_parity as fixture

        fixture.CrossingPageParityTests._stop_patches(self)

    def test_off_hint_adds_resize_and_profiles_on_hint_stays_the_same(self):
        from core import crossing_state

        window = self.window
        self.assertEqual(window.atlas_canvas_hint.text(),
                         "Alt-click a display to split or group · drag to move · click a third of a lit edge to leave it out · drag a corner to resize")
        window._design_peer_caps = lambda: {entry["id"]: {"layout", "profiles"} for entry in self.peers}
        window._profile_event(crossing_state.set_same_ways, True)
        self.assertEqual(window.atlas_canvas_hint.text(),
                         "Click a machine to set its ways · Tab and Return pick one from the keyboard")

    def test_own_resize_reaches_the_existing_crossing_drop_handler(self):
        import app_config
        from core import crossing_state, ways

        window = self.window
        own = window._config.machine_id
        tiles = copy.deepcopy(window.atlas_canvas.tiles)
        tiles[own] = ways.resize_tile(tiles[own], max(tiles[own]["w"], tiles[own]["h"]) * 7 / 8)
        with mock.patch.object(crossing_state, "drop", wraps=crossing_state.drop) as drop:
            self.assertTrue(window._layout_dropped(tiles, own))
        drop.assert_called_once()
        self.assertEqual(drop.call_args.args[1][own], tiles[own])
        self.assertEqual(app_config.load_settings(self.path)["layout"][own], tiles[own])

    def test_own_move_is_still_rejected_by_the_existing_drop_handler(self):
        import app_config
        from core import crossing_state

        before = app_config.load_settings(self.path)
        own = self.window._config.machine_id
        tiles = copy.deepcopy(self.window.atlas_canvas.tiles)
        tiles[own]["x"] += 20
        with mock.patch.object(crossing_state, "drop", wraps=crossing_state.drop) as drop:
            self.assertFalse(self.window._layout_dropped(tiles, own))
        drop.assert_not_called()
        self.assertEqual(app_config.load_settings(self.path), before)


if __name__ == "__main__":
    unittest.main()
