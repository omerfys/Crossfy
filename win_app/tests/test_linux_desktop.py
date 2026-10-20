import unittest
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import linux_desktop


class DesktopTests(unittest.TestCase):
    def test_desktop_tokens_are_case_insensitive_and_colon_separated(self):
        for value in ("KDE", "kde", "KDE:Plasma", "plasma", "Something:KDE"):
            with self.subTest(value=value):
                self.assertEqual(linux_desktop.desktop({"XDG_CURRENT_DESKTOP": value}), "kde")
        for value in ("GNOME", "ubuntu:GNOME", "GNOME-Classic:GNOME"):
            with self.subTest(value=value):
                self.assertEqual(linux_desktop.desktop({"XDG_CURRENT_DESKTOP": value}), "gnome")

    def test_session_desktop_is_a_fallback_not_an_override(self):
        self.assertEqual(linux_desktop.desktop({"XDG_SESSION_DESKTOP": "KDE"}), "kde")
        self.assertEqual(linux_desktop.desktop({"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_DESKTOP": "KDE"}), "gnome")
        self.assertEqual(linux_desktop.desktop({"XDG_CURRENT_DESKTOP": "Xfce"}), "")
        self.assertEqual(linux_desktop.desktop({}), "")
        self.assertEqual(linux_desktop.desktop({"XDG_CURRENT_DESKTOP": "not-kde"}), "")


class CrossingGuidanceTests(unittest.TestCase):
    def test_plasma_has_kwin_guidance_and_gnome_keeps_its_extension_note(self):
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
        import kvm_bridge_win as bridge

        app = QApplication.instance() or QApplication([])
        for name, shown, included, excluded in (
            ("KDE", True, "KWin", "AppIndicator"),
            ("ubuntu:GNOME", True, "AppIndicator", "KWin"),
            ("Xfce", False, "", "KWin"),
        ):
            with self.subTest(desktop=name), mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": name}), mock.patch.object(bridge.sys, "platform", "linux"):
                host = QWidget()
                layout = QVBoxLayout(host)
                view = SimpleNamespace(
                    _ways_module=lambda _: QWidget(), _pointer_module=lambda _: QWidget(), _resistance_module=lambda _: QWidget(),
                    _shortcut_module=lambda _: QWidget(), _profile_override_module=lambda: QWidget(),
                    _profile_ledger_module=lambda: QWidget(), _way_home_module=lambda: QWidget(),
                    _reflect_ways=lambda: None, _reflect_other_name=lambda: None,
                )
                bridge.WindowsApplication._crossing_page(view, layout, bridge.default_config())
                self.assertEqual(not view.linux_tray_note.isHidden(), shown)
                self.assertIn(included, view.linux_tray_note.text())
                self.assertNotIn(excluded, view.linux_tray_note.text())
                host.deleteLater()
