"""The Linux-on-Wayland switch that turns on the key combination sending input out from home: shown
only on Wayland, saved, and starting or stopping the GlobalShortcuts session it drives."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication
    import kvm_bridge_win
    import theme
    from core.tests import responder_harness as harness
except ImportError:  # PySide6 is only in the Windows venv
    kvm_bridge_win = None


class RecordingShortcut:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class HomeShortcutSettingTests(unittest.TestCase):
    def window(self, wayland):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QApplication.instance() or QApplication([])
        theme.init_fonts()
        folder = Path(tempfile.mkdtemp())
        self.config = folder / "settings.json"
        raw = {"host": "192.0.2.20", "port": harness.free_port(), "auth_token": "synthetic", "paired_with": "MacBook Pro",
               "mac_host": "192.0.2.10", "mac_return_edge": "left"}
        (folder / "config.json").write_text(json.dumps(raw))
        patch = mock.patch.object(kvm_bridge_win.platform_parts, "WAYLAND", wayland)
        patch.start()
        self.addCleanup(patch.stop)
        window = kvm_bridge_win.WindowsApplication(self.config)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.server.stop)
        return window

    def test_off_by_default_and_hidden_off_wayland(self):
        window = self.window(wayland=False)
        self.assertFalse(window._config.home_shortcut)
        self.assertFalse(window.home_shortcut_switch.isChecked())
        self.assertTrue(window.home_shortcut_switch.isHidden())
        self.assertTrue(window.home_shortcut_note.isHidden())

    def test_on_wayland_turning_it_on_saves_and_starts_the_session_and_off_stops_it(self):
        window = self.window(wayland=True)
        self.assertFalse(window.home_shortcut_switch.isHidden())
        window.global_shortcut = RecordingShortcut()
        window.home_shortcut_switch.setChecked(True)
        self.assertTrue(json.loads(self.config.read_text())["home_shortcut"])
        window.home_shortcut_switch.setChecked(False)
        self.assertFalse(json.loads(self.config.read_text())["home_shortcut"])
        self.assertEqual(window.global_shortcut.calls, ["start", "stop"])


if __name__ == "__main__":
    unittest.main()
