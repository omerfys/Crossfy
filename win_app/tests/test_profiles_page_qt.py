"""Profiles page behaviour; run offscreen, one module per process."""

import unittest
import sys
from unittest.mock import patch

import test_crossing_page_parity as fixture
from core import crossing_state, profiles, ways
import app_config
from PySide6.QtWidgets import QBoxLayout, QLabel


class ProfilesPageTests(unittest.TestCase):
    setUp = fixture.CrossingPageParityTests.setUp
    tearDown = fixture.CrossingPageParityTests.tearDown
    _open_window = fixture.CrossingPageParityTests._open_window
    _close_window = fixture.CrossingPageParityTests._close_window
    _stop_patches = fixture.CrossingPageParityTests._stop_patches

    def enable(self):
        self.window._design_peer_caps = lambda: {
            entry["id"]: {"layout", "profiles"} for entry in self.peers}
        self.window._profile_event(crossing_state.set_same_ways, True)
        fixture.settle(self.window)

    def test_off_keeps_tabs_hidden_and_home_available(self):
        self.assertFalse(self.window.profile_tabs.isVisible())
        self.assertFalse(self.window.same_ways_switch.isChecked())
        self.assertTrue(self.window.shake_home_switch.isChecked())
        self.assertTrue(self.window.profile_off_note.isVisible())
        self.assertEqual(self.window.shake_sensitivity.value(), 100)

    def test_way_home_sensitivity_is_saved_and_reflected(self):
        self.window.shake_sensitivity.setValue(150)
        settings = app_config.load_settings(self.path)
        self.assertEqual(profiles.shake_sensitivity(settings), 150)
        self.assertEqual(self.window.shake_sensitivity.value(), 150)
        self.assertEqual(self.window.shake_sensitivity_figure.text(), "150 %")

    def test_profile_tabs_and_read_only_overview_follow_switch(self):
        self.enable()
        window = self.window
        self.assertTrue(window.profile_tabs.isVisible())
        self.assertIn("On", window.same_ways_summary.text())
        settings = app_config.load_settings(self.path)
        before = profiles.view_row(settings, settings["machine_id"])
        window._profile_event(crossing_state.new_profile, "Sofa")
        settings = app_config.load_settings(self.path)
        sofa = next(item["id"] for item in profiles.profile_list(settings) if item["name"] == "Sofa")
        window._profile_event(crossing_state.switch_profile, sofa)
        self.assertEqual(app_config.load_settings(self.path)["crossing_desk"]["active"]["value"], sofa)
        self.assertEqual(profiles.view_row(app_config.load_settings(self.path), settings["machine_id"]), before)

    def test_remote_view_edits_that_row_and_hides_local_controls(self):
        self.enable()
        window = self.window
        machine, destination = (entry["id"] for entry in self.peers)
        window._edit_profile_machine(machine)
        fixture.settle(window)
        self.assertEqual(window.atlas_canvas.own_id, machine)
        self.assertEqual(window._crossing_view_settings()["machine_id"], machine)
        self.assertIn("MacBook Pro", window.profile_editing.text())
        self.assertFalse(window.pointer_module.isVisible())
        window._write_ways(peer=destination, edge=False, corners=["top_left"])
        settings = app_config.load_settings(self.path)
        self.assertFalse(profiles.view_row(settings, machine)[destination]["ways"]["edge"])
        self.assertTrue(window.profile_back.isVisible())
        window.profile_back.click()
        self.assertFalse(window._profile_remote())

    def test_same_ways_shelves_left_out_machine_in_picker_and_remote_layout(self):
        own = app_config.load_settings(self.path)["machine_id"]
        viewed, shelved = (entry["id"] for entry in self.peers)
        settings = app_config.load_settings(self.path)
        next(peer for peer in settings["peers"] if peer["id"] == shelved).update(
            left_out=True)
        settings["layout"][shelved] = dict(settings["layout"][viewed])
        app_config.write_settings(self.path, settings)

        self.enable()
        self.window._edit_profile_machine(shelved)
        self.assertEqual(self.window._profile_machine(), own)
        self.window._edit_profile_machine(viewed)
        viewed_settings = self.window._crossing_view_settings()
        self.assertEqual(viewed_settings["machine_id"], viewed)
        states = ways.compile_layout(viewed_settings, viewed_settings["layout"], platform="pc")["tiles"]
        self.assertEqual(states[shelved]["state"], "dormant")
        self.assertNotEqual(states.get(own, {}).get("state"), "overlap")
        self.assertNotEqual(states.get(viewed, {}).get("state"), "overlap")

    def test_older_machine_is_read_only(self):
        self.enable()
        machine, destination = (entry["id"] for entry in self.peers)
        self.window._design_peer_caps = lambda: {machine: {"layout"}, destination: {"layout", "profiles"}}
        self.window._edit_profile_machine(machine)
        before = app_config.load_settings(self.path)
        self.assertTrue(self.window._profile_read_only())
        self.assertFalse(self.window._write_ways(peer=destination, edge=False))
        self.assertEqual(app_config.load_settings(self.path), before)
        self.assertIn("Read only", self.window.profile_machine_status.text())

    def test_profile_actions_create_rename_and_protect_active_profile(self):
        self.enable()
        window = self.window
        self.assertTrue(window.profile_actions.isVisible())
        self.assertFalse(window.profile_delete.isEnabled(), "the only profile cannot go")

        window.profile_new.click()
        window.profile_name.setText("Sofa")
        window._save_profile_name()
        settings = app_config.load_settings(self.path)
        sofa = next(item["id"] for item in profiles.profile_list(settings) if item["name"] == "Sofa")
        window._reflect_ways()
        self.assertTrue(window.profile_delete.isEnabled())
        # Rename names the active profile (Desk); a tab click would switch the desk.
        window.profile_rename.click()
        self.assertEqual(window.profile_name.text(), "Desk")
        window.profile_name.setText("Studio desk")
        window._save_profile_name()
        names = {item["name"] for item in profiles.profile_list(app_config.load_settings(self.path))}
        self.assertEqual(names, {"Studio desk", "Sofa"})
        # Delete offers only the profiles that are not active.
        menu = window._profile_delete_menu()
        self.assertEqual([action.text() for action in menu.actions()], ["Sofa"])
        menu.deleteLater()
        window._profile_event(crossing_state.remove_profile, sofa)
        self.assertEqual(len(profiles.profile_list(app_config.load_settings(self.path))), 1)
        window._reflect_ways()
        self.assertFalse(window.profile_delete.isEnabled())

    def test_override_actions_share_a_plain_row_with_archive(self):
        self.enable()
        window = self.window
        self.assertEqual(window.profile_keep_own.parentWidget(), window.profile_archive_toggle.parentWidget())
        for widget in (window.profile_header, window.profile_tabs, window.profile_own_actions, window.profile_archive):
            self.assertEqual(widget.property("vernier"), "plain")
        window.profile_archive_toggle.click()
        self.assertIn("▴", window.profile_archive_toggle.text())
        window.profile_archive_toggle.click()
        self.assertIn("▾", window.profile_archive_toggle.text())

    def test_remote_header_order_and_shortcut_link_open_overview(self):
        self.enable()
        window = self.window
        window._edit_profile_machine(self.peers[0]["id"])
        fixture.settle(window)
        self.assertEqual(window.profile_editing.parentWidget(), window.profile_back.parentWidget())
        self.assertEqual(window.profile_editing.geometry().top(), window.profile_back.geometry().top())
        body = window.profile_ledger_module.body
        self.assertLess(body.indexOf(window.profile_editing_row), body.indexOf(window.profile_machine_status))
        self.assertLess(body.indexOf(window.profile_machine_status), body.indexOf(window.profile_remote_note))
        self.assertLess(body.indexOf(window.profile_remote_note), body.indexOf(window.profile_permissions_note))
        self.assertIsInstance(window.profile_shortcut, QLabel)
        self.assertIn("font-family", window.profile_shortcut.text())
        with patch.object(window, "_select_page", wraps=window._select_page) as select:
            window.profile_shortcut.linkActivated.emit("shortcut")
        select.assert_called_with("overview")
        self.assertEqual(window.focusWidget(), window.same_checks["shortcut"])

    def test_remote_warning_uses_viewed_machine_and_preserves_platforms(self):
        self.enable()
        window = self.window
        machine = self.peers[0]["id"]
        window._edit_profile_machine(machine)
        settings = app_config.load_settings(self.path)
        with patch.object(profiles, "no_way_back", return_value=["Studio PC"]) as missing:
            window._reflect_profiles(settings)
        missing.assert_called_once_with(settings, machine)
        self.assertIn("back to MacBook Pro", window.profile_no_return.text())
        viewed = window._crossing_view_settings()
        real = {entry["id"]: entry.get("platform") for entry in settings["peers"]}
        for entry in viewed["peers"]:
            local = "linux" if sys.platform.startswith("linux") else "windows"
            self.assertEqual(entry.get("platform"), local if entry["id"] == settings["machine_id"] else real[entry["id"]])

    def test_profile_hint_and_narrow_header_keep_controls_visible(self):
        self.enable()
        window = self.window
        self.assertTrue(window.atlas_canvas_hint.isVisible())
        self.assertIn("Tab and Return", window.atlas_canvas_hint.text())
        for button in window.profile_buttons.values():
            self.assertGreaterEqual(button.minimumWidth(), button.sizeHint().width())
        window.profile_header.setFixedWidth(280)
        fixture.settle(window)
        self.assertEqual(window.profile_header.layout().direction(), QBoxLayout.Direction.TopToBottom)
        self.assertGreater(window.same_ways_switch.geometry().top(), window.profile_tabs.geometry().bottom())
        window.profile_header.setFixedWidth(600)
        fixture.settle(window)
        self.assertEqual(window.profile_header.layout().direction(), QBoxLayout.Direction.LeftToRight)

    def test_own_override_archive_restore_and_shake(self):
        self.enable()
        window = self.window
        window._profile_event(crossing_state.set_own_ways, True)
        self.assertTrue(window.profile_use_desk.isVisible())
        window.profile_use_desk.click()
        self.assertFalse(app_config.load_settings(self.path)["crossing_own"]["use_own"])
        saved = profiles.saved_list(app_config.load_settings(self.path))
        self.assertTrue(saved)
        window._profile_event(crossing_state.restore_saved, saved[0]["id"])
        self.assertTrue(app_config.load_settings(self.path)["crossing_own"]["use_own"])
        window.shake_home_switch.click()
        self.assertFalse(profiles.shake_on(app_config.load_settings(self.path)))

    def test_invalid_profile_name_and_full_desk_use_page_note(self):
        self.enable()
        self.window._profile_event(crossing_state.new_profile, " ")
        self.assertTrue(self.window.profile_note.text())
        for index in range(7):
            self.window._profile_event(crossing_state.new_profile, str(index))
        self.window._profile_event(crossing_state.new_profile, "Too many")
        self.assertIn("full", self.window.profile_note.text())

    def test_older_version_note_is_consumed_into_page_memory(self):
        with patch.object(app_config, "load_notes", return_value=["older_version"]):
            self.window._reflect_ways()
        self.window._reflect_ways()
        self.assertTrue(self.window.profile_load_note.isVisible())
        self.assertIn("older Beamer", self.window.profile_load_note.text())

    def test_unreadable_settings_leave_a_safe_profile_snapshot(self):
        with patch.object(self.window, "_config", None), \
                patch.object(self.window, "_window_settings", side_effect=app_config.SettingsFileError("unreadable")), \
                patch.object(app_config, "write_settings") as write:
            snapshot = self.window._profile_settings()
        self.assertIn("crossing_own", snapshot)
        self.assertIn("crossing_desk", snapshot)
        self.assertFalse(profiles.same_ways_on(snapshot))
        self.assertTrue(profiles.shake_on(snapshot))
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
