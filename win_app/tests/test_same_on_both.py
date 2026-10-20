"""Same on all machines in the real window: the Overview switch, a Mac's settings arriving, and a
change here going out. Built offscreen from a synthetic config as test_style_for builds it, which
starts no receiver, hooks or announcer; the two links' sends are recorded instead."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    import kvm_bridge_win
    import pages_win
    from core import settings_sync
    import theme
    import app_config
    from app_config import load_config
    from core import protocol
    from core.tests import responder_harness as harness
except ImportError:  # PySide6 is only in the Windows venv
    kvm_bridge_win = None


def mac_message(on, set_at, by=None, **values):
    base = dict(shortcut=False, resistance_px=60,
                block_while_dragging=False, trigger_key="alt_r", trigger_style="hold", double_tap_ms=400,
                glow_style="beam", glow_colour="ocean", effect_length="long", shortcut_arrival=False,
                shortcut_arrival_style="locator")
    base.update(values)
    return settings_sync.message_data(on, set_at, base, by=by or protocol.id_text(harness.B),
                                      groups=settings_sync.ALL_GROUPS if on else [])


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class SameOnBothTest(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        folder = Path(tempfile.mkdtemp())
        self.path = folder / "settings.json"
        (folder / "config.json").write_text(json.dumps({
            "host": "192.168.1.20", "port": harness.free_port(), "auth_token": "synthetic", "paired_with": "MacBook Pro",
            "mac_host": "192.168.1.10", "mac_return_edge": "left", "edge_glow": True,
        }))
        self.window = kvm_bridge_win.WindowsApplication(self.path)
        self.sent = []
        self.peers = {harness.B: {"settings"}, harness.C: {"settings"}}
        self.window._peer_caps = lambda: dict(self.peers)
        self.window._send_to = lambda peer, message: self.sent.append((peer, message["data"])) or True
        self.window._refresh_window()

    def tearDown(self):
        self.window.server.stop()
        self.window.deleteLater()

    def pair_peer(self, peer: str) -> None:
        settings = app_config.load_settings(self.path)
        settings["peers"][0]["id"] = peer
        app_config.write_settings(self.path, settings)
        self.window._refresh_peers()

    def test_off_by_default_with_each_page_its_own(self):
        self.assertFalse(self.window.same_checks["everything"].isChecked())
        self.assertEqual(set(self.window.same_checks), {"crossing", "design", "shortcut", "names", "everything"})
        self.assertEqual(self.window.scope_labels["design"].text(), pages_win.SCOPE["design"])

    def test_unchanged_refresh_does_not_reload_settings_for_same_on_all(self):
        self.window._show_same()
        with mock.patch.object(app_config, "load_settings", wraps=app_config.load_settings) as load:
            self.window._show_same()
            self.window._show_same()
        load.assert_not_called()

    def test_same_on_all_reloads_a_changed_settings_file(self):
        self.window._show_same()
        settings = app_config.load_settings(self.path)
        settings["same_before_sync"] = {"saved_at": int(time.time()), "groups": [],
                                         "values": {"shortcut": False}, "names": {}}
        app_config.write_settings(self.path, settings)

        with mock.patch.object(app_config, "load_settings", wraps=app_config.load_settings) as load:
            self.window._show_same()

        load.assert_called_once_with(self.path)
        self.assertFalse(self.window.same_revert.isHidden())

    def test_same_on_all_rechecks_a_write_that_lands_during_the_read(self):
        original_load = app_config.load_settings
        saved = {"saved_at": int(time.time()), "groups": [], "values": {"shortcut": False}, "names": {}}
        calls = 0

        def load_then_write(path):
            nonlocal calls
            settings = original_load(path)
            if calls == 0:
                changed = original_load(path)
                changed["same_before_sync"] = saved
                app_config.write_settings(path, changed)
            calls += 1
            return settings

        self.window._same_settings_signature = object()
        with mock.patch.object(app_config, "load_settings", side_effect=load_then_write):
            self.window._show_same()
            self.window._show_same()

        self.assertEqual(calls, 2)
        self.assertFalse(self.window.same_revert.isHidden())

    def test_display_reconciliation_skips_unchanged_inputs_and_runs_for_changes(self):
        self.window._refresh_own_displays = lambda: None
        self.window._own_display_map = {"screen": {"x": 0, "y": 0, "width": 1920, "height": 1080}}
        self.window._carry_crossing = mock.Mock()
        with mock.patch.object(kvm_bridge_win.crossing_state, "displays_changed",
                               wraps=kvm_bridge_win.crossing_state.displays_changed) as reconcile:
            self.window._displays_changed()
            self.window._displays_changed()
            self.assertEqual(reconcile.call_count, 1)
            self.window._own_display_map = {"screen": {"x": 0, "y": 0, "width": 1600, "height": 900}}
            self.window._displays_changed()
            self.assertEqual(reconcile.call_count, 2)
            settings = app_config.load_settings(self.path)
            settings["name"] = "Changed from another process"
            app_config.write_settings(self.path, settings)
            self.window._displays_changed()
            self.assertEqual(reconcile.call_count, 3)

    def test_display_reconciliation_rechecks_a_write_that_lands_during_the_read(self):
        self.window._refresh_own_displays = lambda: None
        self.window._own_display_map = {"screen": {"x": 0, "y": 0, "width": 1920, "height": 1080}}
        self.window._carry_crossing = mock.Mock()
        original = kvm_bridge_win.crossing_state.displays_changed
        calls = 0

        def reconcile_then_write(*args, **kwargs):
            nonlocal calls
            outcome = original(*args, **kwargs)
            if calls == 0:
                settings = app_config.load_settings(self.path)
                settings["name"] = "Changed during reconciliation"
                app_config.write_settings(self.path, settings)
            calls += 1
            return outcome

        with mock.patch.object(kvm_bridge_win.crossing_state, "displays_changed",
                               side_effect=reconcile_then_write):
            self.window._displays_changed()
            self.window._displays_changed()

        self.assertEqual(calls, 2)

    def test_display_reconciliation_retries_after_a_settings_read_recovers(self):
        self.window._refresh_own_displays = lambda: None
        self.window._own_display_map = {"screen": {"x": 0, "y": 0, "width": 1920, "height": 1080}}
        self.window._carry_crossing = mock.Mock()
        self.window._window_settings_version = None
        self.window._displays_signature = None
        original_load = app_config.load_settings

        with mock.patch.object(app_config, "load_settings",
                               side_effect=[OSError("temporary read failure"), original_load(self.path)]), \
             mock.patch.object(kvm_bridge_win.crossing_state, "displays_changed",
                               wraps=kvm_bridge_win.crossing_state.displays_changed) as reconcile:
            self.window._displays_changed()
            self.assertTrue(self.window._window_settings_stale)
            self.window._displays_changed()

        self.assertFalse(self.window._window_settings_stale)
        self.assertEqual(reconcile.call_count, 1)

    def test_display_reconciliation_tracks_legacy_settings_changes(self):
        self.window._refresh_own_displays = lambda: None
        self.window._own_display_map = {"screen": {"x": 0, "y": 0, "width": 1920, "height": 1080}}
        self.window._carry_crossing = mock.Mock()
        legacy_path = app_config.legacy_config_path(self.path)

        with mock.patch.object(kvm_bridge_win.crossing_state, "displays_changed",
                               wraps=kvm_bridge_win.crossing_state.displays_changed) as reconcile:
            self.window._displays_changed()
            legacy_path.write_text(legacy_path.read_text() + "\n")
            self.window._displays_changed()

        self.assertEqual(reconcile.call_count, 2)

    def test_everything_can_be_turned_off(self):
        self.window._set_same_groups(settings_sync.ALL_GROUPS)
        self.window.same_checks["everything"].setChecked(False)

        self.assertEqual(self.window._config.same_groups, [])

    def test_an_old_peer_does_not_change_this_pcs_group_selection(self):
        self.window._config.same_groups = ["design"]
        message = mac_message(True, 100, resistance_px=60)
        message.pop("groups")
        self.window._on_settings(protocol.id_text(harness.B), message)

        self.assertEqual(self.window._config.same_groups, ["design"])
        self.assertEqual(self.window._config.crossing_resistance_px, 120)

    def test_revert_restores_the_saved_values_and_announces_them(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        data = settings_sync.message_data(True, 100, {"resistance_px": 60}, by=peer,
                                          groups=["crossing"])
        self.window._on_settings(peer, data)
        self.assertTrue(settings_sync.snapshot_available(
            app_config.load_settings(self.path).get("same_before_sync")))

        self.window._revert_same()

        self.assertEqual(self.window._config.crossing_resistance_px, 120)
        self.assertEqual(self.window._config.same_groups, ["crossing"])
        self.assertEqual(self.sent[-1][1]["crossing"]["resistance_px"], 120)

    def test_revert_clears_a_first_remote_label_with_a_new_stamp(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        data = settings_sync.message_data(True, 100, by=peer, groups=["names"], names={
            peer: {"label": "Named here", "set_at": 100, "by": peer},
        })
        self.window._on_settings(peer, data)
        self.assertEqual(app_config.load_settings(self.path)["peers"][0]["label"], "Named here")

        self.window._revert_same()

        restored = app_config.load_settings(self.path)["peers"][0]
        self.assertEqual(restored["label"], "")
        self.assertGreater(restored["label_set_at"], 100)

    def test_legacy_off_state_stays_off_when_announced_to_a_group_peer(self):
        self.window._config.same_groups = ["design"]
        self.window._on_settings(protocol.id_text(harness.B), {"on": False, "set_at": 100,
                                                                 "by": protocol.id_text(harness.B)})

        self.assertFalse(self.window._same_state()["on"])
        self.assertEqual(self.window._same_state()["groups"], ["design"])

    def test_revert_keeps_the_current_trigger_when_a_jump_chord_now_uses_it(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        original_groups = list(self.window._config.same_groups)
        self.window._config.trigger_key = "alt_r"
        self.window._persist()
        # The key changed here holds its own stamp now: only a newer choice from the peer replaces it.
        newer = self.window._config.same_stamps["trigger_key"][0] + 1
        data = settings_sync.message_data(True, newer, {"trigger_key": "f13"}, by=peer,
                                          groups=["shortcut"])
        self.window._on_settings(peer, data)
        settings = app_config.load_settings(self.path)
        settings["peers"][0]["jump_key"] = "alt+cmd+3"
        app_config.write_settings(self.path, settings)
        self.window._peer_entries = settings["peers"]

        self.window._revert_same()

        self.assertEqual(self.window._config.trigger_key, "f13")
        self.assertEqual(self.window._config.same_groups, ["shortcut"])

    def test_names_only_keeps_design_following_and_local_scope(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        self.window._config.same_on_both = True
        self.window._config.same_groups = ["names"]
        self.window._config.design_follow_peer = peer
        self.window._design_states[peer] = {"set_at": 100, "by": peer, "values": {"effect_length": "long"}}
        self.window._apply_followed_design(force=True)
        self.window._show_same()
        self.assertEqual(self.window._config.effect_length, "long")
        self.assertNotIn("crossing", self.window.scope_labels)
        row = self.window.crossing_ledger.rows[peer]
        row.begin_rename()
        self.assertIn("Only on this PC", row.rename_hint.text())
        self.assertEqual(self.window.scope_labels["design"].text(), pages_win.SCOPE["design"])
        self.assertIn("Names", self.window.same_note.text())

    def test_stale_names_policy_cannot_rename_after_names_was_deselected(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        self.window._on_settings(peer, settings_sync.message_data(True, 200, by=peer, groups=["crossing"]))
        self.window._on_settings(peer, settings_sync.message_data(True, 100, by=peer, groups=["names"],
            names={peer: {"label": "Delayed", "set_at": 300, "by": peer}}))
        self.assertNotEqual(app_config.load_settings(self.path)["peers"][0].get("label"), "Delayed")

    def test_local_design_change_does_not_stamp_a_names_only_policy(self):
        self.window._config.same_groups = ["names"]
        self.window._config.same_on_both = True
        self.window._config.same_set_at = 100
        self.window._same_seen = self.window._same_fields()
        self.window._config.glow_colour = "ocean"
        self.window._persist()
        self.assertEqual(self.window._config.same_set_at, 100)

    def test_a_remote_selection_that_drops_design_resumes_the_cached_leader(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        config = self.window._config
        config.same_on_both, config.same_groups, config.same_set_at = True, ["design"], 10
        config.design_follow_peer = peer
        self.window._design_states[peer] = {"set_at": 100, "by": peer, "values": {"effect_length": "long"}}
        self.window._followed_version = (peer, 100, peer)
        self.window._on_settings(protocol.id_text(harness.C), settings_sync.message_data(
            True, 11, by=protocol.id_text(harness.C), groups=["names"]))
        self.assertEqual(self.window._config.effect_length, "long")

    def test_selection_only_revert_keeps_a_later_local_design_edit(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        config = self.window._config
        config.same_on_both, config.same_groups, config.same_set_at = True, ["crossing"], 10
        self.window._on_settings(peer, settings_sync.message_data(True, 11, by=peer, groups=["design"]))
        self.window._config.glow_colour = "ocean"
        self.window._revert_same()
        self.assertEqual(self.window._config.same_groups, ["crossing"])
        self.assertEqual(self.window._config.glow_colour, "ocean")
        self.assertEqual(self.window.glow_colour_choice.value, "ocean")

    def test_older_settings_peer_without_layout_capability_shows_group_note(self):
        self.window._peer_caps = lambda: {harness.B: {"settings"}}

        self.window._show_same()

        self.assertFalse(self.window.same_old_note.isHidden())
        self.assertTrue(self.window.same_checks["crossing"].isEnabled())

    def test_full_screen_hold_switch_names_this_pcs_edges(self):
        self.assertEqual(self.window.hold_switch.text(), "Hold this PC's edges while an app on it is full screen")
    def test_this_pcs_design_state_is_announced_when_same_is_off(self):
        data = self.window._same_state()

        self.assertFalse(data["on"])
        self.assertEqual(data["design_sync"]["values"]["effect_size"], "medium")
        self.assertEqual(set(data["design_sync"]["values"]), set(settings_sync.DESIGN_KEYS))

    def test_a_followed_design_is_applied_and_renamed_as_this_pcs_state(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        self.window._config.design_follow_peer = peer
        received = settings_sync.message_data(
            False, 100, by=peer,
            design_state={"set_at": 200, "by": peer,
                          "values": {"effect_length": "long"}},
        )

        self.window._on_settings(peer, received)

        self.assertEqual(self.window._config.effect_length, "long")
        self.assertGreater(self.window._config.design_set_at, 200)
        self.assertEqual(self.window._config.design_by, self.window._config.machine_id)
        self.assertEqual(self.sent[-1][1]["design_sync"]["values"]["effect_length"], "long")

    def test_a_design_state_in_a_malformed_settings_envelope_is_dropped_whole(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        self.window._config.design_follow_peer = peer
        state = {"set_at": 200, "by": peer, "values": {"effect_length": "long"}}

        for outer in ({"on": "no"}, {"set_at": True}, {"by": "not an id"}):
            received = settings_sync.message_data(False, 100, by=peer, design_state=state)
            received.update(outer)
            self.window._on_settings(peer, received)

        self.assertEqual(self.window._config.effect_length, "normal")
        self.assertNotIn(peer, self.window._design_states)
        self.assertEqual(self.sent, [])

    def test_follow_accepts_the_leaders_next_change_after_this_pc_reannounces(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        config = self.window._config
        config.design_follow_peer = peer
        config.design_set_at = 50
        config.design_by = peer

        for stamp, length in ((100, "long"), (101, "short")):
            received = settings_sync.message_data(
                False, stamp - 50, by=peer,
                design_state={"set_at": stamp, "by": peer, "values": {"effect_length": length}},
            )
            self.window._on_settings(peer, received)

        self.assertEqual(self.window._config.effect_length, "short")
        self.assertGreater(self.window._config.design_set_at, 101)
        self.assertEqual(self.window._config.design_by, self.window._config.machine_id)
        self.assertEqual(self.sent[-1][1]["design_sync"]["values"]["effect_length"], "short")
        self.assertEqual((self.sent[-1][1]["design_sync"]["set_at"], self.sent[-1][1]["design_sync"]["by"]),
                         (self.window._config.design_set_at, self.window._config.machine_id))

    def test_followed_size_updates_the_control_without_saving_a_local_edit(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        self.window._config.design_follow_peer = peer
        received = settings_sync.message_data(
            False, 100, by=peer,
            design_state={"set_at": 200, "by": peer, "values": {"effect_size": "large"}},
        )

        self.window._on_settings(peer, received)

        self.assertEqual(self.window.size_choice.value, "large")
        self.assertEqual(self.window._config.effect_size, "large")
        self.assertEqual(self.sent[-1][1]["design_sync"]["values"]["effect_size"], "large")

    def test_same_on_design_change_is_announced_with_a_new_local_design_stamp(self):
        source = protocol.id_text(harness.C)
        config = self.window._config
        config.same_on_both = True
        config.same_set_at = 10
        config.same_by = source
        config.design_set_at = 20
        config.design_by = config.machine_id
        config.effect_length = "short"
        received = mac_message(True, 11, by=source, effect_length="long")
        received["design_sync"] = {
            "set_at": 100, "by": source, "values": {"effect_length": "long"},
        }

        self.window._on_settings(source, received)

        self.assertEqual(self.window._config.effect_length, "long")
        self.assertGreater(self.window._config.design_set_at, 100)
        self.assertEqual(self.window._config.design_by, self.window._config.machine_id)
        self.assertEqual(self.sent[-1][1]["design_sync"]["set_at"], self.window._config.design_set_at)
        self.assertNotEqual(self.sent[-1][1]["design_sync"]["by"], source)

    def test_same_off_from_another_machine_resumes_the_cached_followed_design(self):
        leader = protocol.id_text(harness.B)
        other = protocol.id_text(harness.C)
        self.pair_peer(leader)
        config = self.window._config
        config.same_on_both = True
        config.same_groups = list(settings_sync.ALL_GROUPS)
        config.same_set_at = 10
        config.same_by = other
        config.design_follow_peer = leader
        config.effect_length = "short"
        self.window._design_states[leader] = {
            "set_at": 100, "by": leader, "values": {"effect_length": "long"},
        }
        apply_followed = mock.Mock(wraps=self.window._apply_followed_design)
        self.window._apply_followed_design = apply_followed

        self.window._on_settings(other, settings_sync.message_data(False, 11, by=other))

        apply_followed.assert_called_once()
        self.assertEqual(self.window._config.effect_length, "long")
        self.assertEqual(self.sent[-1][1]["design_sync"]["values"]["effect_length"], "long")
        self.assertEqual((self.sent[-1][1]["design_sync"]["set_at"], self.sent[-1][1]["design_sync"]["by"]),
                         (self.window._config.design_set_at, self.window._config.machine_id))

    def follow(self, **values):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        # A preset set alone would lose to the held slider value when the config resolves them.
        for key, value in settings_sync._with_continuous(values).items():
            setattr(self.window._config, key, value)
        self.window._config.design_follow_peer = peer
        self.window._reflect_config(self.window._config)
        self.window._design_seen = self.window._design_fields()
        self.window._refresh_design_follow()
        return peer

    def followed_controls(self):
        w = self.window
        return [w.length_choice.view, w.size_choice.view, w.landing_toggle,
                *(w.glow_style_choice.tile(value) for value in self.window.effect_stills),
                *(w.switch_style_choice.tile(value) for value in self.window.switch_stills),
                *w.glow_colour_choice._swatches.values()]

    def test_following_locks_the_followed_design_controls_under_a_banner(self):
        self.follow()

        self.assertFalse(any(control.isEnabled() for control in self.followed_controls()))
        for control in (self.window.length_choice.view, self.window.size_choice.view,
                        self.window.glow_colour_choice.view, self.window.landing_toggle):
            self.assertAlmostEqual(control.graphicsEffect().opacity(), 0.45)
        for choice in (self.window.glow_style_choice, self.window.switch_style_choice):
            for tiles in choice.groups.values():
                self.assertAlmostEqual(tiles.view.graphicsEffect().opacity(), 0.45)
        self.assertTrue(self.window.glow_toggle.isEnabled())
        self.assertFalse(self.window.follow_banner.isHidden())
        self.assertEqual(self.window.follow_banner_label.text(), "Following MacBook Pro's design")

    def test_a_click_on_a_locked_control_changes_nothing_and_keeps_following(self):
        peer = self.follow(effect_length="long")
        self.sent.clear()

        QTest.mouseClick(self.window.length_choice.view, Qt.MouseButton.LeftButton)
        QTest.keyClick(self.window.length_choice.view, Qt.Key.Key_Left)
        self.window.landing_toggle.click()

        self.assertEqual(self.window.length_choice.value, "long")
        self.assertEqual(self.window._config.effect_length, "long")
        self.assertEqual(self.window._config.design_follow_peer, peer)
        self.assertEqual(self.sent, [])

    def test_stop_following_unlocks_the_controls_and_keeps_the_shown_design(self):
        self.follow(effect_length="long", glow_colour="ocean")

        self.window.stop_follow_button.click()

        self.assertEqual(self.window._config.design_follow_peer, "")
        self.assertTrue(all(control.isEnabled() for control in self.followed_controls()))
        self.assertTrue(self.window.follow_banner.isHidden())
        self.assertEqual((self.window.length_choice.value, self.window._config.effect_length), ("long", "long"))
        self.assertEqual((self.window.glow_colour_choice.value, self.window._config.glow_colour), ("ocean", "ocean"))
        self.assertEqual(self.sent[-1][1]["design_sync"]["values"]["effect_length"], "long")

    def test_unpairing_the_followed_machine_resets_the_selection(self):
        peer = protocol.id_text(harness.B)
        self.window._config.design_follow_peer = peer
        with mock.patch.object(self.window.book, "peers", return_value=[]), \
                mock.patch.object(self.window.book, "zones", return_value=[]):
            self.window._refresh_peers()

        self.assertEqual(self.window._config.design_follow_peer, "")

    def test_same_on_all_machines_keeps_precedence_over_a_followed_design(self):
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        self.window._config.design_follow_peer = peer
        self.window._config.same_on_both = True
        self.window._config.same_set_at = 100
        self.window._config.same_groups = list(settings_sync.ALL_GROUPS)
        received = settings_sync.message_data(
            True, 101, settings_sync.pc_values(self.window._config), by=peer,
            design_state={"set_at": 202, "by": peer,
                          "values": {"effect_length": "long"}},
        )

        self.window._on_settings(peer, received)

        self.assertEqual(self.window._config.effect_length, "normal")
        self.assertEqual(self.window._config.design_follow_peer, protocol.id_text(harness.B))

    def test_an_older_peer_is_disabled_in_match_design_with(self):
        self.window._peer_entries = [harness.entry(harness.B, "Old PC")]
        self.peers = {harness.B: {"settings"}}
        self.window._design_peer_caps = lambda: {protocol.id_text(harness.B): {"settings"}}

        self.window._refresh_design_follow()

        self.assertFalse(self.window.design_follow_choice.model().item(1).isEnabled())
        self.assertIn("Needs beta.6 or later", self.window.design_follow_choice.itemText(1))

    def test_design_follow_keeps_its_model_until_inputs_change(self):
        self.window._design_peer_caps = lambda: {}
        self.window._refresh_design_follow()
        model = self.window.design_follow_choice.model()

        self.window._refresh_design_follow()

        self.assertIs(self.window.design_follow_choice.model(), model)

    def test_design_follow_refreshes_rows_when_peer_capabilities_change(self):
        peer = harness.entry(harness.B, "MacBook Pro")
        self.window._peer_entries = [peer]
        caps = {}
        self.window._design_peer_caps = lambda: caps
        self.window._refresh_design_follow()
        model = self.window.design_follow_choice.model()
        self.assertEqual(model.rowCount(), 1)

        caps[peer["id"]] = {"settings"}
        self.window._refresh_design_follow()

        self.assertIs(self.window.design_follow_choice.model(), model)
        self.assertEqual(model.rowCount(), 2)

    def test_design_follow_updates_lock_when_same_on_design_changes(self):
        peer = harness.entry(harness.B, "MacBook Pro")
        self.window._peer_entries = [peer]
        self.window._design_peer_caps = lambda: {peer["id"]: {"settings", "layout", "design_sync"}}
        self.window._config.design_follow_peer = peer["id"]
        self.window._config.same_on_both = False
        self.window._config.same_groups = []
        self.window._design_states[peer["id"]] = {"set_at": 1, "by": peer["id"], "values": {}}
        self.window._refresh_design_follow()
        self.assertFalse(self.window.follow_banner.isHidden())

        self.window._config.same_on_both = True
        self.window._config.same_groups = ["design"]
        self.window._refresh_design_follow()

        self.assertTrue(self.window.follow_banner.isHidden())

    def test_design_follow_label_refreshes_when_hide_addresses_changes(self):
        peer = harness.entry(harness.B, "192.168.1.10")
        self.window._peer_entries = [peer]
        self.window._design_peer_caps = lambda: {peer["id"]: {"settings", "layout", "design_sync"}}
        self.window._config.design_follow_peer = peer["id"]
        self.window._design_states[peer["id"]] = {"set_at": 1, "by": peer["id"], "values": {}}
        self.window._config.hide_addresses = False
        self.window._refresh_design_follow()
        model = self.window.design_follow_choice.model()
        self.assertEqual(model.item(1).text(), "192.168.1.10")

        self.window._config.hide_addresses = True
        self.window._refresh_design_follow()

        self.assertEqual(model.item(1).text(), pages_win.HIDDEN)

    def test_peer_refresh_reads_peers_and_zones_from_one_snapshot(self):
        peer = harness.entry(harness.B, "MacBook Pro")
        zone = {"peer": peer["id"], "side": "left"}
        snapshot = mock.Mock(return_value=([peer], [zone]))
        self.window.book.snapshot = snapshot
        peers = mock.Mock(side_effect=AssertionError("peers() must not read a second snapshot"))
        zones = mock.Mock(side_effect=AssertionError("zones() must not read a second snapshot"))
        self.window.book.peers = peers
        self.window.book.zones = zones

        self.window._refresh_peers()

        snapshot.assert_called_once_with()
        peers.assert_not_called()
        zones.assert_not_called()
        self.assertEqual(self.window._peer_entries, [peer])
        self.assertEqual(self.window._zone_entries, [zone])
        snapshot.return_value = ([], [])
        self.window._refresh_peers()
        self.assertEqual(snapshot.call_count, 2)
        self.assertEqual(self.window._peer_entries, [])

    def test_unchanged_refreshes_have_bounded_retained_python_memory(self):
        import gc
        import tracemalloc

        self.window._show_same()
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for _ in range(400):
            self.window._refresh_window()
        gc.collect()
        after = tracemalloc.take_snapshot()
        tracemalloc.stop()
        retained = sum(stat.size_diff for stat in after.compare_to(before, "filename")
                       if "/win_app/" in str(stat.traceback))

        self.assertLess(retained, 64 * 1024, f"retained Qt refresh allocations: {retained} bytes")

    def test_the_macs_settings_arrive_on_this_pcs_fields_and_controls(self):
        self.window._on_settings(protocol.id_text(harness.B), mac_message(True, 100))
        config = self.window._config
        self.assertTrue(config.same_on_both)
        self.assertNotIn("shortcut", config.crossing_methods)
        self.assertEqual((config.glow_style, config.glow_colour, config.effect_length), ("beam", "ocean", "long"))
        self.assertEqual((config.trigger_style, config.double_tap_ms, config.shortcut_arrival), ("hold", 400, False))
        self.assertTrue(config.edge_glow)
        self.assertEqual(load_config(self.path).glow_style, "beam")
        self.assertEqual(self.window.resistance_slider.value(), 60)
        self.assertFalse(self.window.landing_toggle.isChecked())
        self.window._refresh_window()
        self.assertTrue(self.window.same_checks["crossing"].isChecked())
        self.assertNotIn("crossing", self.window.scope_labels)
        self.assertFalse(self.window.dragging_switch.isChecked())
        # Applying what arrived is not a change made here: it goes on to the other peer and never back.
        self.assertEqual([peer for peer, _data in self.sent], [harness.C])

    def test_an_older_message_changes_nothing(self):
        self.window._on_settings(protocol.id_text(harness.B), mac_message(True, 100))
        self.window._on_settings(protocol.id_text(harness.B), mac_message(True, 90, glow_style="glow"))
        self.assertEqual(self.window._config.glow_style, "beam")

    def test_a_state_a_peer_already_holds_is_not_sent_on_again(self):
        self.window._on_settings(protocol.id_text(harness.B), mac_message(True, 100))
        self.sent.clear()
        self.window._on_settings(protocol.id_text(harness.C), mac_message(True, 100))
        self.assertEqual(self.sent, [])

    def test_a_peer_without_the_settings_capability_is_sent_none(self):
        self.peers[harness.C] = set()
        self.window.same_checks["everything"].setChecked(True)
        self.assertEqual([peer for peer, _data in self.sent], [harness.B])

    def test_turning_it_on_here_sends_this_pcs_values_to_every_peer_that_takes_them(self):
        self.window.same_checks["everything"].setChecked(True)
        self.assertEqual([peer for peer, _data in self.sent], [harness.B, harness.C])
        data = self.sent[0][1]
        self.assertTrue(data["on"])
        self.assertIs(data["crossing"]["shortcut"], True)

    def test_a_change_here_while_on_is_stamped_and_sent_and_one_to_this_pcs_own_is_not(self):
        self.window.same_checks["everything"].setChecked(True)
        stamp = self.window._config.same_set_at
        self.sent.clear()
        self.window._config.same_set_at = stamp - 10
        self.window._config.edge_glow = False
        self.window._persist()
        self.assertEqual(self.sent, [])
        self.window._config.effect_length = "short"
        self.window._config.effect_pace = 0.5
        self.window._persist()
        self.assertEqual(len(self.sent), 2)
        self.assertGreaterEqual(self.window._config.same_set_at, stamp)
        self.assertEqual(self.window._config.same_by, self.window._config.machine_id)
        self.assertEqual(self.sent[0][1]["design"]["effect_length"], "short")

    # Per-key stamps (rc14, 10-10-2026): an edit carries only what a person changed.
    def test_a_change_here_stamps_only_that_value_and_the_state_carries_each_stamp(self):
        config = self.window._config
        seed = [config.same_set_at, config.same_by]
        self.window.same_checks["everything"].setChecked(True)
        self.sent.clear()
        self.window._config.crossing_resistance_px = 60
        self.window._persist()
        config = self.window._config
        stamps = config.same_stamps
        self.assertEqual(stamps["resistance_px"][1], config.machine_id)
        self.assertEqual({key for key, stamp in stamps.items() if list(stamp) != seed}, {"resistance_px"},
                         "turning it on froze every other value at the stamp it held")
        self.assertEqual(app_config.load_settings(self.path)["same_stamps"]["resistance_px"],
                         list(stamps["resistance_px"]))
        sent = self.sent[0][1]
        self.assertEqual(sent["stamps"]["resistance_px"], list(stamps["resistance_px"]))
        self.assertEqual(sent["stamps"]["glow_colour"], seed)
        self.assertGreaterEqual(sent["set_at"], stamps["resistance_px"][0])
        self.assertEqual(self.window._same_state()["stamps"], sent["stamps"])

    def test_a_newer_value_in_an_older_state_is_taken_alone_and_a_newer_one_here_is_answered(self):
        self.window.same_checks["everything"].setChecked(True)
        self.window._config.crossing_resistance_px = 60
        self.window._persist()
        config = self.window._config
        policy = (config.same_set_at, config.same_by)
        mine = config.same_stamps["resistance_px"][0]
        self.sent.clear()
        peer = protocol.id_text(harness.B)
        stamps = settings_sync.held_stamps({"glow_colour": [5, peer], "resistance_px": [4, peer]}, 0, "")
        data = settings_sync.message_data(True, policy[0] - 1, dict(
            resistance_px=30, glow_colour="ocean", trigger_key="alt_r"), by=peer,
            groups=settings_sync.ALL_GROUPS, stamps=stamps)
        self.window._on_settings(peer, data)
        config = self.window._config
        self.assertEqual((config.glow_colour, config.crossing_resistance_px), ("ocean", 60))
        self.assertNotEqual(config.trigger_key, "alt_r")
        self.assertEqual((config.same_set_at, config.same_by), policy)
        self.assertEqual(config.same_stamps["glow_colour"], [5, peer])
        forwarded = [sent for to, sent in self.sent if to == harness.C and sent["by"] == peer]
        self.assertEqual([sent["stamps"] for sent in forwarded], [data["stamps"]], "what it took goes on as it came")
        answers = [sent for to, sent in self.sent if to == harness.B]
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]["stamps"]["resistance_px"], [mine, config.machine_id])

    def test_a_value_changed_here_while_off_outlives_an_older_state_turning_it_on(self):
        self.window._config.crossing_resistance_px = 60
        self.window._persist()
        self.assertEqual(self.sent, [])
        config = self.window._config
        mine = config.same_stamps["resistance_px"]
        self.assertEqual(mine[1], config.machine_id)
        peer = protocol.id_text(harness.B)
        self.window._on_settings(peer, mac_message(True, mine[0] - 1, resistance_px=30))
        config = self.window._config
        self.assertTrue(config.same_on_both)
        self.assertEqual((config.crossing_resistance_px, config.glow_colour), (60, "ocean"))
        answer = [sent for to, sent in self.sent if to == harness.B][-1]
        # The value travels with its own stamp, newer than the state it comes in.
        self.assertEqual(answer["stamps"]["resistance_px"], mine)
        held = settings_sync.held_stamps({}, mine[0] - 1, peer)
        back = settings_sync.merge(answer, held, mine[0] - 1, kvm_bridge_win.TRIGGER_KEYS, by_here=peer,
                                   on_here=True, current_groups=settings_sync.ALL_GROUPS)
        self.assertEqual(back["values"], {"resistance_px": 60})

    def test_a_save_after_a_link_replaced_the_first_peer_does_not_bring_the_old_pairing_back(self):
        # A fold removed the entry migrated from 1.4.x; the window still holds its token.
        settings = app_config.load_settings(self.path)
        settings["peers"] = [harness.entry(harness.B, "Mac", linked=True, token=harness.TOKENS[harness.B])]
        settings["zones"] = []
        app_config.write_settings(self.path, settings)
        self.window._config.effect_length = "short"
        self.window._config.effect_pace = 0.5
        self.assertTrue(self.window._persist())
        saved = app_config.load_settings(self.path)
        self.assertEqual([peer["token"] for peer in saved["peers"]], [harness.TOKENS[harness.B]])
        self.assertEqual(self.window._config.auth_token, harness.TOKENS[harness.B])

    def test_a_state_that_goes_on_is_forwarded_with_this_pcs_direct_design_state(self):
        self.peers = {harness.B: {"settings"}, harness.C: {"settings"}}
        message = mac_message(True, 100)
        self.window._on_settings(protocol.id_text(harness.B), message)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], harness.C)
        forwarded = self.sent[0][1]
        self.assertEqual({key: value for key, value in forwarded.items() if key != "design_sync"},
                         {key: value for key, value in message.items() if key != "design_sync"})
        self.assertEqual(forwarded["design_sync"]["by"], self.window._config.machine_id)

    def test_a_design_change_here_while_off_announces_its_local_state(self):
        self.window._config.effect_length = "short"
        self.window._config.effect_pace = 0.5
        self.window._persist()
        self.assertEqual(len(self.sent), 2)
        self.assertTrue(all(message["design_sync"]["values"]["effect_length"] == "short"
                            for _peer, message in self.sent))

    def test_announcing_carries_a_chosen_arrangement_the_peers_it_may_send_to_and_the_settings(self):
        settings = app_config.load_settings(self.path)
        settings["peers"][0]["id"] = protocol.id_text(harness.B)
        inactive = dict(settings["peers"][0], id=protocol.id_text(harness.C), token="inactive", in_use=False)
        settings["peers"].append(inactive)
        app_config.write_settings(self.path, settings)
        self.peers = {harness.B: {"settings"}}
        messages = self.window._announce(harness.B)
        self.assertEqual([m["type"] for m in messages], ["arrangement", "paired", "settings"])
        self.assertEqual(messages[1]["data"]["ids"], [])
        settings["peers"][0].update(side="left", side_set_at=500, side_by=self.window._config.machine_id)
        app_config.write_settings(self.path, settings)
        messages = self.window._announce(harness.B)
        self.assertEqual(messages[0]["type"], "arrangement")
        self.assertEqual(messages[0]["data"]["edge"], "left")
        self.assertEqual(messages[0]["data"]["set_at"], 500)

    def test_a_followed_design_is_not_stamped_as_this_pcs_choice(self):
        # The Mac's follow path stamps nothing; stamped here, a copied design beat a real choice.
        peer = protocol.id_text(harness.B)
        self.pair_peer(peer)
        config = self.window._config
        config.same_on_both, config.same_groups, config.same_set_at = True, ["crossing"], 10
        self.window._same_seen = self.window._same_fields()
        config.design_follow_peer = peer
        self.window._design_states[peer] = {"set_at": 100, "by": peer, "values": {"glow_colour": "ocean"}}
        self.window._apply_followed_design(force=True)
        self.assertEqual(self.window._config.glow_colour, "ocean")
        stamp = settings_sync.held_stamps(config.same_stamps, config.same_set_at, config.same_by)["glow_colour"]
        self.assertNotEqual(stamp[1], config.machine_id, "the followed colour was stamped as chosen here")


if __name__ == "__main__":
    unittest.main()
