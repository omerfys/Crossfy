import copy
import unittest

from core import crossing_state, profiles, protocol, ways


OWN, PEER, OTHER = (protocol.id_text(bytes([n]) * 16) for n in (1, 2, 3))
ALL = ["start", "middle", "end"]


def tile(x=0, y=0, w=160, h=100, **extra):
    return {"x": x, "y": y, "w": w, "h": h, **extra}


def base():
    default = {"edge": True, "thirds": ALL[:], "edges": [], "corner": False,
               "corner_at": "top_left", "corners": [], "notch": False}
    row = {PEER: {"ways": copy.deepcopy(default), "notch_return": False}}
    own_profile = {
        "name": {"value": "Desk", "set_at": 0, "by": ""}, "removed": None,
        "home": {"shake": {"value": True, "set_at": 0, "by": ""}},
        "rows": {OWN: {"set_at": 10, "by": OWN, "value": copy.deepcopy(row)}},
    }
    return {
        "machine_id": OWN,
        "peers": [{"id": PEER, "port": 24820, "side": "right", "send": True,
                   "ways": copy.deepcopy(row[PEER]["ways"]), "notch_return": False}],
        "zones": [], "layout": {OWN: tile(), PEER: tile(160)},
        "layout_set_at": 10, "layout_by": OWN,
        "crossing_desk": {"format": 1, "on": {"value": True, "set_at": 20, "by": OWN},
                           "active": {"value": profiles.DESK_ID, "set_at": 0, "by": ""},
                           "profiles": {profiles.DESK_ID: own_profile}, "status": {}},
        "crossing_own": {"format": 1, "use_own": False, "row": copy.deepcopy(row),
                         "shake": True, "applied": copy.deepcopy(row), "saved": []},
    }


