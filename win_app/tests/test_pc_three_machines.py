"""Three machines on the Qt app: shortcut targets, tray items, Atlas tile selection and drops,
local ways, and Pause counting every machine's zones (WIRE.md sections 5 and 8)."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.links_rig import B, C, HERE, Rig, edge_zone

import app_config
import pages_win
import sender as sender_module
from core import crossing_state, protocol
from core import ways
from core.tests import responder_harness as harness

try:
    from PySide6.QtWidgets import QApplication, QLabel

    import diagram
    import kvm_bridge_win
    import theme
except ImportError:  # PySide6 is only in the Windows venv
    kvm_bridge_win = None

D = harness.D
BT, CT, DT = protocol.id_text(B), protocol.id_text(C), protocol.id_text(D)
HIGH_ID = bytes([200]) * 16
HIGH = protocol.id_text(HIGH_ID)


def target_of(message):
    return protocol.read_id(message["data"]["target"])


class ShortcutMachineTests(unittest.TestCase):
    """The shortcut, the Send button and the tray send input where core.ways.shortcut_peer says."""

    def rig(self, up, **entries):
        shortcut_goes_to = entries.pop("shortcut_goes_to", "last")
        peers = [harness.entry(B, "Bee", side="left", **entries.get("b", {})),
                 harness.entry(C, "Sea", side="right", **entries.get("c", {}))]
        return Rig(entries=peers, zones=[edge_zone(B), edge_zone(C)], up=up,
                   shortcut_goes_to=shortcut_goes_to)

    def test_with_the_first_machine_down_the_shortcut_takes_one_that_is_up(self):
        rig = self.rig(up=(C,))
        self.assertTrue(rig.sender.set_redirecting(True))
        self.assertEqual(rig.sender.owner, C)
        self.assertEqual(target_of(rig.sent(C, "focus")[0]), C)

    def test_hold_shortcut_announces_an_unready_last_machine(self):
        rig = self.rig(up=(C,))
        rig.sender._last_on = BT
        rig.sender.hold_shortcut(True)
        self.assertEqual(rig.sender.owner, C)
        self.assertEqual(rig.alerts, ["Skipped Bee: not connected."])

    def test_the_shortcut_goes_back_to_the_machine_input_was_last_on(self):
        rig = self.rig(up=(B, C))
        rig.sender.go(C)
        rig.accept_take(C)
        rig.sender.set_redirecting(False)
        self.assertEqual(rig.sender.shortcut_target(), C)
        self.assertTrue(rig.sender.set_redirecting(True))
        self.assertEqual(rig.sender.owner, C)

    def test_next_shortcut_cycles_through_drawing_order_and_home(self):
        rig = self.rig(up=(B, C), shortcut_goes_to="next")
        rig.sender.toggle_shortcut()
        self.assertEqual(rig.sender.owner, C)
        rig.sender.toggle_shortcut()
        self.assertEqual(rig.sender.owner, B)
        rig.sender.toggle_shortcut()
        self.assertIsNone(rig.sender.owner)

    def test_shortcut_at_home_asks_to_push_to_its_target_then_moves_when_captured(self):
        rig = self.rig(up=(B, C))
        rig.sender.input_held = lambda: False
        requested = []

        def push_out(peer, on_captured, on_failed):
            requested.append((peer, on_captured, on_failed))
            return True

        rig.sender.push_out = push_out
        rig.sender.toggle_shortcut()

        self.assertEqual(len(requested), 1)
        peer, captured, _failed = requested[0]
        self.assertEqual(peer, rig.sender.shortcut_target())
        self.assertEqual(rig.sender.owner, None)
        self.assertEqual(rig.alerts, [])
        rig.sender.input_held = lambda: True
        captured()
        self.assertEqual(rig.sender.owner, peer)

    def test_failed_push_out_alerts_with_the_target_name(self):
        rig = self.rig(up=(B, C))
        rig.sender.input_held = lambda: False
        requests = []
        rig.sender.push_out = lambda peer, on_captured, on_failed: requests.append((peer, on_failed)) or True
        rig.sender.toggle_shortcut()

        requests[0][1]()

        self.assertEqual(rig.alerts, ["Cannot switch — the desktop did not let Beamer send input to Bee"])

    def test_no_push_out_keeps_the_existing_wayland_alert(self):
        rig = self.rig(up=(B, C))
        rig.sender.input_held = lambda: False

        rig.sender.toggle_shortcut()

        self.assertEqual(rig.alerts, ["Cannot switch — on this desktop input goes to another machine only by pushing the pointer through an edge"])

    def test_push_out_refusal_falls_back_to_the_existing_wayland_alert(self):
        rig = self.rig(up=(B, C))
        rig.sender.input_held = lambda: False
        rig.sender.push_out = lambda peer, on_captured, on_failed: False

        rig.sender.toggle_shortcut()

        self.assertEqual(rig.alerts, ["Cannot switch — on this desktop input goes to another machine only by pushing the pointer through an edge"])

    def test_models_toward_returns_only_that_peers_models_and_none_while_edges_are_held(self):
        rig = self.rig(up=(B, C))

        models = rig.sender.models_toward(B)

        self.assertTrue(models)
        self.assertEqual(models, [model for peer, model in rig.sender._models if peer == B])
        rig.sender.crossing_paused = True
        self.assertEqual(rig.sender.models_toward(B), [])

    def test_next_shortcut_passes_over_a_machine_that_just_refused_and_comes_home(self):
        # The owner ignores a move to a machine it holds back, so choosing it left input where it was.
        rig = self.rig(up=(B, C), shortcut_goes_to="next")
        rig.sender.toggle_shortcut()
        self.assertEqual(rig.sender.owner, C)
        rig.sender._owner._hold_back(B, "refused")
        rig.sender.toggle_shortcut()
        self.assertIsNone(rig.sender.owner)

    def test_a_machine_that_does_not_accept_input_is_passed_over(self):
        rig = self.rig(up=(C,))
        rig.bring_up(B, accepts=False)
        self.assertEqual(rig.sender.shortcut_target(), C)

    def test_a_machine_this_pc_does_not_send_to_is_never_picked(self):
        rig = self.rig(up=(B, C), b={"send": False})
        self.assertEqual(rig.sender.shortcut_target(), C)

    def test_with_every_machine_down_the_first_is_woken(self):
        rig = self.rig(up=(), b={"hw": "aa:bb:cc:dd:ee:ff"})
        woken = []
        rig.sender._wake_sender = lambda address, host: woken.append(address)
        self.addCleanup(rig.sender._stop_event.set)
        self.assertFalse(rig.sender.set_redirecting(True))
        self.assertTrue(rig.sender.is_waking(B))
        self.assertFalse(rig.sender.is_waking(C))

    def test_with_every_machine_down_and_none_to_wake_the_first_is_named(self):
        rig = self.rig(up=())
        rig.sender.on_status(rig.links.key_of(rig.settings.data["peers"][0]), False, "Bee is unreachable")
        self.assertFalse(rig.sender.set_redirecting(True))
        self.assertEqual(rig.alerts, ["Cannot switch — Bee is unreachable"])

    def test_the_status_is_the_shortcut_machines(self):
        rig = self.rig(up=(C,))
        rig.sender.on_status(rig.links.key_of(rig.settings.data["peers"][0]), False, "Bee is unreachable")
        rig.sender.on_status(rig.links.key_of(rig.settings.data["peers"][1]), True, "Connected to Sea")
        self.assertTrue(rig.sender.connected)
        self.assertEqual(rig.sender.status, "Connected to Sea")

    def test_the_status_does_not_name_a_machine_not_in_use(self):
        rig = self.rig(up=(), b={"in_use": False})
        rig.sender.on_status(rig.links.key_of(rig.settings.data["peers"][0]), False, "Bee is unreachable")
        self.assertEqual(rig.sender.status, sender_module.NOT_CONNECTED_STATUS)


class SetWaysTests(unittest.TestCase):
    """Each machine's side and zones are written one machine at a time, under the settings lock, and
    never by a flat save."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"
        settings = app_config.migrate(None, machine_id=protocol.id_text(harness.HERE))
        settings["peers"] = [
            harness.entry(B, "Bee", side="left", side_set_at=100, side_by=HIGH),
            harness.entry(C, "Sea", platform="windows"),
        ]
        for entry in settings["peers"]:
            entry["caps"] = []
        settings["zones"] = [{"peer": BT, "kind": "edge"}]
        app_config.write_settings(self.path, settings)

    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def peer(self, ident):
        return next(item for item in self.saved()["peers"] if item["id"] == ident)

    def zones(self, ident):
        return {zone["kind"]: zone for zone in self.saved()["zones"] if zone["peer"] == ident}

    def test_reading_the_settings_gives_a_machine_with_no_zone_its_edge_and_writes_it(self):
        # The rig's beta.3 file of 01-10-2026: the laptop paired second, its side set, no zone at all.
        settings = self.saved()
        settings["peers"][1]["side"] = "right"
        app_config.write_settings(self.path, settings)
        loaded = app_config.load_settings(self.path)
        self.assertIn({"peer": CT, "kind": "edge"}, loaded["zones"])
        self.assertIn({"peer": CT, "kind": "edge"}, self.saved()["zones"])

    def test_old_peer_on_a_taken_side_keeps_intent_without_an_overlapping_zone(self):
        settings = self.saved()
        settings["peers"][1]["side"] = "left"
        app_config.write_settings(self.path, settings)
        loaded = app_config.load_settings(self.path)
        self.assertFalse(any(z["peer"] == CT for z in loaded["zones"]))
        self.assertTrue(loaded["peers"][1]["ways"]["edge"])
        self.assertIn("Sea has no way in", ways.blocked_sentence(loaded, CT, "this PC"))

    def test_way_edit_writes_one_peers_intent_and_keeps_both_sides(self):
        settings = self.saved()
        settings["peers"][1]["side"] = "right"
        app_config.write_settings(self.path, settings)
        self.assertFalse(app_config.set_ways(self.path, CT, side="top", methods=["part", "corner"], parts=["end"], corner="bottom_right"))
        self.assertEqual(self.peer(CT)["side"], "right")
        self.assertEqual(self.zones(CT)["part"]["parts"], ["end"])
        self.assertNotIn("edge", self.zones(CT))
        self.assertEqual(self.zones(CT)["corner"]["edge"], "right")
        self.assertEqual(self.zones(BT), {"edge": {"peer": BT, "kind": "edge"}})

    def test_an_unchanged_side_is_not_a_move(self):
        self.assertFalse(app_config.set_ways(self.path, BT, side="left", methods=["edge"], parts=["middle"], corner="top_left"))
        self.assertEqual(self.peer(BT)["side_set_at"], 100)

    def test_no_side_given_keeps_the_side_held_whatever_the_window_last_read(self):
        settings = self.saved()
        settings["peers"][0]["side"] = "top"
        app_config.write_settings(self.path, settings)
        self.assertFalse(app_config.set_ways(self.path, BT, methods=["edge", "corner"], parts=["middle"], corner="top_left"))
        self.assertEqual(self.peer(BT)["side"], "top")
        self.assertEqual(self.zones(BT)["corner"]["edge"], "top")

    def test_shared_side_way_edit_saves_intent_without_a_clash_refusal(self):
        settings = self.saved()
        settings["peers"][1]["side"] = "left"
        app_config.write_settings(self.path, settings)
        app_config.set_ways(self.path, CT, methods=["edge"], parts=["middle"], corner="top_left")
        self.assertTrue(self.peer(CT)["ways"]["edge"])
        self.assertFalse(any(z["peer"] == CT for z in self.saved()["zones"]))
        self.assertEqual(self.zones(BT), {"edge": {"peer": BT, "kind": "edge"}})

    def test_a_machine_that_is_not_paired_is_an_error(self):
        with self.assertRaises(app_config.ConfigError):
            app_config.set_ways(self.path, DT, side="left", methods=[], parts=["middle"], corner="top_left")

    def test_a_flat_save_never_writes_a_side_or_a_zone(self):
        stale = app_config.load_config(self.path)
        settings = self.saved()
        settings["peers"][0].update(side="top", side_set_at=300, side_by=HIGH)
        app_config.write_settings(self.path, settings)
        app_config.save_config(self.path, app_config.replace(
            stale, crossing_methods=["part"], crossing_edge_parts=["start"], mac_return_edge="bottom",
            arrangement_set_at=400, pointer_speed=2.0))
        saved = self.saved()
        self.assertEqual((saved["peers"][0]["side"], saved["peers"][0]["side_set_at"], saved["peers"][0]["side_by"]),
                         ("top", 300, HIGH))
        self.assertEqual(saved["zones"], [{"peer": BT, "kind": "edge"}])
        self.assertFalse(saved["shortcut"])
        self.assertEqual(saved["pointer_speed"], 2.0)

    def test_a_flat_save_keeps_a_name_and_hardware_address_learnt_since_the_window_read(self):
        stale = app_config.load_config(self.path)
        settings = self.saved()
        settings["peers"][0].update(name="Bee Studio", hw="aa:bb:cc:dd:ee:01")
        app_config.write_settings(self.path, settings)
        app_config.save_config(self.path, app_config.replace(stale, pointer_speed=2.0))
        self.assertEqual((self.peer(BT)["name"], self.peer(BT)["hw"]), ("Bee Studio", "aa:bb:cc:dd:ee:01"))
        app_config.save_config(self.path, app_config.replace(stale, mac_host="192.0.2.99", paired_with="",
                                                              mac_hardware_address=""))
        self.assertEqual((self.peer(BT)["host"], self.peer(BT)["name"], self.peer(BT)["hw"]), ("192.0.2.99", "", ""))

    def test_an_arrangement_rewrites_the_edge_that_machines_corner_crosses(self):
        settings = self.saved()
        settings["zones"].append({"peer": BT, "kind": "corner", "corner": "top_right", "edge": "left"})
        app_config.write_settings(self.path, settings)
        self.assertEqual(app_config.apply_arrangement(self.path, BT, "left", 500, HIGH), (True, []))
        self.assertEqual((self.peer(BT)["side"], self.zones(BT)["corner"]["edge"]), ("right", "right"))

    def test_old_peer_arrangement_compiles_without_historical_off_zones(self):
        changed, notices = app_config.apply_arrangement(self.path, CT, "right", 500, HIGH)
        self.assertTrue(changed)
        self.assertEqual(self.peer(CT)["side"], "left")
        self.assertEqual(notices, [])
        self.assertEqual(self.zones(CT), {})
        self.assertTrue(self.peer(CT)["ways"]["edge"])


