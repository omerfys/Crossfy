"""Crossing parity and repaint stability with synthetic linked desktop peers."""

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QWidget

import app_config
import diagram
import kvm_bridge_win as kvm
import motion
import pages_win
import theme
import widgets
from core import pairing, peerlist
from core.receiver import ServerState


def settle(window):
    for child in window.crossing_document.findChildren(QWidget):
        animation = motion._runs(child).get("shown")
        if animation is not None:
            animation.setCurrentTime(animation.duration())
    for _ in range(8):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        QApplication.processEvents()


def descendants(root):
    return {id(widget): widget for widget in root.findChildren(QWidget)}


def position(widget, root):
    return widget.mapTo(root, QPoint())


class CrossingPageParityTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        self.app.setFont(theme.font(theme.TYPE["body"]))
        # The PC page as Windows and X11 draw it, whatever session runs the suite: Wayland hides the
        # pointer module.
        self.patches = [patch.object(kvm.platform_parts, "WAYLAND", False)]
        self.patches[0].start()
        for name, value in (("installed_exe", lambda: Path("Beamer.exe")),
                            ("is_enabled", lambda: False),
                            ("can_run_for_current_user", lambda: False)):
            patcher = patch.object(kvm.autostart_win, name, value)
            patcher.start()
            self.patches.append(patcher)
        self.addCleanup(self._stop_patches)
        temp_root = Path(__file__).resolve().parents[1] / '.test-tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.tempdir = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.tempdir.cleanup)
        settings = app_config.migrate({"appearance": "dark", "name": "Studio Linux", "peers": [], "check_updates": False})
        settings.update(name="Studio Linux", check_updates=False)
        self.peers = []
        for index, (name, platform) in enumerate((("MacBook Pro", "macos"), ("Desktop PC", "windows"))):
            token = base64.urlsafe_b64encode(bytes([40 + index]) * 32).decode("ascii").rstrip("=")
            entry = pairing.peer_entry(bytes([index + 1]) * 16, name, platform, 24820 + index,
                                       token, f"192.168.1.{10 + index}", 1791321600 + index)
            entry["linked"] = True
            peerlist.add_peer(settings, entry)
            self.peers.append(entry)
        self.path = Path(self.tempdir.name) / "settings.json"
        app_config.write_settings(self.path, settings)
        app_config.set_ways(self.path, self.peers[0]["id"], side="right", methods=[], parts=[], corner="top_left")
        app_config.set_ways(self.path, self.peers[1]["id"], side="left", methods=[], parts=[], corner="top_left")
        settings = app_config.load_settings(self.path)
        own = settings["machine_id"]
        settings["layout"] = {own: {"x": 0, "y": 0, "w": 160, "h": 100},
                              self.peers[0]["id"]: {"x": 160, "y": 0, "w": 160, "h": 100},
                              self.peers[1]["id"]: {"x": -160, "y": 0, "w": 160, "h": 100}}
        app_config.write_settings(self.path, settings)
        self._open_window()

    def _open_window(self):
        self.window = kvm.WindowsApplication(self.path)
        self.window.full_screen_timer.stop()
        self.window.refresh_timer.stop()
        self.window._set_status(ServerState.CONNECTED, "Connected to 192.168.1.10")
        self.window.sender.links.up = lambda _peer: True
        self.window.sender._sock = object()
        self.window.sender.refresh = lambda: None
        self.window.server.peers_changed = lambda: None
        self.window._sync_sending = lambda: None
        # The fixture peers are 1.5.3 desktops. Pinned, because what a live link has advertised by now
        # depends on the machine: on the rig neither had, and both read as 1.5.1 peers with no wraps.
        self.window._design_peer_caps = lambda: {entry["id"]: {"layout"} for entry in self.peers}
        self.window._read_crossing()
        self.window._chosen = self.peers[0]["id"]
        self.window._reflect_ways()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.resize(900, 700)
        self.window.show()
        self.window._select_page("crossing")
        settle(self.window)

    def _stop_patches(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    def tearDown(self):
        self._close_window()

    def _close_window(self):
        self.window.sender._sock = None
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_option_changes_keep_widgets_and_paint_one_batch(self):
        window, peer = self.window, self.peers[0]["id"]
        document = window.crossing_document
        row = window.crossing_ledger.rows[peer]
        previous = descendants(document)
        for change in (
            lambda: window._ledger_edge(peer),
            lambda: window._ledger_third(peer, "middle"),
            lambda: window._ledger_corner(peer, "top_right"),
            lambda: window._ledger_corner(peer, "top_right"),
            lambda: window._set_shortcut_cycle(peer, False),
            lambda: window._choose_machine(self.peers[1]["id"]),
            lambda: window._canvas_left_out(peer, True),
            lambda: window._canvas_left_out(peer, False),
        ):
            batches = []
            original = document.setUpdatesEnabled
            with patch.object(document, "setUpdatesEnabled", lambda value: (batches.append(value), original(value))[1]):
                change()
            settle(window)
            self.assertEqual(batches, [False, True])
            self.assertIs(window.crossing_ledger.rows[peer], row)
            self.assertEqual(descendants(document).keys(), previous.keys())

    def test_guard_restores_updates_after_failure_and_respects_an_outer_freeze(self):
        document = self.window.crossing_document
        with patch.object(self.window.atlas_canvas, "set_tiles", side_effect=RuntimeError("Synthetic refresh failure")):
            with self.assertRaisesRegex(RuntimeError, "Synthetic refresh failure"):
                self.window._reflect_ways()
        self.assertTrue(document.updatesEnabled())
        self.assertEqual(self.window._crossing_update_depth, 0)
        document.setUpdatesEnabled(False)
        self.window._reflect_ways()
        self.assertFalse(document.updatesEnabled())
        document.setUpdatesEnabled(True)

    def test_ledger_and_modules_match_the_reference_order(self):
        window = self.window
        peer = self.peers[0]["id"]
        window._ledger_edge(peer)
        row = window.crossing_ledger.rows[peer]
        contact = next(chip for chip in row.edge_chips.chips.values() if chip.kind == "contact")
        self.assertTrue(contact.isChecked())
        self.assertEqual(contact.toolTip(), "Right edge: touches MacBook Pro; click to turn it off")
        self.assertFalse(any(button.isChecked() for button in row.corner_grid.buttons.values()))
        self.assertEqual(row.cycle.text(), "Right Ctrl")
        self.assertEqual(row.jump.key.text(), "Set a key")
        self.assertTrue(row.corner_grid.buttons["top_left"].isEnabled())
        self.assertFalse(hasattr(window, "way_boxes"))
        self.assertFalse(hasattr(window, "left_out_shelf"))
        sequence = (window.ways_module, window.pointer_module, window.resistance_module, window.shortcut_module)
        ys = [position(item, window.crossing_document).y() for item in sequence]
        self.assertEqual(ys, sorted(ys))
        self.assertFalse(hasattr(window, "route_readout"))

    def test_edge_toggle_keeps_corner_pointer_and_jump_visible(self):
        window, peer = self.window, self.peers[0]["id"]
        row = window.crossing_ledger.rows[peer]
        watched = (row.corner_cell, window.pointer_module, row.jump)
        for on in (True, False):
            window._ways_changed("edge", on)
            settle(window)
            self.assertTrue(all(not widget.isHidden() for widget in watched))
            self.assertEqual(window.dragging_switch.isEnabled(), on)

    def test_edge_off_clears_map_crossing_and_reticking_restores_the_whole_edge(self):
        window, peer = self.window, self.peers[0]["id"]
        window._ledger_edge(peer)
        window._ledger_third(peer, "middle")
        window._ledger_edge(peer)
        state = window.atlas_canvas.states[peer]
        self.assertFalse(state["crosses"])
        self.assertTrue(state["edge_off"])
        contact = next(chip for chip in window.crossing_ledger.rows[peer].edge_chips.chips.values() if chip.kind == "contact")
        self.assertFalse(contact.isChecked())
        window._ledger_edge(peer)
        self.assertTrue(window.atlas_canvas.states[peer]["crosses"])
        self.assertTrue(contact.isChecked())
        self.assertEqual([segment.isChecked() for segment in contact.segments.values()], [True, True, True])

    def test_shortcut_settings_and_figures_keep_their_order(self):
        window = self.window
        module = window.shortcut_module
        sequence = (window.trigger_recorder, window.trigger_style_row, window.shortcut_target_row,
                    window.shortcut_target_note, window.double_tap_row, window.style_hint)
        self.assertEqual([position(item, module).y() for item in sequence],
                         sorted(position(item, module).y() for item in sequence))
        self.assertIsInstance(window.resistance_readout, widgets.Figure)
        self.assertIsInstance(window.double_tap_readout, widgets.Figure)
        self.assertEqual(window.double_tap_slider.ticks, (50, 150, 300, 600, 1000))

    def test_ledger_controls_fit_at_640_and_900(self):
        for width in (640, 900):
            self.window.resize(width, 700)
            settle(self.window)
            ledger = self.window.crossing_ledger
            for row in ledger.rows.values():
                chips = [chip for chip in row.edge_chips.chips.values() if not chip.isHidden()]
                self.assertTrue(chips)
                for control in (*row.cells, row.rename, row.leave, row.jump, row.cycle, *chips,
                                *row.corner_grid.buttons.values()):
                    point = position(control, ledger)
                    self.assertGreaterEqual(point.x(), 0)
                    self.assertLessEqual(point.x() + control.width(), ledger.width() + 1)

    def test_keys_tick_supports_keyboard_and_accessibility(self):
        row = self.window.crossing_ledger.rows[self.peers[0]["id"]]
        self.assertEqual(row.cycle.toolTip(), "In the shortcut's cycle")
        self.assertEqual(row.cycle.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        checked = row.cycle.isChecked()
        row.cycle.setFocus()
        QTest.keyClick(row.cycle, Qt.Key.Key_Space)
        self.assertNotEqual(row.cycle.isChecked(), checked)

    def test_shelved_machine_keeps_its_row_and_put_back_action(self):
        window, peer = self.window, self.peers[0]["id"]
        row = window.crossing_ledger.rows[peer]
        window._canvas_left_out(peer, True)
        self.assertIs(window.crossing_ledger.rows[peer], row)
        self.assertEqual(row.leave.text(), "Put back")
        self.assertIn("Left out", row.status.text())
        row.leave.click()
        self.assertIs(window.crossing_ledger.rows[peer], row)
        self.assertEqual(row.leave.text(), "Leave out")

    def test_destination_note_matches_the_mac(self):
        for mode, hold, expected in (
            ("last", False, "With Hold, input goes to the last machine."),
            ("next", True, "With Hold, input goes to the first ready machine in order."),
            ("next", False, "The order follows the tiles from top to bottom, then left to right. This PC is always in the cycle."),
        ):
            self.assertEqual(pages_win.shortcut_destination_note(mode, hold), expected)
