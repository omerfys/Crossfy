"""Profile choices in the real Qt tray; run offscreen, without capture or receivers."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app_config
from core import crossing_state, profiles
from win_app.tests import test_tray_icon as fixture


@unittest.skipIf(fixture.kvm_bridge_win is None, "needs PySide6")
class ProfilesTrayQtTests(unittest.TestCase):
    setUp = fixture.TrayWindowTest.setUp
    tearDown = fixture.TrayWindowTest.tearDown

    def test_submenu_stays_hidden_when_settings_cannot_be_read(self):
        with patch.object(app_config, "load_settings", side_effect=app_config.SettingsFileError("unreadable")):
            self.window._refresh_tray_profiles()
        self.assertFalse(self.window.profile_menu.menuAction().isVisible())
        self.assertEqual(self.window.profile_menu.actions(), [])
        with patch.object(self.window, "_config", None), patch.object(app_config, "load_settings") as load:
            self.window._refresh_tray_profiles()
        load.assert_not_called()
        self.assertFalse(self.window.profile_menu.menuAction().isVisible())

    def test_submenu_requires_same_ways_and_two_profiles_then_switches(self):
        menu = self.window.profile_menu
        self.assertFalse(menu.menuAction().isVisible())
        settings = app_config.load_settings(self.config)
        settings = crossing_state.set_same_ways(settings, True, platform="pc", now=100)["settings"]
        app_config.write_settings(self.config, settings)
        self.window._refresh_tray_profiles(settings)
        self.assertFalse(menu.menuAction().isVisible())
        settings = crossing_state.new_profile(settings, "Sofa", platform="pc", now=101)["settings"]
        app_config.write_settings(self.config, settings)
        self.window._refresh_tray_profiles(settings)
        self.assertTrue(menu.menuAction().isVisible())
        actions = {action.text(): action for action in menu.actions()}
        self.assertEqual(set(actions), {"Desk", "Sofa"})
        self.assertEqual(sum(action.isChecked() for action in actions.values()), 1)
        target = next(item["id"] for item in profiles.profile_list(settings) if item["name"] == "Sofa")
        if settings["crossing_desk"]["active"]["value"] == target:
            target = profiles.DESK_ID
            actions["Desk"].trigger()
        else:
            actions["Sofa"].trigger()
        saved = app_config.load_settings(self.config)
        self.assertEqual(saved["crossing_desk"]["active"]["value"], target)
        self.assertEqual(sum(action.isChecked() for action in menu.actions()), 1)
        saved = crossing_state.set_same_ways(saved, False, platform="pc", now=102)["settings"]
        self.window._refresh_tray_profiles(saved)
        self.assertFalse(menu.menuAction().isVisible())


if __name__ == "__main__":
    unittest.main()