class DiagramGeometryTests(unittest.TestCase):
    SCREEN = (120.0, 75.0)

    def test_machines_sharing_a_side_are_ordered_by_their_thirds_then_the_list(self):
        slots = pages_win.side_slots([
            {"side": "right", "methods": ["part"], "parts": ["end"]},
            {"side": "right", "methods": ["part"], "parts": ["start"]},
            {"side": "top", "methods": [], "parts": ["middle"]},
            {"side": "", "methods": ["corner"], "parts": ["middle"]},
        ])
        self.assertEqual(slots, [("right", 0.5, 1.0), ("right", 0.0, 0.5), ("top", 0.0, 1.0), None])

    def test_one_machine_sits_where_the_pair_always_did(self):
        for side, offset in (("right", (134.0, 0.0)), ("left", (-134.0, 0.0)), ("top", (0.0, -89.0)), ("bottom", (0.0, 89.0))):
            pc, (other,), _height = pages_win.layout_rects(400.0, 0.0, [(pages_win.SIDE_ANGLE[side], 0.0, 1.0)], self.SCREEN, 14.0)
            self.assertEqual((other[0] - pc[0], other[1] - pc[1]), offset, side)
            self.assertEqual(other[2:], self.SCREEN)
        pc, (other,), height = pages_win.layout_rects(400.0, 10.0, [(0.0, 0.0, 1.0)], self.SCREEN, 14.0)
        self.assertEqual(height, 75.0)
        self.assertEqual((pc[0] + other[0] + other[2]) / 2.0, 200.0)
        self.assertEqual(pc[1], 10.0)
        _pc, _rects, stacked = pages_win.layout_rects(400.0, 0.0, [(90.0, 0.0, 1.0)], self.SCREEN, 14.0)
        self.assertEqual(stacked, 164.0)

    def test_a_row_puts_this_pc_in_the_middle(self):
        pc, (left, right), height = pages_win.layout_rects(
            500.0, 0.0, [(180.0, 0.0, 1.0), (0.0, 0.0, 1.0)], self.SCREEN, 14.0)
        self.assertEqual(pc[0] + pc[2] / 2.0, 250.0)
        self.assertEqual(left[0] + left[2] + 14.0, pc[0])
        self.assertEqual(right[0], pc[0] + pc[2] + 14.0)
        self.assertEqual(height, 75.0)

    def test_two_on_one_side_are_each_half_as_long_and_split_it(self):
        pc, (top, bottom), _height = pages_win.layout_rects(
            500.0, 0.0, [(0.0, 0.0, 0.5), (0.0, 0.5, 1.0)], self.SCREEN, 14.0)
        self.assertEqual(top[2:], (60.0, 37.5))
        self.assertEqual(bottom[2:], (60.0, 37.5))
        self.assertEqual(top[0], pc[0] + pc[2] + 14.0)
        self.assertEqual((top[1], bottom[1] + bottom[3]), (pc[1], pc[1] + pc[3]))

    def test_an_l_has_one_beside_and_one_above(self):
        pc, (right, above), height = pages_win.layout_rects(
            500.0, 0.0, [(0.0, 0.0, 1.0), (90.0, 0.0, 1.0)], self.SCREEN, 14.0)
        self.assertEqual((right[0], right[1]), (pc[0] + pc[2] + 14.0, pc[1]))
        self.assertEqual((above[0], above[1] + above[3] + 14.0), (pc[0], pc[1]))
        self.assertEqual(above[1], 0.0)
        self.assertEqual(height, 164.0)

    def test_with_several_machines_this_pc_stays_in_the_middle_whatever_the_sides(self):
        for placed in ([(0.0, 0.0, 1.0), (90.0, 0.0, 1.0)], [(0.0, 0.0, 0.5), (0.0, 0.5, 1.0)]):
            pc, _rects, _height = pages_win.layout_rects(500.0, 0.0, placed, self.SCREEN, 14.0, centre_pc=True)
            self.assertEqual(pc[0] + pc[2] / 2.0, 250.0, placed)
        pc, (_left, right), _height = pages_win.layout_rects(
            300.0, 0.0, [(0.0, 0.0, 1.0), (90.0, 0.0, 1.0)], self.SCREEN, 14.0, centre_pc=True)
        self.assertEqual(pc[0] + pc[2] / 2.0, 150.0)
        self.assertLessEqual(right[0] + right[2], 300.001)

    def test_a_narrow_width_shrinks_the_drawing_to_fit(self):
        pc, (left, right), _height = pages_win.layout_rects(
            300.0, 0.0, [(180.0, 0.0, 1.0), (0.0, 0.0, 1.0)], self.SCREEN, 14.0)
        self.assertGreaterEqual(left[0], -0.001)
        self.assertLessEqual(right[0] + right[2], 300.001)
        self.assertLess(pc[2], 120.0)

    def test_nobody_goes_through_this_pc_on_the_way_round(self):
        for start, end in ((0.0, 1.0), (0.0, 0.5), (0.5, 1.0)):
            for angle in range(0, 360, 5):
                pc, (other,), _height = pages_win.layout_rects(500.0, 0.0, [(float(angle), start, end)], self.SCREEN, 14.0)
                apart_x = other[0] >= pc[0] + pc[2] or other[0] + other[2] <= pc[0]
                apart_y = other[1] >= pc[1] + pc[3] or other[1] + other[3] <= pc[1]
                self.assertTrue(apart_x or apart_y, (angle, start, end))

    def test_the_description_names_every_machine_and_its_side(self):
        machines = [
            {"label": "Bee", "side": "right", "methods": ["edge"], "parts": ["middle"], "corner": "top_left", "chosen": True},
            {"label": "Sea", "side": "top", "methods": [], "parts": ["middle"], "corner": "top_left", "chosen": False},
            {"label": "Dee", "side": "", "methods": [], "parts": ["middle"], "corner": "top_left", "chosen": False},
        ]
        text = pages_win.diagram_description(machines, "Right Ctrl", "hold", True)
        self.assertIn("Bee is to the right of this PC", text)
        self.assertIn("Sea is above this PC", text)
        self.assertIn("Not placed yet: Dee", text)
        self.assertIn("Input moves to Bee when you push through the whole right edge", text)

    def test_the_unplaced_line_names_them_all(self):
        self.assertEqual(pages_win.unplaced_line(["Sea"]), "Not placed yet: Sea")
        self.assertEqual(pages_win.unplaced_line(["Sea", "Dee", "Eff"]), "Not placed yet: Sea, Dee and Eff")
        self.assertEqual(pages_win.unplaced_line([]), "")


