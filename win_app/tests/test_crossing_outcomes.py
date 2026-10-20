"""The PC carries shared crossing outcomes through save, engines and wire messages."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_config
import kvm_bridge_win as kvm
from core import crossing_state, protocol, ways
from core.tests import responder_harness as h


class CrossingOutcomes(unittest.TestCase):
    def test_pairing_after_empty_start_adds_a_tile_and_saves_the_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            window = mock.Mock()
            window.config_path = Path(folder) / "settings.json"
            saved = app_config.load_settings(window.config_path)
            window._own_displays.return_value = {}
            window._layout_capable.return_value = {saved["machine_id"]}
            window._carry_crossing.side_effect = lambda out, **_: app_config.write_settings(window.config_path, out["settings"])
            entry = h.entry(h.B, "Studio", side="right")
            kvm.WindowsApplication._store_peer(window, entry, None)
            result = app_config.load_settings(window.config_path)
            self.assertEqual(result["peers"][0]["id"], entry["id"])
            self.assertIn(entry["id"], result["layout"])

    def test_picture_peer_arrangement_keeps_position_and_side(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = app_config.migrate(None, machine_id=protocol.id_text(h.HERE))
            peer = protocol.id_text(h.B)
            settings["peers"] = [h.entry(h.B, "Studio", side="right")]
            settings = crossing_state.paired(settings, platform="pc", own_displays={}, now=100)["settings"]
            app_config.write_settings(path, settings)
            before = app_config.load_settings(path)
            changed, notices = app_config.apply_arrangement(path, peer, "top", 200, peer,
                                                            False, capable={peer})
            after = app_config.load_settings(path)
            self.assertTrue(changed)
            self.assertEqual(notices, [])
            self.assertEqual(after["layout"], before["layout"])
            self.assertEqual(after["peers"][0]["side"], before["peers"][0]["side"])
            self.assertFalse(after["peers"][0]["way_back"])

    def test_outcome_rebuilds_and_rearms_before_messages(self):
        calls = []
        window = mock.Mock()
        window.config_path = Path("synthetic")
        window._config = app_config.default_config()
        window.sender.update_config.side_effect = lambda *_: calls.append("update")
        window.sender.refresh.side_effect = lambda: calls.append("refresh")
        window.server.peers_changed.side_effect = lambda: calls.append("peers")
        window.server.rearm.side_effect = lambda: calls.append("rearm")
        window._tell.side_effect = lambda p: calls.append(("tell", p))
        window._send_same.side_effect = lambda **kw: calls.append(("picture", kw))
        saved = app_config.migrate(None)
        outcome = crossing_state.migrate(saved, "pc")
        outcome.update(changed=True, tell=["peer"], send_picture=True, forward_picture=True)
        with mock.patch.object(app_config, "write_settings", side_effect=lambda *_: calls.append("save")):
            kvm.WindowsApplication._carry_crossing(window, outcome, source=protocol.id_text(h.B), arrived={"layout": 1})
        self.assertEqual(calls[:6], ["save", "update", "refresh", "peers", "rearm", ("tell", "peer")])
        self.assertEqual(calls[6:], [("picture", {"layout_only": True}),
                                   ("picture", {"source": h.B, "data": {"layout": 1}, "layout_only": True})])

    def test_load_migrates_legacy_intent_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = app_config.migrate(None, machine_id=protocol.id_text(h.HERE))
            peer = protocol.id_text(h.B)
            settings["peers"] = [h.entry(h.B, "Studio", side="right")]
            settings["zones"] = [{"peer": peer, "kind": "edge", "off": True, "page_off": True}]
            app_config.write_settings(path, settings)
            saved = app_config.load_settings(path)
            self.assertFalse(saved["peers"][0]["ways"]["edge"])
            saved["zones"] = [{"peer": peer, "kind": "edge"}]
            app_config.write_settings(path, saved)
            self.assertFalse(app_config.load_settings(path)["peers"][0]["ways"]["edge"])


if __name__ == "__main__":
    unittest.main()
