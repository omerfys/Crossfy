"""Same on all machines, value by value (rc14, 10-10-2026): an edit carries only what a person
changed, so a value a machine missed or never set no longer overwrites real choices everywhere."""

import unittest

from core import protocol, settings_sync

A, B, C = (protocol.id_text(bytes([value]) * 16) for value in (1, 2, 3))
KEYS = {"cmd_r", "alt_r"}
GROUPS = list(settings_sync.ALL_GROUPS)
NOW = 2_000_000_000


def state(by, set_at, stamps, **values):
    held = settings_sync.held_stamps(stamps, set_at, by)
    return settings_sync.message_data(True, set_at, values, by=by, groups=GROUPS, stamps=held)


class Merge(unittest.TestCase):
    def merge(self, data, stamps, set_at, by, on=True, groups=GROUPS):
        return settings_sync.merge(data, stamps, set_at, KEYS, by_here=by, on_here=on, now=NOW,
                                   current_groups=groups)

    def test_a_fresh_machine_adopts_every_value_the_group_holds(self):
        sent = state(A, 500, {"trigger_style": [400, A]}, trigger_style="double_tap", trigger_key="cmd_r")
        merged = self.merge(sent, {}, 0, "", on=False, groups=[])
        self.assertIsNotNone(merged["policy"])
        self.assertEqual(merged["values"], {"trigger_style": "double_tap", "trigger_key": "cmd_r"})
        self.assertFalse(merged["answer"])

    def test_an_edit_from_a_machine_that_missed_one_carries_only_its_own_change(self):
        # A set the style at 300. C was offline, then changed the key at 400 still holding the old style.
        sent = state(C, 400, {"trigger_key": [400, C], "trigger_style": [100, B]},
                     trigger_style="hold", trigger_key="alt_r")
        merged = self.merge(sent, {"trigger_style": [300, A], "trigger_key": [100, B]}, 300, A)
        self.assertEqual(merged["values"], {"trigger_key": "alt_r"})
        self.assertTrue(merged["answer"], "A holds a newer style C has to learn")
        # A's answer brings C the style, and C has nothing newer to send back.
        answer = state(A, 400, {"trigger_style": [300, A], "trigger_key": [400, C]},
                       trigger_style="double_tap", trigger_key="alt_r")
        back = self.merge(answer, {"trigger_key": [400, C], "trigger_style": [100, B]}, 400, C)
        self.assertEqual(back["values"], {"trigger_style": "double_tap"})
        self.assertFalse(back["answer"])
        again = self.merge(answer, {"trigger_key": [400, C], "trigger_style": [300, A]}, 400, C)
        self.assertEqual(again["values"], {})
        self.assertFalse(again["answer"], "the same state twice changes nothing and is not answered")

    def test_a_1_5_1_peer_without_stamps_counts_every_value_at_its_whole_stamp(self):
        old = settings_sync.message_data(True, 500, {"trigger_style": "hold", "trigger_key": "cmd_r"},
                                         by=B, groups=GROUPS)
        self.assertNotIn("stamps", old)
        merged = self.merge(old, {"trigger_style": [600, A], "trigger_key": [300, A]}, 600, A)
        self.assertIsNone(merged["policy"])
        self.assertEqual(merged["values"], {"trigger_key": "cmd_r"})
        self.assertTrue(merged["answer"])

    def test_values_wait_while_same_is_off_and_outside_the_selected_groups(self):
        sent = state(A, 500, {}, trigger_style="hold", glow_colour="ocean")
        older = settings_sync.message_data(True, 100, {"trigger_style": "hold", "glow_colour": "ocean"},
                                           by=A, groups=GROUPS, stamps={"trigger_style": (100, A), "glow_colour": (100, A)})
        held = {"trigger_style": [50, B], "glow_colour": [50, B]}
        self.assertEqual(self.merge(older, held, 200, B, on=False)["values"], {})
        merged = self.merge(older, held, 200, B, on=True, groups=["design"])
        self.assertEqual(merged["values"], {"glow_colour": "ocean"})
        self.assertEqual(self.merge(sent, {}, 0, "", on=False, groups=[])["groups"], tuple(GROUPS))

    def test_a_value_changed_while_its_group_was_off_travels_newer_than_its_state(self):
        sent = settings_sync.message_data(True, 100, {"trigger_style": "hold"}, by=A, groups=GROUPS,
                                          stamps={"trigger_style": (900, A)})
        self.assertEqual(self.merge(sent, {"trigger_style": [500, B]}, 600, B)["values"], {"trigger_style": "hold"})
        ahead = settings_sync.message_data(True, 100, {"trigger_style": "hold"}, by=A, groups=GROUPS,
                                           stamps={"trigger_style": (NOW + 2 * settings_sync.DAY, A)})
        self.assertEqual(self.merge(ahead, {}, 50, B)["values"], {}, "a day ahead of this clock is refused")

    def test_ties_break_on_the_larger_id_as_whole_states_do(self):
        sent = state(B, 300, {"trigger_style": [300, B]}, trigger_style="hold")
        self.assertEqual(self.merge(sent, {"trigger_style": [300, A]}, 300, A)["values"], {"trigger_style": "hold"})
        self.assertEqual(self.merge(sent, {"trigger_style": [300, C]}, 300, C)["values"], {})


class Stamping(unittest.TestCase):
    def test_only_the_keys_a_person_changed_are_stamped_and_newer_than_any_held(self):
        held = settings_sync.held_stamps({"glow_colour": [700, B]}, 500, A)
        before = {"trigger_style": "double_tap", "glow_colour": "ocean"}
        stamps, stamp = settings_sync.stamp_changes(held, before, {**before, "trigger_style": "hold"}, C, now=600)
        self.assertEqual(stamp, 701)
        self.assertEqual(stamps["trigger_style"], (701, C))
        self.assertEqual(stamps["glow_colour"], (700, B))
        self.assertEqual(settings_sync.stamp_changes(held, before, before, C, now=600), (held, None))

    def test_a_fresh_machine_holds_nothing_newer_than_the_group(self):
        self.assertEqual(set(settings_sync.held_stamps({}, 0, "").values()), {(0, "")})
        held = settings_sync.held_stamps({"trigger_style": ["x", A], "trigger_key": [5, "not an id"]}, 9, A)
        self.assertEqual(held["trigger_style"], (9, A))
        self.assertEqual(held["trigger_key"], (9, A))

    def test_stamps_travel_only_with_the_values_sent(self):
        held = settings_sync.held_stamps({}, 5, A)
        data = settings_sync.message_data(True, 5, {"glow_colour": "ocean", "trigger_style": "hold"}, by=A,
                                          groups=["design"], stamps=held)
        self.assertEqual(data["stamps"], {"glow_colour": [5, A]})
        self.assertEqual(settings_sync.stored_stamps({"glow_colour": (5, A)}), {"glow_colour": [5, A]})


if __name__ == "__main__":
    unittest.main()