class WordingTests(unittest.TestCase):
    def test_the_summary_and_the_unlearned_side_name_the_machine(self):
        self.assertEqual(pages_win.ways_summary(["edge"], "right", [], "top_left", "F13", "hold", "Sea"),
                         "Input moves to Sea when you push through the whole right edge.")
        self.assertIn("on Sea", pages_win.not_learned_edge("Sea"))
        self.assertIn("the other machine", pages_win.not_learned_edge())

    def test_no_page_purpose_pictures_exactly_one_other_machine(self):
        for _key, _name, purpose in pages_win.PAGES:
            self.assertNotIn("the other machine", purpose)
        for line in pages_win.SCOPE.values():
            self.assertNotIn("the other machine", line)


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class WindowTests(unittest.TestCase):
    """The real window, built offscreen from a settings file, which starts no receiver, hooks or announcer."""

    PEERS = None

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"
        settings = app_config.migrate(None, machine_id=protocol.id_text(harness.HERE))
        settings["peers"] = self.PEERS if self.PEERS is not None else [
            harness.entry(B, "Bee", side="left", side_set_at=100, side_by=HIGH, paired_with=[]),
            harness.entry(C, "Sea", platform="windows", allow_drive=False),
        ]
        settings["zones"] = [{"peer": BT, "kind": "edge"}]
        settings["port"] = harness.free_port()
        app_config.write_settings(self.path, settings)
        self.window = kvm_bridge_win.WindowsApplication(self.path)
        self.linked = {BT, CT}
        self.window._live = lambda peer: peer in self.linked
        self.sent = []
        self.window._send_to = lambda peer, message: self.sent.append((peer, message)) or True
        self.window._refresh_window()

    def tearDown(self):
        self.window.server.stop()
        self.window.deleteLater()

    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def peer(self, ident):
        return next(item for item in self.saved()["peers"] if item["id"] == ident)