class ProfileEventTests(unittest.TestCase):
    def test_existing_crossing_events_reconcile_and_report_desk_paths(self):
        held = base()
        out = crossing_state.edit_ways(held, PEER, thirds=["start"], platform="mac",
                                       live=lambda _: True, gone=lambda _: False, now=40)
        row = out["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OWN]
        self.assertEqual(row["value"][PEER]["ways"]["thirds"], ["start"])
        self.assertIn(("row", profiles.DESK_ID, OWN), out["send_desk"])
        self.assertEqual(out["settings"]["crossing_own"]["applied"],
                         profiles.live_row(out["settings"]))

    def test_turning_same_on_seeds_without_changing_live_crossings(self):
        held = base()
        held["crossing_desk"]["on"] = {"value": False, "set_at": 30, "by": OWN}
        held["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"].pop(OWN)
        before = profiles.live_row(held)
        out = crossing_state.set_same_ways(held, True, platform="mac", now=40)
        self.assertTrue(out["accepted"])
        self.assertEqual(profiles.live_row(out["settings"]), before)
        row = out["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OWN]
        self.assertEqual(row["value"], before)
        self.assertEqual(row["set_at"], 40)

    def test_own_override_is_local_and_share_mine_writes_the_active_desk_row(self):
        held = base()
        enabled = crossing_state.set_own_ways(held, True, platform="mac", now=41)
        self.assertTrue(enabled["settings"]["crossing_own"]["use_own"])
        edited = crossing_state.edit_ways(enabled["settings"], PEER, edge=False, platform="mac",
                                          live=lambda _: True, gone=lambda _: False, now=42)
        changed = edited["settings"]["crossing_own"]["row"]
        shared = crossing_state.share_mine(edited["settings"], platform="mac", now=43)
        row = shared["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OWN]
        self.assertEqual(row["value"], changed)
        self.assertTrue(any(path[0] == "row" for path in shared["send_desk"]))

    def test_edit_other_changes_only_the_target_machine_row(self):
        held = base()
        target_row = {OWN: {"ways": {"edge": True, "thirds": ALL[:], "edges": [],
                                     "corner": False, "corner_at": "top_left",
                                     "corners": [], "notch": False}, "notch_return": False}}
        held["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OTHER] = {
            "set_at": 5, "by": OWN, "value": target_row}
        out = crossing_state.edit_other(held, OTHER, OWN, thirds=["end"], platform="mac", now=50)
        row = out["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OTHER]
        self.assertEqual(row["value"][OWN]["ways"]["thirds"], ["end"])
        self.assertEqual(profiles.live_row(out["settings"]), profiles.live_row(held))

    def test_edit_other_keeps_the_last_thirds_choice_and_refuses_a_held_corner(self):
        held = base()
        row = {OWN: {"ways": {"edge": True, "thirds": ["middle"], "edges": [],
                              "corner": False, "corner_at": "top_left", "corners": [],
                              "notch": False}, "notch_return": False},
               PEER: {"ways": {"edge": True, "thirds": ALL[:], "edges": [],
                               "corner": True, "corner_at": "top_left",
                               "corners": ["top_left"], "notch": False},
                      "notch_return": False}}
        held["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OTHER] = {
            "set_at": 5, "by": OWN, "value": row}
        kept = crossing_state.edit_other(held, OTHER, OWN, thirds=[], platform="mac", now=50)
        self.assertEqual(kept["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]
                         ["rows"][OTHER]["value"][OWN]["ways"]["thirds"], ["middle"])
        refused = crossing_state.edit_other(held, OTHER, OWN, corner=True,
                                            corner_at="top_left", platform="mac", now=51)
        self.assertFalse(refused["accepted"])
        self.assertEqual(refused["settings"], held)

    def test_edit_other_ignores_notch_controls_for_a_non_mac_target(self):
        held = base()
        held["crossing_desk"]["status"][OTHER] = {"set_at": 1, "by": OTHER,
            "value": {"app": "1.5.4", "platform": "windows", "in_force": "desk",
                      "profile": profiles.DESK_ID, "row": None, "waiting": []}}
        held["crossing_desk"]["profiles"][profiles.DESK_ID]["rows"][OTHER] = {
            "set_at": 5, "by": OWN,
            "value": {OWN: {"ways": {"edge": True, "thirds": ALL[:], "edges": [],
                                      "corner": False, "corner_at": "top_left", "corners": [],
                                      "notch": False}, "notch_return": False}}}
        out = crossing_state.edit_other(held, OTHER, OWN, notch=True, notch_return=True,
                                        platform="mac", now=50)
        intent = (out["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]
                  ["rows"][OTHER]["value"][OWN])
        self.assertFalse(intent["ways"]["notch"])
        self.assertFalse(intent["notch_return"])

    def test_other_row_edits_and_share_mine_are_refused_while_sync_is_off(self):
        held = base()
        held["crossing_desk"]["on"] = {"value": False, "set_at": 30, "by": OWN}
        edited = crossing_state.edit_other(held, OTHER, OWN, edge=False, now=40)
        shared = crossing_state.share_mine(held, now=41)
        self.assertFalse(edited["accepted"])
        self.assertFalse(shared["accepted"])
        self.assertEqual(edited["settings"], held)
        self.assertEqual(shared["settings"], held)

    def test_profile_switch_snapshots_old_picture_and_activates_new_picture(self):
        held = base()
        held["layout"][OWN]["display_offsets"] = {"0": {"x": 50, "y": 0}}
        held["layout"][OWN]["displays"] = {"0": tile()}
        held["peers"].append({"id": OTHER, "port": 24820, "side": "right", "send": True,
                              "ways": copy.deepcopy(held["peers"][0]["ways"])})
        held["layout"][OTHER] = tile(320)
        held["crossing_desk"]["profiles"][profiles.DESK_ID]["picture"] = None
        created = crossing_state.new_profile(held, "Sofa", now=50)
        sofa = next(pid for pid in created["settings"]["crossing_desk"]["profiles"]
                    if pid != profiles.DESK_ID)
        created["settings"]["crossing_desk"]["profiles"][sofa]["picture"] = {
            "set_at": 50, "by": OWN,
            "tiles": {OWN: {**tile(), "display_offsets": {"unplugged": {"x": 5, "y": 0}}},
                      PEER: tile(160)}}
        switched = crossing_state.switch_profile(created["settings"], sofa, platform="mac", now=60)
        desk = switched["settings"]["crossing_desk"]["profiles"][profiles.DESK_ID]
        self.assertEqual(desk["picture"]["tiles"][OWN]["x"], 0)
        self.assertEqual(desk["picture"]["tiles"][OWN]["display_offsets"], {"0": {"x": 50, "y": 0}})
        self.assertEqual(switched["settings"]["crossing_desk"]["active"]["value"], sofa)
        # Kept while active so every machine's desk is the same; not read until it is left again.
        self.assertIn("picture", switched["settings"]["crossing_desk"]["profiles"][sofa])
        self.assertTrue(switched["send_picture"])
        self.assertNotIn("display_offsets", switched["settings"]["layout"][OWN])
        self.assertIn("displays", switched["settings"]["layout"][OWN])
        self.assertEqual(switched["settings"]["layout"][OTHER]["x"], 320)

    def test_shake_setting_changes_the_in_force_register(self):
        held = base()
        held["crossing_own"]["use_own"] = True
        out = crossing_state.set_shake(held, False, now=70)
        self.assertFalse(profiles.shake_on(out["settings"]))
        self.assertIn(("home", profiles.DESK_ID, "shake"), out["send_desk"])

    def test_shake_sensitivity_is_profile_synced_and_local_when_same_ways_is_off(self):
        held = base()
        out = crossing_state.set_shake_sensitivity(held, 150, now=70)
        self.assertTrue(out["accepted"])
        self.assertEqual(profiles.shake_sensitivity(out["settings"]), 150)
        self.assertIn(("home", profiles.DESK_ID, "sensitivity"), out["send_desk"])

        held["crossing_desk"]["on"]["value"] = False
        local = crossing_state.set_shake_sensitivity(held, 75, now=71)
        self.assertEqual(profiles.shake_sensitivity(local["settings"]), 75)
        self.assertNotIn(("home", profiles.DESK_ID, "sensitivity"), local["send_desk"])

    def test_shake_sensitivity_rejects_values_outside_the_control_range(self):
        for value in (49, 201, True):
            with self.subTest(value=value):
                self.assertFalse(crossing_state.set_shake_sensitivity(base(), value, now=70)["accepted"])

    def test_shake_sensitivity_delta_reaches_peer_without_overwriting_local_preference(self):
        edited = crossing_state.set_shake_sensitivity(base(), 150, now=70)
        target = base()
        target["crossing_own"]["shake_sensitivity"] = 80
        target["peers"][0].update(allow_drive=True, linked=True)
        packet = profiles.desk_message(edited["settings"], edited["send_desk"])
        received, *_ = profiles.merge_desk(target, packet, source=PEER, now=71)
        self.assertEqual(profiles.shake_sensitivity(received), 150)
        loaded, _ = profiles.before_load(received, now=72)
        self.assertEqual(profiles.shake_sensitivity(loaded), 150)
        local = crossing_state.set_same_ways(loaded, False, now=73)["settings"]
        self.assertEqual(profiles.shake_sensitivity(local), 80)

    def test_new_profile_carries_the_active_shake_sensitivity(self):
        held = crossing_state.set_shake_sensitivity(base(), 150, now=70)["settings"]
        created = crossing_state.new_profile(held, "Studio", now=71)
        profile_id = next(pid for pid in created["settings"]["crossing_desk"]["profiles"]
                          if pid != profiles.DESK_ID)
        self.assertEqual(profiles.shake_sensitivity(created["settings"]), 150)
        self.assertEqual(created["settings"]["crossing_desk"]["profiles"][profile_id]
                         ["home"]["sensitivity"]["value"], 150)
        self.assertIn(("home", profile_id, "sensitivity"), created["send_desk"])

    def test_same_ways_toggle_sends_the_register_even_when_a_seed_is_also_written(self):
        held = base()
        held["crossing_desk"]["on"] = {"value": False, "set_at": 30, "by": OWN}
        out = crossing_state.set_same_ways(held, True, platform="mac", now=40)
        self.assertIn(("on",), out["send_desk"])

    def test_event_rolls_back_when_the_mutation_exceeds_the_desk_size_cap(self):
        created = crossing_state.new_profile(base(), "Sofa", now=70)
        held = created["settings"]
        sofa = next(pid for pid in held["crossing_desk"]["profiles"] if pid != profiles.DESK_ID)
        held["crossing_desk"]["status"][OTHER] = {
            "set_at": 1, "by": OTHER,
            "value": {"app": "x" * profiles.MAX_DESK_BYTES, "platform": "mac",
                      "in_force": "desk", "profile": profiles.DESK_ID,
                      "row": None, "waiting": []}}
        out = crossing_state.switch_profile(held, sofa, platform="mac", now=71)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["reason"], "desk_full")
        self.assertEqual(out["settings"], held)
        self.assertFalse(out["send_picture"])
        self.assertFalse(out["forward_picture"])
        self.assertEqual(out["forward"], {})
        self.assertEqual(out["answer"], {})
        self.assertEqual(out["tell"], [])

    def test_forward_contains_only_registers_taken_from_the_peer(self):
        held = base()
        held["crossing_desk"]["on"] = {"value": False, "set_at": 30, "by": OWN}
        held["peers"][0].update(allow_drive=True, linked=True)
        received_on = {"value": True, "set_at": 90, "by": PEER}
        out = crossing_state.desk_arrived(held, {"on": received_on}, source=PEER,
                                          platform="mac", now=100)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["forward"], {"on": received_on})
        self.assertIn(("row", profiles.DESK_ID, OWN), out["send_desk"])

    def test_desk_arrival_is_refused_from_a_peer_that_cannot_drive(self):
        held = base()
        held["peers"][0]["allow_drive"] = False
        state = profiles.desk_message(held)
        out = crossing_state.desk_arrived(held, state, source=PEER, platform="mac", now=80)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["reason"], "untrusted")
        self.assertEqual(out["settings"], held)

    def test_saved_row_restore_archives_the_row_it_replaces(self):
        held = base()
        old = copy.deepcopy(held["crossing_own"]["row"])
        old[PEER]["ways"]["edge"] = False
        profiles.archive(held, old, "edited", 11)
        saved_id = held["crossing_own"]["saved"][0]["id"]
        out = crossing_state.restore_saved(held, saved_id, platform="mac", now=90)
        self.assertFalse(out["settings"]["crossing_own"]["row"][PEER]["ways"]["edge"])
        self.assertGreaterEqual(len(out["settings"]["crossing_own"]["saved"]), 2)

    def test_deleting_saved_row_does_not_change_live_or_desk_state(self):
        held = base()
        profiles.archive(held, held["crossing_own"]["row"], "edited", 11)
        saved_id = held["crossing_own"]["saved"][0]["id"]
        out = crossing_state.delete_saved(held, saved_id)
        self.assertEqual(out["settings"]["crossing_own"]["saved"], [])
        self.assertEqual(profiles.live_row(out["settings"]), profiles.live_row(held))


if __name__ == "__main__":
    unittest.main()
