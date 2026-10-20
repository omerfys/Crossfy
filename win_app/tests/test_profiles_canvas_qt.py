"""Profile map selection and remote ledger controls; run offscreen, one module per process."""

import copy
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import ways
from crossing_ledger import CrossingLedger
from diagram import AtlasCanvas
import theme


class ProfilesCanvasTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.edited, self.chosen, self.dropped = [], [], []
        self.canvas = AtlasCanvas(on_edit_machine=self.edited.append, on_select=self.chosen.append,
                                  on_drop=lambda tiles, peer: self.dropped.append((tiles, peer)))
        self.addCleanup(self.canvas.deleteLater)
        self.canvas.resize(720, 268)
        self.tiles = {"home": {"x": 0, "y": 0, "w": 160, "h": 100},
                      "peer": {"x": 160, "y": 0, "w": 160, "h": 100}}
        self.canvas.profile_mode = True
        self.reflect()

    def reflect(self):
        self.canvas.set_tiles(self.tiles, {"home": "This PC", "peer": "Studio Mac"},
                              {"home": {"profile_word": "Own"},
                               "peer": {"linked": False, "profile_word": "Offline"}},
                              "peer", cycle_mode="ticked", own_id="home")

    def test_clicking_each_tile_edits_that_machine_without_selecting_a_destination_or_writing(self):
        for peer in self.tiles:
            QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                             pos=self.canvas.tile_rect(peer).center().toPoint())
        self.assertEqual(self.edited, ["home", "peer"])
        self.assertEqual(self.chosen, [])
        self.assertEqual(self.dropped, [])

    def test_keyboard_can_focus_own_tile_and_activate_it_with_return_or_space(self):
        self.canvas.selected = "peer"
        self.assertTrue(self.canvas.focusNextPrevChild(False))
        self.assertEqual(self.canvas.selected, "home")
        self.assertEqual(self.edited, [])
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            QTest.keyClick(self.canvas, key)
        self.assertEqual(self.edited, ["home", "home"])
        self.assertTrue(self.canvas.rename_edit.isHidden())
        self.assertEqual(self.chosen, [])

    def test_remote_map_keeps_geometry_drag_without_changing_edited_machine(self):
        self.canvas.remote = True
        start = self.canvas.tile_rect("peer").center()
        end = start + QPointF(35, 20)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start.toPoint())
        event = QMouseEvent(QEvent.Type.MouseMove, end, end, Qt.MouseButton.NoButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.canvas.mouseMoveEvent(event)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end.toPoint())
        self.assertEqual(self.edited, [])
        self.assertIsNone(self.canvas._drag)
        self.assertNotEqual(self.canvas.tiles["peer"], self.tiles["peer"])

    def test_read_only_map_can_pick_machine_but_cannot_drag_recentre_or_change_thirds(self):
        self.canvas.read_only = True
        self.reflect()
        before = copy.deepcopy(self.canvas.tiles)
        start = self.canvas.tile_rect("peer").center().toPoint()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.canvas, start + QPoint(30, 0))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(30, 0))
        QTest.keyClick(self.canvas, Qt.Key.Key_Left)
        self.canvas.recentre()
        self.assertEqual(self.canvas.tiles, before)
        self.assertEqual(self.dropped, [])
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(self.edited, ["peer"])
        self.assertTrue(self.canvas.recentre_button.isHidden())

    def test_remote_profile_hides_cycle_and_blocks_rename_and_leave_out(self):
        self.canvas.remote = True
        self.canvas.on_rename = Mock()
        self.canvas.on_leave_out = Mock()
        self.assertFalse(self.canvas._shows_cycle("peer"))
        self.canvas.begin_rename("peer")
        self.canvas.leave_out("peer")
        self.canvas.put_back("peer")
        self.assertTrue(self.canvas.rename_edit.isHidden())
        self.canvas.on_rename.assert_not_called()
        self.canvas.on_leave_out.assert_not_called()

    def test_own_cycle_checkbox_does_not_switch_the_machine_being_edited(self):
        cycled = []
        self.canvas.on_cycle = lambda peer, on: cycled.append((peer, on))
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.canvas._cycle_box(self.canvas.tile_rect("peer")).center().toPoint())
        self.assertEqual(cycled, [("peer", False)])
        self.assertEqual(self.edited, [])

    def test_profile_mode_does_not_force_remote_own_tile_online(self):
        self.canvas.remote = True
        self.canvas.set_tiles(self.tiles, {"home": "Studio PC", "peer": "Studio Mac"},
                              {"peer": {"linked": False, "detail": "macOS", "profile_word": "Offline"}},
                              "home", own_id="peer")
        self.assertFalse(self.canvas.states["peer"]["linked"])
        self.assertEqual(self.canvas.states["peer"]["detail"], "macOS")

    def test_profile_word_is_drawn_on_own_and_older_tiles(self):
        def draw(states):
            self.canvas.set_tiles(self.tiles, {"home": "This PC", "peer": "Studio Mac"},
                                  states, "peer", own_id="home")
            image = QImage(self.canvas.size(), QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            self.canvas.render(image)
            return image

        blank = draw({"home": {"profile_word": ""},
                      "peer": {"legacy": True, "profile_word": ""}})
        for peer, word in (("home", "Own"), ("peer", "Older")):
            with self.subTest(peer=peer):
                states = {"home": {"profile_word": ""},
                          "peer": {"legacy": True, "profile_word": ""}}
                states[peer]["profile_word"] = word
                self.assertNotEqual(draw(states), blank)

    def test_normal_map_click_still_selects_destination(self):
        self.canvas.profile_mode = False
        self.reflect()
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.canvas.tile_rect("peer").center().toPoint())
        self.assertEqual(self.chosen, ["peer"])
        self.assertEqual(self.edited, [])

    def test_profile_word_dot_uses_the_word_even_when_an_older_machine_is_linked(self):
        for word, colour in (("Desk", "signal"), ("Own", "signal"), ("Older", "ink_3"), ("Offline", "ink_3")):
            with self.subTest(word=word):
                self.canvas.set_tiles(self.tiles, {"home": "This PC", "peer": "Studio Mac"},
                                      {"peer": {"linked": True, "profile_word": word}}, "home", own_id="home")
                picture = QImage(self.canvas.size(), QImage.Format.Format_ARGB32)
                picture.fill(Qt.GlobalColor.transparent)
                self.canvas.render(picture)
                rect = self.canvas.tile_rect("peer")
                self.assertEqual(picture.pixelColor(round(rect.left() + 15), round(rect.top() + 39)),
                                 QColor(theme.colour(colour)))

    def test_remote_map_does_not_draw_amber_contacts_between_other_machines(self):
        self.canvas.remote = True
        tiles = {**self.tiles, "third": {"x": 0, "y": -100, "w": 160, "h": 100}}
        self.canvas.set_tiles(tiles, {"home": "This PC", "peer": "Studio Mac", "third": "Laptop"},
                              {"home": {"state": "set-elsewhere"}, "third": {"state": "set-elsewhere"}},
                              "peer", own_id="peer")
        paint_contact = Mock(wraps=self.canvas._paint_contact)
        self.canvas._paint_contact = paint_contact
        picture = QImage(self.canvas.size(), QImage.Format.Format_ARGB32)
        picture.fill(Qt.GlobalColor.transparent)
        self.canvas.render(picture)
        for call in paint_contact.call_args_list:
            self.assertNotIn("amber", call.args)


class ProfilesLedgerTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.remote, self.read_only, self.platform = True, False, "pc"
        self.settings = {"machine_id": "remote", "peers": [{"id": "home", "name": "Studio PC",
                         "ways": {"edge": True, "part": False, "parts": [], "edges": [],
                                  "corner": False, "corners": [], "notch": False}}],
                         "layout": {"remote": {"x": 0, "y": 0, "w": 160, "h": 100},
                                    "home": {"x": 160, "y": 0, "w": 160, "h": 100}}}
        self.owner = SimpleNamespace(**{name: Mock() for name in (
            "_ledger_third", "_ledger_edge", "_ledger_side", "_ledger_corner", "_ledger_jump",
            "_set_shortcut_cycle", "_canvas_left_out", "_jump_arming", "_rename_canvas_peer",
            "_choose_machine", "_write_ways")})
        self.owner._profile_remote = lambda: self.remote
        self.owner._profile_read_only = lambda: self.read_only
        self.owner._crossing_view_settings = lambda: self.settings
        self.owner._profile_settings = lambda: {"machine_id": "home", "peers": [], "crossing_desk": {
            "status": {"remote": {"value": {"platform": self.platform}}}}}
        self.owner._profile_machine = lambda: "remote"
        self.ledger = CrossingLedger(self.owner)
        self.addCleanup(self.ledger.deleteLater)

    def reflect(self):
        reach = {"home": ways.reach(self.settings, "home", platform=self.platform, capable={"home"},
                                   live=lambda _peer: True)}
        self.ledger.reflect(self.settings, self.settings["layout"], {"home": "Studio PC"},
                             "home", lambda _peer: True, "Ctrl Ctrl", reach=reach)
        return self.ledger.rows["home"]

    def test_remote_view_shows_local_machine_destination_but_no_local_controls(self):
        row = self.reflect()
        self.assertEqual(row.name.full_text, "Studio PC")
        for widget in (row.keys, row.rename, row.leave):
            self.assertTrue(widget.isHidden())
        self.assertEqual(row.grid.columnMinimumWidth(3), 0)
        self.assertTrue(row.edge_chips.isEnabled())
        row.begin_rename()
        self.assertTrue(row.edit.isHidden())

    def test_read_only_remote_ledger_disables_ways_without_losing_the_displayed_state(self):
        self.read_only = True
        row = self.reflect()
        self.assertFalse(row.edge_chips.isEnabled())
        self.assertFalse(row.corner_grid.isEnabled())
        self.assertEqual(row.name.full_text, "Studio PC")
        self.read_only = False
        self.assertTrue(self.reflect().edge_chips.isEnabled())

    def test_returning_to_own_ways_restores_keys_and_machine_actions(self):
        # The wide layout, as the window lays it out; an unsized offscreen ledger lays out narrow.
        self.ledger.resize(900, 600)
        row = self.reflect()
        self.remote = False
        self.reflect()
        for widget in (row.keys, row.rename, row.leave):
            self.assertFalse(widget.isHidden())
        self.assertEqual(row.grid.columnMinimumWidth(3), 128)

    def test_remote_mac_shows_notch_and_routes_both_flags_through_profile_write(self):
        self.platform = "mac"
        row = self.reflect()
        self.assertFalse(row.notch_cell.isHidden())
        self.assertTrue(row.keys.isHidden())
        row.notch.click()
        self.owner._write_ways.assert_called_with(peer="home", notch=True)
        self.settings["peers"][0]["ways"]["notch"] = True
        row = self.reflect()
        self.assertTrue(row.notch.isChecked())
        self.assertFalse(row.notch_return.isHidden())
        row.notch_return.click()
        self.owner._write_ways.assert_called_with(peer="home", notch_return=True)


if __name__ == "__main__":
    unittest.main()