class ShortcutCycleRefreshTests(WindowTests):
    def test_ticked_cycle_remains_visible_after_peer_state_refresh(self):
        self.window._config.shortcut_goes_to = "ticked"

        self.window._refresh_peers()
        rows = [row for row in self.window.machines.rows.values() if not row._phone]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.shortcut_cycle.isVisibleTo(self.window.machines) for row in rows))

        self.window._refresh_peer_states()

        self.assertTrue(all(row.shortcut_cycle.isVisibleTo(self.window.machines) for row in rows))


class HeaderResponseTests(WindowTests):
    def test_active_sender_peer_uses_outgoing_measurement_before_other_driver(self):
        outgoing, incoming = B, C
        link = SimpleNamespace(live=lambda: True, response_time_ms=23)
        links = SimpleNamespace(_by_peer={outgoing: link}, up=lambda peer: peer == outgoing,
                                _link=lambda peer: link if peer == outgoing else None)
        with mock.patch.object(self.window, "sender", SimpleNamespace(owner=outgoing, links=links)), \
             mock.patch.object(self.window, "server", SimpleNamespace(owner=incoming, links=lambda: {incoming},
                                                                      response_time_ms=lambda _peer: 91)):
            self.assertEqual(self.window._header_response_time(), ("Bee", 23, True))

    def test_receive_only_driver_uses_incoming_measurement(self):
        sender = SimpleNamespace(owner=None, links=SimpleNamespace(up=lambda _peer: False, _link=lambda _peer: None))
        server = SimpleNamespace(owner=C, links=lambda: {C}, response_time_ms=lambda peer: 42 if peer == C else None)
        with mock.patch.object(self.window, "sender", sender), mock.patch.object(self.window, "server", server):
            self.assertEqual(self.window._header_response_time(), ("Sea", 42, True))

    def test_windows_identity_advertises_ping_response_measurements(self):
        self.assertIn("ping_rtt", self.window._identity()["caps"])


