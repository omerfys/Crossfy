"""Regressions from the ledger review and the seven offscreen states."""

import threading
import unittest
from unittest import mock

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

import app_config
import kvm_bridge_win as kvm
import theme
from core import protocol
import test_crossing_page_parity as parity


class CrossingFixPass(unittest.TestCase):
    setUp = parity.CrossingPageParityTests.setUp
    tearDown = parity.CrossingPageParityTests.tearDown
    _open_window = parity.CrossingPageParityTests._open_window
    _close_window = parity.CrossingPageParityTests._close_window
    _stop_patches = parity.CrossingPageParityTests._stop_patches

    def test_keys_preserves_a_concurrent_link_save_and_other_peer_choices(self):
        peer = self.peers[0]["id"]
        load = app_config.load_settings
        started, finished = threading.Event(), threading.Event()
        threads = []
        def link_save():
            started.set()
            with app_config.SETTINGS_LOCK:
                saved = load(self.path)
                saved["peers"][0]["label"] = "Name learned on link"
                saved["peers"][1]["shortcut_cycle"] = False
                app_config.write_settings(self.path, saved)
            finished.set()
        def keys_read(path):
            saved = load(path)
            if not threads:
                thread = threading.Thread(target=link_save)
                threads.append(thread)
                thread.start()
                self.assertTrue(started.wait(1))
                finished.wait(.15)
            return saved
        with mock.patch.object(app_config, "load_settings", side_effect=keys_read):
            self.window._set_shortcut_cycle(peer, False)
        threads[0].join(2)
        self.assertFalse(threads[0].is_alive())
        saved = load(self.path)
        self.assertEqual(saved["peers"][0].get("label"), "Name learned on link")
        self.assertFalse(saved["peers"][0]["shortcut_cycle"])
        self.assertFalse(saved["peers"][1]["shortcut_cycle"])

    def test_link_announcement_arranges_before_picture_without_early_target_send(self):
        peer = protocol.read_id(self.peers[0]["id"])
        for gap in (False, True):
            with self.subTest(gap=gap):
                saved = app_config.load_settings(self.path)
                if gap:
                    saved["layout"][self.peers[0]["id"]]["x"] = 600
                app_config.write_settings(self.path, saved)
                self.window._read_crossing()
                sent = []
                with mock.patch.object(self.window, "_peer_caps", return_value={peer: {"layout", "settings"}}), \
                     mock.patch.object(self.window, "_layout_capable", return_value={self.window._config.machine_id, self.peers[0]["id"]}), \
                     mock.patch.object(self.window, "_send_to", side_effect=lambda target, message: sent.append((target, message))):
                    messages = self.window._announce(peer)
                self.assertEqual([message["type"] for target, message in sent if target == peer], [])
                kinds = [message["type"] for message in messages]
                self.assertLess(kinds.index("arrangement"), kinds.index("settings"))

    def test_worker_own_displays_reads_a_copy_of_the_gui_cache(self):
        from display_map_fixture import refresh_own_displays
        desktop = mock.Mock()
        desktop.display_map.return_value = {"screen": {"x": 0, "y": 0, "w": 160, "h": 100}}
        with mock.patch.object(self.window, "_refresh_own_displays",
                               refresh_own_displays.__get__(self.window)), \
             mock.patch.object(self.window.sender, "_desktop_module", return_value=desktop), \
             mock.patch.object(kvm.platform, "system", return_value="Linux"):
            self.window._displays_changed()
            desktop.display_map.reset_mock()
            result = []
            thread = threading.Thread(target=lambda: result.append(self.window._own_displays()))
            thread.start()
            thread.join(2)
            self.assertEqual(result, [{"screen": {"x": 0, "y": 0, "w": 160, "h": 100}}])
            desktop.display_map.assert_not_called()
            result[0].clear()
            self.assertTrue(self.window._own_displays())

    def test_escape_cancels_jump_and_restores_empty_or_saved_chip(self):
        row = self.window.crossing_ledger.rows[self.peers[0]["id"]]
        for value, text in (("", "Set a key"), ("alt+f18", "Alt F18")):
            with self.subTest(value=value):
                self.window._ledger_jump(row.peer, value)
                row.jump.click()
                self.assertTrue(self.window.sender.jump_recording)
                QTest.keyClick(row.jump, Qt.Key.Key_Escape)
                self.assertFalse(row.jump.armed)
                self.assertFalse(self.window.sender.jump_recording)
                self.assertEqual(row.jump.key.text(), text)
                self.assertFalse(row.jump.hint.isVisible())
                self.assertEqual(row.jump.value, value)

    def test_empty_jump_uses_quiet_sans_text_and_keeps_recorded_chip(self):
        row = self.window.crossing_ledger.rows[self.peers[0]["id"]]
        self.assertEqual(row.jump.property("vernier"), "plain")
        self.assertEqual(row.jump.key.font().family(), theme.font(theme.TYPE["note"]).family())
        self.window._ledger_jump(row.peer, "alt+f18")
        self.assertEqual(row.jump.property("vernier"), "keycap")
        parity.settle(self.window)
        self.assertEqual(row.clear.font().weight(), 400)
        row.clear.click()
        self.assertEqual(row.jump.property("vernier"), "plain")

    def test_checked_keys_indicator_has_a_visible_dark_tick(self):
        check = self.window.crossing_ledger.rows[self.peers[0]["id"]].cycle
        check.setChecked(True)
        image = QImage(check.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        check.render(image)
        dark = sum(1 for y in range(max(0, check.height() // 2 - 5), min(check.height(), check.height() // 2 + 5))
                   for x in range(4, 14) if image.pixelColor(x, y).lightnessF() < .2)
        self.assertGreater(dark, 5)

    def test_hint_gap_is_twelve_pixels_with_and_without_corner(self):
        for width in (900, 960, 640):
            self.window.resize(width, 760)
            for corner in (False, True):
                with self.subTest(width=width, corner=corner):
                    self.window._write_ways(self.peers[0]["id"], corner=corner, corner_at="top_left")
                    parity.settle(self.window)
                    canvas, hint = self.window.atlas_canvas, self.window.atlas_canvas_hint
                    root = self.window.ways_module
                    bottom = canvas.mapTo(root, QPoint(0, canvas.height())).y()
                    self.assertEqual(hint.mapTo(root, QPoint()).y() - bottom, 12)

    def test_wrapped_chips_have_room_for_every_line_in_the_edges_cell(self):
        row = self.window.crossing_ledger.rows[self.peers[0]["id"]]
        self.window._ledger_side(row.peer, "top")
        self.window._ledger_side(row.peer, "bottom")
        for width in (900, 640):
            self.window.resize(width, 760)
            parity.settle(self.window)
            chips = row.edge_chips
            shown = [chip for chip in chips.chips.values() if not chip.isHidden()]
            self.assertEqual(len(shown), 4)
            self.assertGreaterEqual(chips.height(), chips.flow.heightForWidth(chips.width()))
            self.assertGreaterEqual(row.height(), chips.mapTo(row, QPoint()).y() + chips.height())
            for chip in shown:
                self.assertLessEqual(chip.geometry().right(), chips.width())
                self.assertLessEqual(chip.geometry().bottom(), chips.height())

    def test_narrow_jump_stays_beside_its_label(self):
        self.window.resize(640, 700)
        parity.settle(self.window)
        row = self.window.crossing_ledger.rows[self.peers[0]["id"]]
        self.assertLess(row.jump.x(), 60)

    def test_wide_ledger_keeps_its_column_width_and_headers(self):
        self.window.resize(960, 760)
        parity.settle(self.window)
        self.assertFalse(self.window.crossing_ledger.narrow)
        self.assertTrue(self.window.crossing_ledger.header.isVisible())
        self.assertEqual(self.window.atlas_canvas.height(), 260)

    def test_map_background_is_ground(self):
        canvas = self.window.atlas_canvas
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        canvas.render(image)
        self.assertEqual(image.pixelColor(20, 20).name(), theme.colour("ground"))


if __name__ == "__main__":
    unittest.main()
