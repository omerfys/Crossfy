"""Focused action and state coverage for nearby pairing's Windows Qt surface."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.append(str(Path(__file__).resolve().parents[2]))
sys.path.append(str(Path(__file__).resolve().parents[1]))

from core import feature_flags

try:
    from PySide6.QtCore import QCoreApplication, QEvent, QSize
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtWidgets import QApplication, QBoxLayout
    import kvm_bridge_win
    import machines_win
    import theme
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "needs PySide6")
class NearbyPairingUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        theme.init_fonts()

    @mock.patch.object(feature_flags, "PAIRING_QR_VISIBLE", True)
    def test_machine_actions_keep_typed_pairing_and_add_phone_and_nearby(self):
        calls = []
        callbacks = [lambda *_args, action=action: calls.append(action)
                     for action in ("send", "allow", "in_use", "left_out", "remove", "typed")]
        module = machines_win.MachinesModule(
            *callbacks,
            on_pair_phone=lambda: calls.append("phone"),
            on_pair_nearby=lambda: calls.append("nearby"),
        )

        self.assertEqual(module.pair_button.text(), "Pair a machine")
        self.assertEqual(module.pair_phone_button.text(), "Pair a phone")
        self.assertEqual(module.pair_nearby_button.text(), "Pair nearby")
        self.assertFalse(module.pair_phone_button.isHidden())
        self.assertEqual(module.pair_actions.itemAt(0).widget(), module.pair_nearby_button)
        self.assertEqual(module.pair_actions.itemAt(1).widget(), module.pair_phone_button)
        self.assertEqual(module.pair_actions.itemAt(2).widget(), module.pair_button)
        self.assertEqual(module.pair_nearby_button.property("vernier"), "primary")
        self.assertNotEqual(module.pair_phone_button.property("vernier"), "primary")
        self.assertNotEqual(module.pair_button.property("vernier"), "primary")
        module.resize(350, 300)
        module.resizeEvent(QResizeEvent(QSize(350, 300), QSize(600, 300)))
        self.assertEqual(module.pair_actions.direction(), QBoxLayout.Direction.TopToBottom)
        module.resize(600, 300)
        module.resizeEvent(QResizeEvent(QSize(600, 300), QSize(350, 300)))
        self.assertEqual(module.pair_actions.direction(), QBoxLayout.Direction.LeftToRight)
        module.pair_button.click()
        module.pair_phone_button.click()
        module.pair_nearby_button.click()

        self.assertEqual(calls, ["typed", "phone", "nearby"])

    def test_phone_pairing_stays_hidden_while_nearby_pairing_remains_available(self):
        calls = []
        callbacks = [lambda *_args: None for _ in range(6)]
        module = machines_win.MachinesModule(
            *callbacks,
            on_pair_phone=lambda: calls.append("phone"),
            on_pair_nearby=lambda: calls.append("nearby"),
        )

        self.assertTrue(module.pair_phone_button.isHidden())
        self.assertFalse(module.pair_nearby_button.isHidden())
        module.pair_nearby_button.click()
        self.assertEqual(calls, ["nearby"])

    def test_nearby_status_copy_candidates_and_manual_confirmation(self):
        calls = []
        sheet = machines_win.PairingSheet(
            lambda: None, lambda: None, lambda *_: None, lambda *_: None,
            lambda peer: calls.append(("choose", peer)),
            lambda sas, attempt: calls.append(("confirm", sas, attempt)),
            lambda: calls.append(("cancel",)),
        )
        self.addCleanup(sheet.deleteLater)
        sheet.set_nearby({"state": "searching", "seconds_left": 60, "peers": [], "peer": None,
                          "sas": None, "attempt": "attempt-1"})
        self.assertEqual(sheet.nearby_note.text(), "Press Pair nearby on the other machine within 60 seconds.")
        self.assertEqual(sheet.nearby_count.text(), "Expires in 60 s")
        self.assertTrue(sheet.nearby_confirm.isHidden())

        peer = {"id": "machine-id", "nearby": "window-a", "name": "Studio Mac", "platform": "macos",
                "address": "192.0.2.50"}
        shown = lambda text: f"Private {text.replace('192.0.2.50', '•••')}" if text else ""
        sheet.set_nearby({"state": "choosing", "seconds_left": 50, "peers": [peer], "peer": None,
                          "sas": None, "attempt": "attempt-1"}, shown)
        self.assertEqual(sheet.nearby_note.text(), "Choose a machine to pair nearby.")
        self.assertEqual(len(sheet.nearby_group.buttons()), 1)
        self.assertIn("Private Studio Mac", sheet.nearby_group.buttons()[0].text())
        self.assertIn("•••", sheet.nearby_group.buttons()[0].text())
        self.assertNotIn("192.0.2.50", sheet.nearby_group.buttons()[0].text())
        self.assertEqual(sheet.nearby_peer.text(), "")
        sheet.nearby_group.buttons()[0].click()
        self.assertEqual(calls, [("choose", peer)])
        renewed = dict(peer, nearby="window-b")
        sheet.set_nearby({"state": "choosing", "seconds_left": 48, "peers": [renewed], "peer": None,
                          "sas": None, "attempt": "attempt-2"}, shown)
        self.assertEqual(sheet.nearby_group.buttons()[0].property("nearby_peer"), renewed)
        sheet.nearby_group.buttons()[0].click()
        self.assertEqual(calls[-1], ("choose", renewed))

        sheet.set_nearby({"state": "confirm", "seconds_left": 35, "peers": [], "peer": peer,
                          "sas": "012345", "attempt": "attempt-1"}, shown)
        self.assertEqual(sheet.nearby_note.text(), "Compare all six digits on both machines, then confirm on each.")
        self.assertEqual(sheet.nearby_digits.text(), "012 345")
        self.assertEqual(sheet.nearby_peer.text(), "Private Selected: Studio Mac · Mac")
        self.assertTrue(sheet.nearby_confirm.isEnabled())
        self.assertFalse(sheet.nearby_confirm.isDefault())
        self.assertFalse(sheet.nearby_confirm.autoDefault())
        sheet.nearby_confirm.click()
        self.assertEqual(calls[-1], ("confirm", "012345", "attempt-1"))

        sheet.set_nearby({"state": "waiting", "seconds_left": 17, "peers": [], "peer": peer,
                          "sas": "012345", "attempt": "attempt-1"}, shown)
        self.assertEqual(sheet.nearby_note.text(), "Waiting for confirmation on the other machine.")
        self.assertEqual(sheet.nearby_digits.text(), "012 345")
        self.assertFalse(sheet.nearby_digits.isHidden())
        self.assertTrue(sheet.nearby_confirm.isHidden())
        self.assertEqual(sheet.nearby_peer.text(), "Private Selected: Studio Mac · Mac")
        self.assertEqual(sheet.nearby_count.text(), "Expires in 17 s")

        sheet.set_nearby({"state": "exchanging", "seconds_left": 42, "peers": [], "peer": peer,
                          "sas": None, "attempt": "attempt-1"}, shown)
        self.assertEqual(sheet.nearby_note.text(), "Connecting to the selected machine…")
        sheet.set_nearby({"state": "paired", "seconds_left": 0, "peers": [], "peer": peer,
                          "sas": None, "attempt": "attempt-1"}, shown)
        self.assertEqual(sheet.nearby_note.text(), "Nearby pairing complete.")

    def test_waiting_terminal_copy_and_cancel_action(self):
        sheet = machines_win.PairingSheet(
            lambda: None, lambda: None, lambda *_: None, lambda *_: None,
            on_cancel_nearby=lambda: setattr(self, "cancelled", True),
        )
        self.addCleanup(sheet.deleteLater)
        cases = {
            "waiting": "Waiting for confirmation on the other machine.",
            "expired": "Nearby pairing expired. Press Pair nearby to try again.",
            "refused": "Nearby pairing refused. Use a new window to try again.",
            "not_saved": "The new peer could not be saved.",
        }
        for state, text in cases.items():
            with self.subTest(state=state):
                sheet.set_nearby({"state": state, "seconds_left": 0, "peers": [], "peer": None,
                                  "sas": None, "attempt": "attempt-1"})
                self.assertEqual(sheet.nearby_note.text(), text)
        sheet.nearby_cancel.click()
        self.assertTrue(self.cancelled)

    def test_nearby_candidates_removal_and_sheet_destruction_clears_deferred_deletes(self):
        sheet = machines_win.PairingSheet(
            lambda: None, lambda: None, lambda *_: None, lambda *_: None,
            lambda *_: None, lambda *_: None, lambda: None,
        )
        peer = {"id": "peer-1", "nearby": "win-1", "name": "Desk Rig", "platform": "windows",
                "address": "192.0.2.20"}
        sheet.set_nearby({"state": "choosing", "seconds_left": 50, "peers": [peer], "peer": None,
                          "sas": None, "attempt": "attempt-1"})
        self.assertEqual(len(sheet.nearby_group.buttons()), 1)
        # Transitioning away from choosing removes candidate buttons via deleteLater.
        sheet.set_nearby({"state": "confirm", "seconds_left": 30, "peers": [], "peer": peer,
                          "sas": "123456", "attempt": "attempt-1"})
        self.assertEqual(len(sheet.nearby_group.buttons()), 0)
        # Destroy the sheet while candidate buttons have pending deferred deletes.
        # Buttons must have been unparented so sheet's destruction doesn't double-free them
        # when deferred delete events are delivered.
        sheet.setParent(None)
        sheet.deleteLater()
        del sheet
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_new_window_repair_and_window_close_cancel_nearby(self):
        calls = []
        service = SimpleNamespace(cancel_nearby=lambda: calls.append("cancel"), machines=lambda: [])
        address = SimpleNamespace(setText=lambda value: calls.append(("address", value)))
        sheet = SimpleNamespace(address=address, setVisible=lambda value: calls.append(("visible", value)))
        machines = SimpleNamespace(set_pairing_open=lambda value: calls.append(("open", value)))
        app = SimpleNamespace(
            _peer_entries=[{"token": "known", "host": "192.0.2.22"}],
            pairing=service,
            _pairing_open=False,
            _select_page=lambda page: calls.append(("page", page)),
            _hide_addresses=lambda: False,
            sheet=sheet,
            machines=machines,
            _refresh_pairing=lambda: calls.append("refresh"),
            _cancel_nearby=lambda: (service.cancel_nearby(), calls.append("refresh")),
            _closing=False,
            tray=SimpleNamespace(isVisible=lambda: False),
            quit=lambda: (service.cancel_nearby(), calls.append("cancel"), calls.append("quit")),
        )
        kvm_bridge_win.WindowsApplication._re_pair(app, "known")
        self.assertIn("cancel", calls)
        self.assertIn(("address", "192.0.2.22"), calls)

        calls.clear()
        event = SimpleNamespace(accept=lambda: calls.append("accept"), ignore=lambda: calls.append("ignore"))
        kvm_bridge_win.WindowsApplication.closeEvent(app, event)
        self.assertIn("cancel", calls)
        self.assertIn("quit", calls)
        self.assertIn("accept", calls)


if __name__ == "__main__":
    unittest.main()
