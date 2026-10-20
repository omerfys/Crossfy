import os
import sys
import unittest
import copy
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "win_app"))

from PySide6.QtWidgets import QApplication

import peers_view
import pages_win
import kvm_bridge_win
from machines_win import PairingSheet, PeerRow
from core import pairing
from core import protocol
from core.tests import responder_harness as harness
import app_config


APP = QApplication.instance() or QApplication([])


class DormantRowTests(unittest.TestCase):
    def test_dormant_machines_mark_overview_and_crossing_for_attention(self):
        self.assertEqual(pages_win.dots(False, None, dormant=True),
                         {"overview": "amber", "crossing": "amber"})

    def test_row_shows_needs_repair_and_reason(self):
        state = peers_view.describe({"dormant": True, "dormant_reason": "forgotten", "send": True}, "Desk",
                                    up=False, driving=False, input_there=False, kind="unreachable", status="offline",
                                    waking=False)
        self.assertEqual((state.word, state.detail), ("Needs re-pair", "The other machine no longer has this pairing."))

    def test_peer_row_exposes_a_repair_action(self):
        called = []
        row = PeerRow("token", lambda *_: None, lambda *_: None, lambda *_: None, lambda *_: None,
                      lambda *_: None, on_repair=called.append)
        self.assertTrue(hasattr(row, "repair_button"))
        self.assertIn("Re-pair", row.repair_button.text())
        state = peers_view.describe({"dormant": True, "dormant_reason": "forgotten", "send": True}, "Desk",
                                    up=False, driving=False, input_there=False, kind="none", status="", waking=False)
        row.refresh({"id": "id", "name": "Desk", "port": 24820, "dormant": True,
                     "dormant_reason": "forgotten"}, "Desk", state, "Windows", cycle_mode="last")
        self.assertFalse(row.repair_button.isHidden())
        row.repair_button.click()
        self.assertEqual(called, ["token"])

    def test_re_pair_opens_the_existing_sheet_for_the_saved_address(self):
        app = SimpleNamespace(
            _peer_entries=[{"token": "token", "host": "192.0.2.10"}],
            _hide_addresses=lambda: False,
            _pairing_open=False,
            sheet=SimpleNamespace(address=mock.Mock(), setVisible=mock.Mock()),
            machines=SimpleNamespace(set_pairing_open=mock.Mock()),
            _refresh_pairing=mock.Mock(),
            _cancel_nearby=mock.Mock(),
            _select_page=mock.Mock(),
        )

        kvm_bridge_win.WindowsApplication._re_pair(app, "token")
        app._cancel_nearby.assert_called_once_with()

        self.assertTrue(app._pairing_open)
        app.sheet.address.setText.assert_called_once_with("192.0.2.10")
        app.sheet.setVisible.assert_called_once_with(True)
        app.machines.set_pairing_open.assert_called_once_with(True)
        app._refresh_pairing.assert_called_once_with()

    def test_programmatic_repair_selection_checks_the_real_discovery_button(self):
        selected = []
        sheet = PairingSheet(lambda: None, lambda: None, lambda *args: None, selected.append)
        sheet.set_machines([
            {"name": "Desk", "address": "192.0.2.10", "platform": "windows",
             "pairing": pairing.PAIRING_V3, "pair_id": "pair"},
            {"name": "Other", "address": "192.0.2.11", "platform": "windows",
             "pairing": pairing.PAIRING_V3, "pair_id": "other"},
        ])
        sheet.code.setText("123456")

        sheet._pick("192.0.2.10")

        self.assertEqual(sheet.chosen_machine()["address"], "192.0.2.10")
        self.assertTrue(sheet.pair_button.isEnabled())
        self.assertEqual(selected[-1]["address"], "192.0.2.10")

    def test_re_pair_with_hidden_addresses_selects_the_saved_discovery_machine(self):
        machines = [
            {"name": "Desk", "address": "192.0.2.10", "platform": "windows",
             "pairing": pairing.PAIRING_V3, "pair_id": "pair"},
            {"name": "Other", "address": "192.0.2.11", "platform": "windows",
             "pairing": pairing.PAIRING_V3, "pair_id": "other"},
        ]
        selected = []
        sheet = PairingSheet(lambda: None, lambda: None, lambda *args: None, selected.append)
        sheet.set_machines(machines)
        sheet.code.setText("123456")
        sheet._pick("192.0.2.11")
        app = SimpleNamespace(
            _peer_entries=[{"token": "token", "host": "192.0.2.10"}],
            _hide_addresses=lambda: True,
            _pairing_open=False,
            _shown=lambda text: text,
            pairing=SimpleNamespace(machines=lambda: machines),
            sheet=sheet,
            machines=SimpleNamespace(set_pairing_open=mock.Mock()),
            _refresh_pairing=lambda: sheet.set_machines(machines),
            _cancel_nearby=mock.Mock(),
            _select_page=mock.Mock(),
        )

        kvm_bridge_win.WindowsApplication._re_pair(app, "token")
        app._cancel_nearby.assert_called_once_with()

        self.assertEqual(sheet.chosen_machine()["address"], "192.0.2.10")
        self.assertTrue(sheet.pair_button.isEnabled())
        self.assertEqual(selected[-1]["address"], "192.0.2.10")


class DormantCrossingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.json"
        self.peer = protocol.id_text(harness.B)
        self.other = protocol.id_text(harness.C)
        self.own = protocol.id_text(harness.HERE)
        settings = app_config.migrate(None, machine_id=self.own)
        settings["peers"] = [harness.entry(harness.B, "Desk", side="right", dormant=True,
                                           dormant_reason="forgotten"),
                             harness.entry(harness.C, "Other", side="left")]
        settings["zones"] = [{"peer": self.peer, "kind": "edge"}, {"peer": self.other, "kind": "edge"}]
        settings["layout"] = {self.own: {"x": 0, "y": 0, "w": 160, "h": 100},
                              self.peer: {"x": 160, "y": 0, "w": 160, "h": 100},
                              self.other: {"x": -160, "y": 0, "w": 160, "h": 100}}
        app_config.write_settings(self.path, settings)
        with mock.patch.object(kvm_bridge_win.WindowsApplication, "_build_tray", lambda window: setattr(window, "tray", mock.Mock())), \
                mock.patch.object(kvm_bridge_win.WindowsApplication, "_refresh_window"):
            self.window = kvm_bridge_win.WindowsApplication(self.path)
        self.window.full_screen_timer.stop()
        self.addCleanup(self.window.server.stop)
        self.addCleanup(self.window.deleteLater)

    def test_persisted_dormant_peer_is_off_the_map_but_kept_in_the_ledger(self):
        window = self.window
        self.assertIn(self.peer, window.atlas_canvas.shelf_ids)
        self.assertNotIn(self.peer, window.atlas_canvas.tiles)
        self.assertIn(self.peer, window.crossing_ledger.rows)
        window._choose_machine(self.peer)
        self.assertTrue(window.crossing_ledger.rows[self.peer].selected)
        self.assertFalse(hasattr(window, "left_out_shelf"))
        self.assertFalse(hasattr(window, "dormant_note"))

    def test_dormant_tile_cannot_be_moved_with_the_canvas_keyboard(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        canvas = self.window.atlas_canvas
        canvas.selected = self.peer
        before = copy.deepcopy(canvas.tiles)
        self.assertIn(self.peer, canvas.shelf_ids)
        self.assertNotIn(self.peer, canvas.tiles)
        QTest.keyClick(canvas, Qt.Key.Key_Down)
        self.assertEqual(canvas.tiles, before)
        self.assertIn(self.peer, canvas.shelf_ids)

    def test_dormant_position_does_not_block_an_active_edge_snap(self):
        settings = app_config.load_settings(self.path)
        tiles = copy.deepcopy(settings["layout"])
        tiles[self.other]["x"] = 166
        tiles[self.other]["y"] = 17
        with mock.patch.object(self.window, "_tell"), mock.patch.object(self.window, "_send_same"), \
                mock.patch.object(self.window.sender, "refresh"):
            self.assertTrue(self.window._layout_dropped(tiles, self.other))
        saved = app_config.load_settings(self.path)
        self.assertEqual(saved["layout"][self.other]["x"], 160)
        self.assertEqual(saved["layout"][self.peer], settings["layout"][self.peer])
        self.assertEqual([zone for zone in saved["zones"] if zone["peer"] == self.peer],
                         [zone for zone in settings["zones"] if zone["peer"] == self.peer])

    def test_incoming_layout_moves_shelved_positions_but_keeps_local_intent(self):
        from core import settings_sync

        settings = app_config.load_settings(self.path)
        settings["peers"][1]["in_use"] = False
        settings["peers"].append(harness.entry(harness.D, "Sender", side="right"))
        settings["layout"][protocol.id_text(harness.D)] = {"x": 0, "y": 120, "w": 160, "h": 100}
        settings["zones"].append({"peer": protocol.id_text(harness.D), "kind": "edge"})
        app_config.write_settings(self.path, settings)
        settings = app_config.load_settings(self.path)
        window = self.window
        window._peer_entries = settings["peers"]
        source = protocol.id_text(harness.D)
        window._peer_caps = lambda: {harness.D: {"settings", "layout"}}
        window._design_peer_caps = lambda: {source: {"settings", "layout"}}
        original = copy.deepcopy(settings)
        incoming = copy.deepcopy(settings["layout"])
        incoming[self.peer]["x"] = 320
        incoming[self.other]["x"] = -320
        message = settings_sync.message_data(False, 0, by=source,
                                             layout_state={"tiles": incoming, "set_at": 1, "by": source})

        with mock.patch.object(window, "_send_same"), mock.patch.object(window, "_read_crossing"), \
                mock.patch.object(window, "_reflect_config"), mock.patch.object(window, "_tell"), \
                mock.patch.object(window.sender, "update_config"), mock.patch.object(window.sender, "refresh"), \
                mock.patch.object(window.server, "peers_changed"):
            window._on_settings(source, message)

        saved = app_config.load_settings(self.path)
        self.assertEqual(saved["layout"][self.peer], incoming[self.peer])
        self.assertEqual(saved["layout"][self.other], incoming[self.other])
        for peer in (self.peer, self.other):
            self.assertEqual(next(p["ways"] for p in saved["peers"] if p["id"] == peer),
                             next(p["ways"] for p in original["peers"] if p["id"] == peer))
            self.assertEqual([zone for zone in saved["zones"] if zone["peer"] == peer],
                             [zone for zone in original["zones"] if zone["peer"] == peer])

    def test_repair_keeps_label_layout_zones_and_left_out_after_reloading(self):
        settings = app_config.load_settings(self.path)
        old = copy.deepcopy(settings["peers"][0])
        settings["peers"][0]["label"] = "Office"
        settings["peers"][0].update(left_out=True, left_out_ways=["edge"])
        app_config.write_settings(self.path, settings)
        repaired = pairing.peer_entry(harness.B, "Desk", "macos", 24820, harness.token(5), "192.0.2.20", 100)
        self.window._store_peer(repaired, old)
        saved = app_config.load_settings(self.path)
        self.assertEqual(saved["peers"][0]["label"], "Office")
        self.assertTrue(saved["peers"][0]["left_out"])
        self.assertNotIn("left_out_ways", saved["peers"][0])
        self.assertEqual(saved["peers"][0]["ways"], settings["peers"][0]["ways"])
        from display_map_fixture import display_fields
        self.assertEqual(saved["zones"], [dict(zone, **display_fields(self.window))
                                          for zone in settings["zones"]])
        expected_layout = copy.deepcopy(settings["layout"])
        displays = self.window._own_displays()
        if displays:
            expected_layout[self.own]["displays"] = {
                key: {"x": rect.x, "y": rect.y, "w": rect.width, "h": rect.height}
                for key, rect in displays.items()
            }
        self.assertEqual(saved["layout"], expected_layout)
        self.assertNotIn("dormant", saved["peers"][0])


if __name__ == "__main__":
    unittest.main()
