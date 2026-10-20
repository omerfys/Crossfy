"""The Shortcut tile controls saved global intent and the real sender's trigger."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app_config
import capture_win
import kvm_bridge_win as kvm
from core import settings_sync, ways
from links_rig import Rig
import test_crossing_page_parity as parity


class GlobalShortcutTests(unittest.TestCase):
    setUp = parity.CrossingPageParityTests.setUp
    tearDown = parity.CrossingPageParityTests.tearDown
    _open_window = parity.CrossingPageParityTests._open_window
    _close_window = parity.CrossingPageParityTests._close_window
    _stop_patches = parity.CrossingPageParityTests._stop_patches

    def test_tile_toggles_saved_methods_and_stops_and_starts_shortcut_input(self):
        window = self.window
        self.assertTrue(hasattr(window, "shortcut_tile"), "global Shortcut control is missing")
        tile = window.shortcut_tile
        self.assertTrue(tile.isChecked())
        before = app_config.load_settings(self.path)
        rig = Rig(machine_id=window._config.machine_id)
        shell = SimpleNamespace(sender=rig.sender, _trigger=capture_win.Trigger("ctrl_r", "hold", 300))
        for on in (False, True, False):
            tile.click()
            saved = app_config.load_settings(self.path)
            loaded = app_config.load_config(self.path)
            self.assertEqual("shortcut" in window._config.crossing_methods, on)
            self.assertEqual("shortcut" in loaded.crossing_methods, on)
            self.assertEqual(window.sender.shortcut_armed, on)
            for peer in self.peers:
                self.assertEqual(ways.ways(saved, peer["id"]), ways.ways(before, peer["id"]))
            rig.sender.update_config(loaded)
            kvm.WindowsApplication._on_hook_key(shell, "ctrl_r", True)
            self.assertEqual(rig.sender.redirecting, on)
            kvm.WindowsApplication._on_hook_key(shell, "ctrl_r", False)
            self.assertFalse(rig.sender.redirecting)
        self._close_window()
        self._open_window()
        self.assertFalse(self.window.shortcut_tile.isChecked())
        self.window.shortcut_tile.click()
        self._close_window()
        self._open_window()
        self.assertTrue(self.window.shortcut_tile.isChecked())

    def test_shared_shortcut_arrivals_reflect_without_a_local_toggle(self):
        window = self.window
        self.assertTrue(hasattr(window, "shortcut_tile"), "global Shortcut control is missing")
        peer = self.peers[0]["id"]
        original_tile = window.shortcut_tile
        with patch.object(window, "_ways_changed", side_effect=AssertionError("reflection saved a local toggle")):
            for stamp, on, key in ((100, False, "alt_r"), (101, True, "cmd_r")):
                message = settings_sync.message_data(True, stamp, {"shortcut": on, "trigger_key": key},
                                                     by=peer, groups=["shortcut"])
                window._on_settings(peer, message)
                self.assertIs(window.shortcut_tile, original_tile)
                self.assertEqual(window.shortcut_tile.isChecked(), on)
                self.assertEqual(window.sender.shortcut_armed, on)
                saved = app_config.load_settings(self.path)
                self.assertEqual("shortcut" in app_config.load_config(self.path).crossing_methods, on)
                self.assertEqual(saved["same_set_at"], stamp)
                self.assertEqual(saved["same_by"], peer)
                title = "Right Alt" if key == "alt_r" else "Right Ctrl"
                self.assertEqual(window.shortcut_tile.detail.text(), f"{title}, to where input last went")

    def test_tile_is_first_and_key_detail_tracks_local_recording(self):
        window = self.window
        self.assertTrue(hasattr(window, "shortcut_tile"), "global Shortcut control is missing")
        self.assertIs(window.shortcut_module.body.itemAt(1).widget(), window.shortcut_tile)
        self.assertEqual(window.shortcut_tile.text(), "Shortcut")
        self.assertEqual(window.shortcut_tile.detail.text(), "Right Ctrl, to where input last went")
        window._record_trigger("key", kvm.TRIGGER_VKS["alt_r"])
        self.assertEqual(window.shortcut_tile.accessibleDescription(), "Right Alt, to where input last went")

    def test_destination_choices_refresh_visible_and_accessible_detail(self):
        for mode, ending in (("next", "next in order"), ("ticked", "next among ticked"),
                             ("last", "to where input last went")):
            with self.subTest(mode=mode):
                self.window.shortcut_target_choice._buttons[mode].click()
                expected = f"Right Ctrl, {ending}"
                self.assertEqual(self.window.shortcut_tile.detail.text(), expected)
                self.assertEqual(self.window.shortcut_tile.accessibleDescription(), expected)
                self._close_window()
                self._open_window()
                self.assertEqual(self.window.shortcut_target_choice.value, mode)
                self.assertEqual(self.window.shortcut_tile.detail.text(), expected)


if __name__ == "__main__":
    unittest.main()