class CrossingPageTests(WindowTests):
    def drop(self, peer, x, y, w=160, h=100, positions=None):
        layout = {key: dict(tile) for key, tile in self.window.atlas_canvas.tiles.items()}
        layout.update(positions or {})
        layout[peer] = {"x": x, "y": y, "w": w, "h": h}
        self.window._choose_machine(peer)
        return self.window._layout_dropped(layout, peer)

    def sharing_side(self):
        settings = app_config.load_settings(self.path)
        for peer in settings["peers"]:
            peer.update(side="right", side_set_at=100 if peer["id"] == BT else 200, side_by=HIGH)
        settings["zones"] = [{"peer": BT, "kind": "edge"}, {"peer": CT, "kind": "edge", "off": True}]
        app_config.write_settings(self.path, settings)
        self.window._pull_peer_fields()
        self.window._choose_machine(CT)
        return self.window

    def test_offline_picture_peer_keeps_its_zone_when_another_edge_is_edited(self):
        window = self.sharing_side()
        self.linked = {CT}
        before = dict(self.bee_zone())
        window._ledger_edge(CT)
        window._ledger_edge(CT)
        self.assertEqual(self.bee_zone(), before)
        self.assertTrue(self.peer(CT)["ways"]["edge"])
        self.assertFalse(any("aside" in zone for zone in self.saved()["zones"]))

    def lid_shut(self):
        """Keep Bee offline while Sea edits its ways."""
        window = self.sharing_side()
        self.linked = {CT}
        window._choose_machine(CT)
        self.assertTrue(window._write_ways(methods=["edge"]))
        self.alerts = []
        window._on_alert = lambda title, message: self.alerts.append(message)
        return window

    def bee_zone(self):
        return next(zone for zone in app_config.load_settings(self.path)["zones"]
                    if zone["peer"] == BT and zone["kind"] == "edge")

    def test_offline_picture_peer_keeps_its_zone_and_reconnection_adds_no_glue(self):
        window = self.lid_shut()
        before = self.saved()
        self.assertNotIn("aside", self.bee_zone())
        self.linked = {BT, CT}
        window._settle_presence()
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.alerts, [])

    def test_reconnecting_picture_peer_keeps_allocations_and_ledger_status_updates(self):
        window = self.lid_shut()
        before = self.saved()["zones"]
        self.linked = {BT, CT}
        window._settle_presence()
        window._reflect_ways()
        self.assertEqual(self.saved()["zones"], before)
        self.assertEqual(self.alerts, [])
        self.assertIn("Linked", window.crossing_ledger.rows[BT].status.text())

    def test_forgotten_peer_has_no_zones_but_keeps_intent_and_a_ledger_row(self):
        window = self.lid_shut()
        settings = self.saved()
        settings["peers"][0].update(dormant=True, dormant_reason="forgotten")
        app_config.write_settings(self.path, settings)
        window._pull_peer_fields()
        window._write_ways(peer=CT, edge=True)
        self.assertFalse(any(z["peer"] == BT for z in self.saved()["zones"]))
        self.assertTrue(self.peer(BT)["ways"]["edge"])
        self.assertIn(BT, window.atlas_canvas.shelf_ids)
        self.assertIn(BT, window.crossing_ledger.rows)
        self.assertFalse(hasattr(window, "left_out_shelf"))

    def test_selected_machine_is_named_in_its_ledger_row(self):
        window = self.sharing_side()
        self.assertEqual(window.crossing_ledger.rows[CT].name.full_text, "Sea")
        self.assertTrue(window.crossing_ledger.rows[CT].selected)
        self.assertFalse(hasattr(window, "blocked_note"))

    def test_removing_a_machine_that_shared_a_side_leaves_the_zones_as_a_fresh_compile(self):
        # rc16 bug hunt #6 suspected the PC kept stale zones until the next link-up, as it skips the
        # Mac's compile on save; the narrowed thirds are the remaining machine's own saved choice, so
        # a compile changes nothing. This holds that.
        self.sharing_side()
        self.assertTrue(self.drop(CT, 160, 80, 160, 20, {BT: dict(x=160, y=0, w=160, h=80)}))
        self.assertIn((BT, "part"), {(z["peer"], z["kind"]) for z in self.saved()["zones"]})
        self.window._remove_peer(harness.TOKENS[C])
        saved = self.saved()
        compiled = crossing_state.migrate(saved, "pc", capable=self.window._layout_capable())["settings"]
        self.assertEqual(saved["zones"], compiled["zones"])
        self.assertNotIn(CT, {zone["peer"] for zone in saved["zones"]})

    def test_dropping_tiles_on_separate_thirds_saves_and_tells_the_new_way_back(self):
        window = self.sharing_side()
        self.assertTrue(self.drop(CT, 160, 67, 160, 33, {BT: dict(x=160, y=0, w=160, h=33)}))
        zones = {(z["peer"], z["kind"]): z for z in self.saved()["zones"]}
        self.assertEqual(zones[(BT, "part")]["parts"], ["start"])
        self.assertEqual(zones[(CT, "part")]["parts"], ["end"])
        self.assertNotIn((BT, "edge"), zones)
        self.assertNotIn((CT, "edge"), zones)
        self.assertEqual(self.peer(BT)["side"], "right")
        self.assertEqual(self.peer(CT)["side"], "right")
        self.assertEqual({peer for peer, _data in self.arrangements()}, {B, C})
        self.assertTrue(all(data["way_back"] for _, data in self.arrangements()))

    def test_overlapping_drop_lands_only_at_an_accepted_free_position(self):
        window = self.sharing_side()
        self.assertTrue(self.drop(CT, 160, -50))
        layout = self.saved()["layout"]
        self.assertFalse(ways._overlaps(layout[BT], layout[CT]))
        self.assertEqual(window.atlas_canvas.tiles[CT], layout[CT])

    def test_an_overlapping_partial_tile_is_sent_to_a_free_snap(self):
        window = self.sharing_side()
        self.assertTrue(self.drop(CT, 160, -50, 160, 33))
        layout = self.saved()["layout"]
        self.assertFalse(ways._overlaps(layout[BT], layout[CT]))
        self.assertFalse(ways._overlaps(layout[window._config.machine_id], layout[CT]))

    def test_with_two_machines_paired_the_page_offers_a_choice_of_machine(self):
        window = self.window
        self.assertEqual(set(window.atlas_canvas.tiles), {window._config.machine_id, BT, CT})
        self.assertEqual((window.atlas_canvas.labels[BT], window.atlas_canvas.labels[CT]), ("Bee", "Sea"))
        self.assertEqual(window.atlas_canvas.selected, BT)
        self.assertEqual(ways.ways(window._crossing_settings(), BT)["side"], "left")
        self.assertEqual(window.crossing_ledger.rows[BT].name.full_text, "Bee")

    def test_choosing_a_machine_shows_its_ways(self):
        window = self.window
        window._choose_machine(CT)
        self.assertEqual(ways.ways(window._crossing_settings(), CT)["methods"], ["edge"])
        self.assertEqual(window.crossing_ledger.rows[CT].name.full_text, "Sea")
        self.assertTrue(window.crossing_ledger.rows[CT].selected)
        self.assertFalse(window.crossing_ledger.rows[BT].selected)
        self.assertEqual(window.atlas_canvas.selected, CT)

    def test_a_side_set_here_is_that_machines_alone_and_is_sent_to_it(self):
        window = self.window
        window._choose_machine(CT)
        self.assertTrue(self.drop(CT, 160, 0))
        self.assertEqual(self.peer(CT)["side"], "right")
        self.assertEqual(self.peer(BT)["side"], "left")
        (peer, message), = self.sent
        self.assertEqual(peer, C)
        self.assertEqual(message["data"]["edge"], "right")
        self.assertEqual(message["data"]["set_at"], self.peer(CT)["side_set_at"])

    def arrangements(self):
        return [(peer, message["data"]) for peer, message in self.sent if message["type"] == protocol.MSG_ARRANGEMENT]

    def test_ledger_way_changes_tell_the_peer_its_current_return_way(self):
        next(chip for chip in self.window.crossing_ledger.rows[BT].edge_chips.chips.values() if chip.kind == "contact").click()
        peer, data = self.arrangements()[-1]
        self.assertEqual(peer, B)
        self.assertFalse(data["way_back"])
        self.assertEqual(data["edge"], self.peer(BT)["side"])
        self.window.crossing_ledger.rows[BT].corner_grid.buttons["top_left"].click()
        self.assertTrue(self.arrangements()[-1][1]["way_back"])

    def test_moving_one_machine_tells_every_machine_whose_way_back_it_changed(self):
        self.assertTrue(self.drop(BT, -400, 0, positions={CT: dict(x=400, y=200, w=160, h=100)}))
        told = {peer: data for peer, data in self.arrangements()}
        self.assertEqual(set(told), {B, C})
        self.assertTrue(all(data["way_back"] is False for data in told.values()))

    def test_removing_a_left_out_machine_keeps_the_remaining_crossing(self):
        self.window._canvas_left_out(CT, True)
        self.sent.clear()
        self.window._remove_peer(harness.TOKENS[C])
        saved = self.saved()
        self.assertEqual([p["id"] for p in saved["peers"]], [BT])
        self.assertTrue(ways.has_way(saved, BT))
        self.assertFalse(any(peer == C for peer, _data in self.arrangements()))

    def test_picture_peer_return_way_changes_are_saved_without_an_answer(self):
        window = self.window
        before = self.saved()["layout"]
        window.bridge.arrangement.emit(CT, "left", 500, HIGH, True, None)
        self.assertTrue(self.peer(CT)["way_back"])
        self.assertEqual(self.saved()["layout"], before)
        self.assertEqual(self.arrangements(), [])
        window.bridge.arrangement.emit(CT, "left", 500, HIGH, False, None)
        self.assertFalse(self.peer(CT)["way_back"])
        self.assertEqual(self.arrangements(), [])

    def test_every_link_up_says_whether_a_way_leads_to_that_machine(self):
        told = lambda: next(m["data"] for m in self.window._announce(B) if m["type"] == protocol.MSG_ARRANGEMENT)
        self.assertIs(told()["way_back"], True)
        self.assertTrue(self.drop(BT, -400, 0))
        self.assertIs(told()["way_back"], False)

    def test_either_link_hands_on_way_back(self):
        heard = []
        self.window.bridge.arrangement.connect(lambda *args: heard.append(args))
        read = {"edge": "left", "set_at": 500, "by": HIGH_ID, "way_back": False}
        self.window.server._callbacks["arrangement"](C, read)
        self.window.sender.arrangement_callback(C, {**read, "set_at": 501, "way_back": True})
        self.assertEqual([args[4] for args in heard], [False, True])

    def test_drop_over_another_machine_saves_a_nonoverlapping_snap(self):
        window = self.window
        self.assertTrue(self.drop(CT, -160, 0))
        saved = self.saved()["layout"]
        self.assertFalse(ways._overlaps(saved[BT], saved[CT]))
        self.assertEqual(window.atlas_canvas.selected, CT)

    def test_ways_written_here_reach_that_machines_zones_only(self):
        window = self.window
        self.assertTrue(self.drop(CT, 160, 0))
        before = dict(self.peer(BT)["ways"])
        window.crossing_ledger.rows[CT].corner_grid.buttons["bottom_right"].click()
        corners = [z for z in self.saved()["zones"] if z["peer"] == CT and z["kind"] == "corner"]
        self.assertEqual(corners[0]["corner"], "bottom_right")
        self.assertEqual(self.peer(BT)["ways"], before)

    def test_the_shortcut_stays_this_pcs_own(self):
        window = self.window
        window._ways_changed("shortcut", False)
        self.assertFalse(self.saved()["shortcut"])
        window._choose_machine(BT)
        self.assertFalse(self.saved()["shortcut"])
        self.assertTrue(self.peer(BT).get("shortcut_cycle", True))

    def test_selected_machine_stays_named_without_a_missing_way_inspector(self):
        window = self.window
        window._choose_machine(CT)
        self.assertEqual(window.crossing_ledger.rows[CT].name.full_text, "Sea")
        self.assertTrue(window.crossing_ledger.rows[CT].selected)
        self.assertFalse(hasattr(window, "missing_note"))

    def test_picture_arrangement_keeps_layout_and_selects_its_ledger_row(self):
        window = self.window
        before = self.saved()["layout"]
        window._on_arrangement(CT, "right", 500, HIGH)
        window._choose_machine(CT)
        self.assertEqual(self.saved()["layout"], before)
        self.assertTrue(window.crossing_ledger.rows[CT].selected)
        self.assertFalse(hasattr(window, "blocked_note"))

    def test_picture_peer_return_way_flag_updates_without_a_notice_block(self):
        window = self.window
        window._on_arrangement(BT, "right", 50, HIGH, False)
        self.assertFalse(self.peer(BT)["way_back"])
        window._on_arrangement(BT, "right", 50, HIGH, True)
        self.assertTrue(self.peer(BT)["way_back"])
        self.assertFalse(hasattr(window, "no_way_back_note"))

    def test_arrangement_keeps_the_return_way_holder_without_a_notice_block(self):
        window = self.window
        window._on_arrangement(CT, "right", 500, HIGH, False, BT)
        self.assertEqual(self.peer(CT)["way_back_by"], BT)
        self.assertFalse(hasattr(window, "no_way_back_note"))

    def test_nonselected_picture_arrangement_keeps_its_side_and_layout(self):
        window = self.window
        before = self.saved()["layout"]
        side = self.peer(CT)["side"]
        window._on_arrangement(CT, "left", 500, HIGH, True)
        self.assertEqual(window.atlas_canvas.selected, BT)
        self.assertEqual(self.peer(CT)["side"], side)
        self.assertEqual(self.saved()["layout"], before)
        self.assertTrue(self.peer(CT)["way_back"])

    def test_the_diagram_draws_every_machine(self):
        window = self.window
        window._choose_machine(CT)
        self.assertTrue(self.drop(CT, 160, 0))
        canvas = window.atlas_canvas
        own = canvas.tiles[window._config.machine_id]
        self.assertEqual(ways._rect_contact(own, canvas.tiles[BT])[0], "left")
        self.assertEqual(ways._rect_contact(own, canvas.tiles[CT])[0], "right")
        self.assertEqual(canvas.selected, CT)
        self.assertEqual((canvas.labels[BT], canvas.labels[CT]), ("Bee", "Sea"))

    def test_pause_counts_every_machines_zones(self):
        window = self.window
        window._choose_machine(BT)
        self.assertTrue(self.drop(BT, -400, 0,
                                 positions={CT: {"x": 400, "y": 200, "w": 160, "h": 100}}))
        self.assertFalse(window._crossing_state_args()[4])
        window._choose_machine(CT)
        self.assertTrue(self.drop(CT, 160, 0))
        self.assertTrue(window._crossing_state_args()[4])

    def test_granular_same_groups_name_each_shared_area(self):
        self.assertEqual(set(self.window.same_checks), {"crossing", "design", "shortcut", "names", "everything"})
        self.assertIn("Names shares this machine's name and paired-machine labels",
                      self.window.same_content_note.text())


