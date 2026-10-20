"""The tray icon: the glyph for who holds input, the receiver badge, and the Show in tray switch,
through the real window built offscreen, which starts no receiver, hooks or announcer."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

    import kvm_bridge_win
    import theme
    import tray_glyph
    from core import receiver
    from core.tests import responder_harness as harness
except ImportError:  # PySide6 is only in the Windows venv
    kvm_bridge_win = None

# The scale factor only takes effect before a QApplication exists, and another test may already
# have made one, so the render runs in its own process.
PROBE = """
from PySide6.QtWidgets import QApplication
app = QApplication([])
import tray_glyph
pixmap = tray_glyph.pixmap(tray_glyph.LOCAL, "connected", 64, False)
print(pixmap.width(), pixmap.toImage().pixelColor(10, 28).alpha())
"""


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class TrayGlyphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        theme.init_fonts()

    def test_glyph_survives_a_scaled_display(self):
        # At 150% the old tray mark once showed only the state dot on a taskbar-coloured square.
        env = dict(os.environ, QT_SCALE_FACTOR="1.5", QT_QPA_PLATFORM="offscreen")
        out = subprocess.run(
            [sys.executable, "-c", PROBE], cwd=Path(__file__).resolve().parent.parent, env=env,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        width, alpha = out.stdout.split()
        self.assertEqual(width, "64")
        # The left screen is filled while input is on this PC.
        self.assertEqual(alpha, "255")

    def test_each_drive_state_draws_its_own_glyph(self):
        images = {drive: tray_glyph.pixmap(drive, "connected", 64, False).toImage() for drive in tray_glyph.DRIVE_STATES}
        self.assertEqual(len({image.constBits().tobytes() for image in images.values()}), 3)
        left, right = (10, 24), (50, 24)
        self.assertEqual(images[tray_glyph.LOCAL].pixelColor(*left).alpha(), 255)
        self.assertEqual(images[tray_glyph.LOCAL].pixelColor(*right).alpha(), 0)
        self.assertEqual(images[tray_glyph.ELSEWHERE].pixelColor(*left).alpha(), 0)
        self.assertEqual(images[tray_glyph.ELSEWHERE].pixelColor(*right).alpha(), 255)
        # Held fills neither screen and draws the bar between them.
        self.assertEqual(images[tray_glyph.HELD].pixelColor(*left).alpha(), 0)
        self.assertEqual(images[tray_glyph.HELD].pixelColor(*right).alpha(), 0)
        self.assertEqual(images[tray_glyph.HELD].pixelColor(32, 8).alpha(), 255)

    def test_a_receiver_that_is_not_running_dims_the_glyph(self):
        left = (10, 24)
        for status, alpha in (("connected", 255), ("waiting", 255), ("error", 102), ("stopped", 102)):
            self.assertEqual(tray_glyph.pixmap(tray_glyph.LOCAL, status, 64, False).toImage().pixelColor(*left).alpha(), alpha, status)

    def test_the_badge_follows_the_receiver_state(self):
        corner = (56, 56)
        colours = {status: tray_glyph.pixmap(tray_glyph.LOCAL, status, 64, False).toImage().pixelColor(*corner).name()
                   for status in ("connected", "waiting", "error", "stopped")}
        self.assertEqual(len(set(colours.values())), 4, colours)

    def test_the_ink_follows_the_taskbar(self):
        left = (10, 24)
        self.assertEqual(tray_glyph.pixmap(tray_glyph.LOCAL, "connected", 64, False).toImage().pixelColor(*left).name(), "#000000")
        self.assertEqual(tray_glyph.pixmap(tray_glyph.LOCAL, "connected", 64, True).toImage().pixelColor(*left).name(), "#ffffff")

    def test_which_glyph(self):
        self.assertEqual(tray_glyph.drive_state(False, False, False), tray_glyph.LOCAL)
        self.assertEqual(tray_glyph.drive_state(True, False, False), tray_glyph.ELSEWHERE)
        self.assertEqual(tray_glyph.drive_state(False, True, False), tray_glyph.ELSEWHERE)
        self.assertEqual(tray_glyph.drive_state(False, False, True), tray_glyph.HELD)
        self.assertEqual(tray_glyph.drive_state(True, False, True), tray_glyph.ELSEWHERE)

    def test_every_size_a_tray_asks_for_is_drawn(self):
        icon = tray_glyph.icon(tray_glyph.LOCAL, "connected", False)
        self.assertEqual({size.width() for size in icon.availableSizes()}, set(tray_glyph.SIZES))


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class TrayWindowTest(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        folder = Path(tempfile.mkdtemp())
        self.config = folder / "settings.json"
        raw = {"host": "192.0.2.20", "port": harness.free_port(), "auth_token": "synthetic", "paired_with": "MacBook Pro",
               "mac_host": "192.0.2.10", "mac_return_edge": "left"}
        (folder / "config.json").write_text(json.dumps(raw))
        patch = mock.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.window = kvm_bridge_win.WindowsApplication(self.config)
        self.shown = [True]
        patch = mock.patch.object(self.window.tray, "setVisible", side_effect=self.shown.append)
        patch.start()
        self.addCleanup(patch.stop)
        # A real QSystemTrayIcon reports visible only on a desktop with a tray.
        patch = mock.patch.object(self.window.tray, "isVisible", side_effect=lambda: self.shown[-1])
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.window.server.stop()
        self.window.deleteLater()

    def test_each_drive_state_sets_the_matching_icon(self):
        cases = (
            ((), tray_glyph.LOCAL),
            ((True, None, False), tray_glyph.ELSEWHERE),
            ((False, b"peer", False), tray_glyph.ELSEWHERE),
            ((False, None, True), tray_glyph.HELD),
        )
        for args, expected in cases:
            with self.subTest(expected=expected, args=args):
                self.window._tray_icon_key = None
                with mock.patch.object(self.window.tray, "setIcon") as set_icon:
                    stack = mock.patch.multiple(
                        type(self.window.sender), redirecting=mock.PropertyMock(return_value=bool(args and args[0])),
                        edges_held=mock.PropertyMock(return_value=bool(args and args[2])))
                    owner = mock.patch.object(type(self.window.server), "owner",
                                              new_callable=mock.PropertyMock, return_value=args[1] if args else None)
                    with stack, owner, mock.patch.object(self.window, "_ways_in", return_value={"edge"}):
                        self.window._refresh_tray_state()
                self.assertEqual(self.window._tray_icon_key[0], expected)
                set_icon.assert_called_once()
                drawn = set_icon.call_args.args[0].pixmap(64, 64).toImage()
                status = self.window._status.value.lower()
                self.assertEqual(drawn, tray_glyph.pixmap(expected, status, 64, self.window._tray_icon_key[2]).toImage())

    def test_held_needs_a_way_to_hold(self):
        # Only the shortcut is on: there is nothing to pause, as on the Mac, which shows Local.
        with mock.patch.object(type(self.window.sender), "edges_held", new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(self.window, "_ways_in", return_value=set()):
            self.assertEqual(self.window._drive_glyph(), tray_glyph.LOCAL)

    def test_the_icon_is_set_again_only_when_something_it_draws_changes(self):
        self.window._tray_icon_key = None
        with mock.patch.object(self.window.tray, "setIcon") as set_icon:
            self.window._refresh_tray_state()
            self.window._refresh_tray_state()
            self.assertEqual(set_icon.call_count, 1)
            self.window._set_status(receiver.ServerState.CONNECTED, "")
            self.app.processEvents()
            self.assertEqual(set_icon.call_count, 2)

    def test_show_in_tray_defaults_on_and_persists(self):
        self.assertTrue(self.window._config.show_in_tray)
        self.assertTrue(self.window.tray_switch.isChecked())
        self.assertTrue(self.window.tray_shown())
        self.window.tray_switch.setChecked(False)
        self.assertEqual(self.shown[-1], False)
        self.assertFalse(self.window.tray_shown())
        self.assertFalse(json.loads(self.config.read_text())["show_in_tray"])
        self.window.tray_switch.setChecked(True)
        self.assertEqual(self.shown[-1], True)
        self.assertTrue(json.loads(self.config.read_text())["show_in_tray"])

    def test_reloading_a_file_that_turns_it_off_takes_the_icon_down(self):
        raw = json.loads(self.config.read_text())
        raw["show_in_tray"] = False
        self.config.write_text(json.dumps(raw))
        self.window.reload_config()
        self.assertFalse(self.window.tray_switch.isChecked())
        self.assertEqual(self.shown[-1], False)

    def test_same_on_all_machines_leaves_it_alone(self):
        self.assertNotIn("show_in_tray", json.dumps(self.window._same_fields(), default=str))

    def test_closing_the_window_with_the_tray_off_quits(self):
        self.window.tray_switch.setChecked(False)
        with mock.patch.object(self.window, "quit") as quit_app:
            self.window.close()
        quit_app.assert_called_once()

    def test_closing_the_window_with_the_tray_on_keeps_beamer_running(self):
        self.window.show()
        with mock.patch.object(self.window, "quit") as quit_app:
            self.window.close()
        quit_app.assert_not_called()
        self.assertFalse(self.window.isVisible())

    def test_a_second_launch_raises_the_window_with_the_tray_off(self):
        self.window.tray_switch.setChecked(False)
        self.window.hide()
        signal = kvm_bridge_win.InstanceSignal(self.window.show_window, name=str(Path(self.config.parent) / "sig"))
        self.addCleanup(signal.close)
        self.assertTrue(signal.listening)
        code = ("import sys\nfrom PySide6.QtCore import QCoreApplication\napp = QCoreApplication([])\nimport kvm_bridge_win\n"
                "sys.exit(0 if kvm_bridge_win.send_instance_activation(sys.argv[1], None, timeout_ms=3000) else 1)\n")
        client = subprocess.Popen([sys.executable, "-c", code, str(Path(self.config.parent) / "sig")],
                                  cwd=Path(__file__).resolve().parent.parent)
        self.addCleanup(client.wait)
        deadline = time.monotonic() + 30
        while not self.window.isVisible() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(client.wait(timeout=10), 0)

    def test_a_hidden_start_has_no_tray_to_stay_in_when_it_is_off(self):
        # main() shows the window of a hidden start whenever tray_shown() is false.
        self.window.tray_switch.setChecked(False)
        self.assertFalse(self.window.tray_shown())
        self.window._config.show_in_tray = True
        self.assertTrue(self.window.tray_shown())


if __name__ == "__main__":
    unittest.main()