class OneMachineTests(WindowTests):
    PEERS = [harness.entry(B, "Bee", side="left")]

    def test_one_machine_is_selected_on_the_canvas_with_its_existing_way(self):
        window = self.window
        self.assertEqual(set(window.atlas_canvas.tiles), {window._config.machine_id, BT})
        self.assertEqual(window.atlas_canvas.selected, BT)
        self.assertEqual(window.crossing_ledger.rows[BT].name.full_text, "Bee")
        self.assertEqual(ways.ways(window._crossing_settings(), BT)["side"], "left")
        self.assertEqual(ways.ways(window._crossing_settings(), BT)["methods"], ["edge"])

    def test_the_tray_has_no_item_per_machine_and_the_button_names_it(self):
        window = self.window
        self.assertEqual(window.machine_actions, {})
        self.assertEqual(window.redirect_action.text(), "Send input to Bee")
        self.assertTrue(window.redirect_action.isVisible())


class TrayTests(WindowTests):
    def setUp(self):
        # The tray of a desktop that can send input from a menu; on Wayland only an edge can
        # (test_linux_start), and a Linux test run over SSH reads as Wayland.
        patcher = mock.patch("platform_parts.WAYLAND", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_tray_groups_status_version_connection_directions_and_settings(self):
        window = self.window
        actions = window.tray_menu.actions()
        self.assertIs(actions[0], window.status_action)
        self.assertTrue(actions[1].isSeparator())
        self.assertIs(actions[2], window.header_action)
        self.assertTrue(actions[3].isSeparator())
        labels = [action.text() for action in actions if not action.isSeparator()]
        self.assertLess(labels.index("Send input to Bee"), labels.index("Pause crossing"))
        self.assertLess(labels.index("Pause crossing"), labels.index(window.send_action.text()))
        self.assertLess(labels.index(window.send_action.text()), labels.index(window.drive_action.text()))
        self.assertLess(labels.index(window.drive_action.text()), labels.index("Settings…"))
        self.assertEqual(window.open_action.text(), "Settings…")

    def test_each_machine_this_pc_sends_to_has_its_own_tray_item(self):
        window = self.window
        self.assertEqual([action.text() for action in window.machine_actions.values()],
                         ["Send input to Bee", "Send input to Sea"])
        went = []
        window.sender.go = lambda peer, *args: went.append(peer) or True
        window.machine_actions[CT].trigger()
        self.assertEqual(went, [C])
        self.assertFalse(window.redirect_action.isVisible())

    def test_a_machine_whose_link_is_down_is_dimmed_as_unavailable(self):
        window = self.window
        self.linked = {BT}
        window._refresh_tray_machines()
        bee, sea = window.machine_actions[BT], window.machine_actions[CT]
        self.assertEqual((bee.text(), bee.isEnabled()), ("Send input to Bee", True))
        self.assertEqual((sea.text(), sea.isEnabled()), ("Sea is unavailable", False))
        self.linked = {BT, CT}
        window._refresh_tray_machines()
        self.assertEqual((sea.text(), sea.isEnabled()), ("Send input to Sea", True))

    def test_active_target_row_returns_input_and_owner_changes_update_existing_rows(self):
        window = self.window
        returned = []
        went = []
        sender = SimpleNamespace(redirecting=True, owner=C,
                                 set_redirecting=lambda enabled: returned.append(enabled),
                                 go=lambda peer, *args: went.append(peer) or True,
                                 shortcut_target=lambda: C)
        with mock.patch.object(window, "sender", sender):
            window._refresh_tray_machines()
            sea = window.machine_actions[CT]
            bee = window.machine_actions[BT]
            self.assertEqual(sea.text(), "Bring input back")
            self.assertTrue(sea.isEnabled())
            self.assertFalse(window.redirect_action.isVisible())
            sea.trigger()
            self.assertEqual(returned, [False])

            sender.owner = B
            window._refresh_tray_machines()
            self.assertIs(window.machine_actions[CT], sea)
            self.assertIs(window.machine_actions[BT], bee)
            self.assertEqual(sea.text(), "Send input to Sea")
            self.assertEqual(bee.text(), "Bring input back")
            sea.trigger()
            self.assertEqual(went, [C])

            next(entry for entry in window._peer_entries if entry["id"] == CT)["name"] = "Seaside"
            window._labels_by_id[C] = "Seaside"
            window._refresh_tray_machines()
            self.assertIs(window.machine_actions[CT], sea)
            self.assertEqual(sea.text(), "Send input to Seaside")

            sender.redirecting = False
            sender.owner = None
            window._refresh_tray_machines()
            self.assertEqual(sea.text(), "Send input to Seaside")
            self.assertEqual(bee.text(), "Send input to Bee")

            window._peer_entries = [entry for entry in window._peer_entries if entry.get("id") == CT]
            window._refresh_tray_machines()
            self.assertEqual(window.machine_actions, {})
            self.assertTrue(window.redirect_action.isVisible())
            self.assertEqual(window._redirect_text(), "Send input to Seaside")

            window._peer_entries = []
            window._refresh_tray_machines()
            self.assertEqual(window.machine_actions, {})
            self.assertTrue(window.redirect_action.isVisible())

    def test_direction_switches_name_every_machine_and_distinguish_mixed_none_and_all(self):
        window = self.window

        def set_directions(send, allow_drive):
            settings = self.saved()
            for entry, sends, allows in zip(settings["peers"], send, allow_drive):
                entry["send"] = sends
                entry["allow_drive"] = allows
            app_config.write_settings(self.path, settings)
            window._pull_peer_fields()
            window._refresh_tray_directions()

        set_directions((True, False), (False, True))
        self.assertEqual(window.send_action.text(), "This PC drives every machine (some enabled)")
        self.assertEqual(window.drive_action.text(), "Every machine drives this PC (some enabled)")
        self.assertFalse(window.send_action.isChecked())
        self.assertFalse(window.drive_action.isChecked())
        window._after_peers_edit = lambda: None
        window.send_action.trigger()
        self.assertTrue(all(entry["send"] is True for entry in self.saved()["peers"]))
        self.assertTrue(window.send_action.isChecked())

        set_directions((False, False), (False, False))
        self.assertEqual(window.send_action.text(), "This PC drives every machine")
        self.assertEqual(window.drive_action.text(), "Every machine drives this PC")
        self.assertFalse(window.send_action.isChecked())
        self.assertFalse(window.drive_action.isChecked())

        set_directions((True, True), (True, True))
        self.assertTrue(window.send_action.isChecked())
        self.assertTrue(window.drive_action.isChecked())
        window.send_action.trigger()
        self.assertTrue(all(entry["send"] is False for entry in self.saved()["peers"]))

    def test_zero_peers_leave_the_disabled_general_send_action_available(self):
        window = self.window
        window._peer_entries = []
        window._refresh_tray_directions()
        window._refresh_tray_machines()
        self.assertFalse(window.send_action.isEnabled())
        self.assertFalse(window.drive_action.isEnabled())
        self.assertEqual(window.machine_actions, {})
        self.assertTrue(window.redirect_action.isVisible())

    def test_the_send_button_names_the_machine_the_shortcut_would_pick(self):
        window = self.window
        window.sender.shortcut_target = lambda: C
        window._refresh_window()
        self.assertEqual(window.redirect_button.text(), "Send input to Sea")


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class DiagramWidgetTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])

    def machine(self, key, label, side, methods=(), chosen=False, parts=("middle",)):
        return {"key": key, "label": label, "side": side, "methods": list(methods), "parts": list(parts),
                "corner": "top_left", "chosen": chosen}

    def test_each_machines_marks_are_its_own_and_the_unplaced_are_named_underneath(self):
        picture = diagram.ArrangementDiagram()
        picture.resize(500, picture.height())
        picture.set_machines([self.machine("b", "Bee", "left", ["edge"], chosen=True),
                              self.machine("c", "Sea", "right", ["part"], parts=["end"]),
                              self.machine("d", "Dee", "")], "Right Ctrl", "hold", True)
        self.assertEqual(picture._marks[("edge", "b", "left")], 1.0)
        self.assertEqual(picture._marks[("part", "c", "right", "end")], 1.0)
        self.assertEqual(picture._marks[("part", "c", "right", "start")], 0.0)
        self.assertEqual(picture._unplaced, "Not placed yet: Dee")
        self.assertFalse(picture.grab().isNull())

    def test_one_machine_with_no_side_is_drawn_on_the_right_but_no_edge_lights_until_a_side_is_held(self):
        # This PC's engine crosses no edge for a machine with no side, as the page's Not learned yet says.
        picture = diagram.ArrangementDiagram()
        picture.set_machines([self.machine("b", "Bee", "", ["edge", "part"], chosen=True)], "Right Ctrl", "hold", False)
        self.assertEqual(picture._unplaced, "")
        self.assertEqual(diagram._drawn_side({"side": ""}, True), "right")
        self.assertEqual(picture._marks[("edge", "b", "right")], 0.0)
        self.assertEqual(picture._marks[("track", "b", "right")], 0.0)
        self.assertEqual(picture._marks[("part", "b", "right", "middle")], 0.0)
        picture.set_machines([self.machine("b", "Bee", "right", ["edge"], chosen=True)], "Right Ctrl", "hold", False)
        self.assertEqual(picture._marks[("edge", "b", "right")], 1.0)


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class TrayRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(
            sender=SimpleNamespace(redirecting=False, owner=None, route_chain=(HERE, B, C)),
            server=SimpleNamespace(owner=None),
            _labels_by_id={B: "PC", C: "Linux"},
            _identity=lambda: {"id": HERE, "name": "Mac"},
            _label_of=lambda peer: {B: "PC", C: "Linux"}.get(peer, "another machine"),
        )

    def test_tray_state_names_the_machine_that_drives_this_pc(self):
        self.assertEqual(kvm_bridge_win.WindowsApplication._drive_status(self.app), "Idle")
        self.app.sender.redirecting = True
        self.app.sender.owner = B
        self.assertEqual(kvm_bridge_win.WindowsApplication._drive_status(self.app), "Driving PC")
        self.app.sender.redirecting = False
        self.app.server.owner = C
        self.assertEqual(kvm_bridge_win.WindowsApplication._drive_status(self.app), "Driven by Linux")

    def test_crossing_route_shows_the_whole_chain_in_order(self):
        self.assertEqual(kvm_bridge_win.WindowsApplication._current_chain_sentence(self.app),
                         "Current chain: Mac → PC → Linux")


if __name__ == "__main__":
    unittest.main()
