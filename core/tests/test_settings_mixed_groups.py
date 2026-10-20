"""Same on all machines past the per-key suite (rc16 bug hunt, 11-10-2026): a group holding a 1.5.1
machine, two edits whose messages cross in flight, four desks, and a machine paired again, each
through the apps' own arrival code (settings_behaviour's fixtures) and recipients()' routing."""

import time
import unittest

from core import settings_sync
from core.tests.settings_behaviour import IDS, fixture
from core.tests.test_settings_per_key_desks import CHOICES
from core.tests.test_settings_per_key_review import FOURTH, RoutedDesks

# Beamer 1.5.1's shared keys (release/1.5.1 a4d36dfa, core/settings_sync.py): it reads nothing else.
OLD_CROSSING = ("resistance_px", "block_while_dragging", "shortcut", "trigger_key", "trigger_style", "double_tap_ms")
OLD_DESIGN = ("glow_style", "glow_colour", "effect_length", "effect_size", "shortcut_arrival",
              "shortcut_arrival_style")
OLD_KEYS = OLD_CROSSING + OLD_DESIGN
TRIGGER_KEYS = {"cmd_r", "f13"}


class OldPeer:
    """A 1.5.1 desk, as its settings_sync.arrived and each app's apply_same behave: one stamp for the
    whole state; a newer whole state is taken outright, its values only while on, and sent on
    unchanged; groups and per-value stamps are unknown and ignored."""

    def __init__(self, ident, values):
        self.ident = ident
        self.on, self.set_at, self.by = False, 0, ""
        self.shared = {key: values[key] for key in OLD_KEYS if key in values}
        self.routed = []

    def state(self):
        data = {"on": self.on, "set_at": self.set_at, "by": self.by}
        if self.on:
            data["crossing"] = {key: self.shared[key] for key in OLD_CROSSING}
            data["design"] = {key: self.shared[key] for key in OLD_DESIGN}
        return data

    def receive(self, source, data):
        if not settings_sync._valid_envelope(data):
            return
        by = settings_sync._id(data.get("by", ""))
        mine = settings_sync._id(self.by) or b""
        if not (data["set_at"] > self.set_at or (data["set_at"] == self.set_at and by > mine)):
            return
        self.on, self.set_at, self.by = data["on"], data["set_at"], data.get("by", "")
        if self.on:
            for section, keys in (("crossing", OLD_CROSSING), ("design", OLD_DESIGN)):
                given = data.get(section) if isinstance(data.get(section), dict) else {}
                self.shared.update({key: given[key] for key in keys
                                    if key in given and settings_sync._valid(key, given[key], TRIGGER_KEYS)})
        self.routed.append((dict(data), source))

    def edit(self, **values):
        self.shared.update(values)
        self.set_at = settings_sync.next_stamp(self.set_at, time.time())
        self.by = self.ident
        self.routed.append((self.state(), None))

    def values(self):
        return dict(self.shared)


class Group(RoutedDesks):
    def __init__(self, test, platforms, old=()):
        super().__init__(test, platforms)
        for index in old:
            self.apps[index] = OldPeer(IDS[index], self.apps[index].values())

    def link_all(self):
        for one in range(len(self.apps)):
            for other in range(one + 1, len(self.apps)):
                self.link(one, other)

    def unlink(self, index):
        self.links = {pair for pair in self.links if index not in pair}

    def old_edit(self, index, **values):
        app = self.apps[index]
        app.edit(**values)
        message, _source = app.routed.pop()
        self.run([(index, message, set(range(len(self.apps))) - {index})])

    def deliver_crossed(self, *indices):
        """Each of `indices` announces its state to every other at once, as messages in flight cross."""
        everyone = set(range(len(self.apps)))
        self.run([(index, self.apps[index].state(), everyone - {index}) for index in indices])

    def agree(self, keys, indices=None):
        indices = range(len(self.apps)) if indices is None else indices
        seen = [{key: self.apps[index].values().get(key) for key in keys} for index in indices]
        self.test.assertTrue(all(item == seen[0] for item in seen), f"the desks disagree: {seen}")
        return seen[0]


class MixedWithOnePointFiveOne(unittest.TestCase):
    """A Mac and a PC on 1.5.2 and a PC still on 1.5.1, every pair linked, Same on everywhere."""

    def setUp(self):
        self.group = Group(self, ("mac", "win", "win"), old=(2,))
        self.mac, self.pc, self.old = self.group.apps
        self.mac._set_same(True)
        self.mac.routed.clear()
        self.group.link_all()
        self.assertTrue(self.old.on, "the 1.5.1 machine follows Same on")
        self.group.edit(0, **CHOICES)

    def test_a_new_machines_edit_reaches_the_old_one(self):
        old_choices = {key: value for key, value in CHOICES.items() if key in OLD_KEYS}
        self.assertEqual({key: self.old.values()[key] for key in old_choices}, old_choices)
        self.group.agree(CHOICES, (0, 1))

    def test_an_old_machines_edit_reaches_both_and_moves_nothing_else(self):
        time.sleep(1.1)
        self.group.old_edit(2, glow_colour="mono")
        expected = dict(CHOICES, glow_colour="mono")
        for index in (0, 1):
            self.assertEqual(self.group.shared(index), expected, f"desk {index}")

    def test_a_value_only_1_5_2_has_survives_an_old_machines_edit(self):
        self.group.edit(1, shortcut_goes_to="ticked")
        time.sleep(1.1)
        self.group.old_edit(2, trigger_style="double_tap")
        for index in (0, 1):
            values = self.group.apps[index].values()
            self.assertEqual(values["shortcut_goes_to"], "ticked", f"desk {index}")
            self.assertEqual(values["trigger_style"], "double_tap", f"desk {index}")

    def test_the_old_machine_away_for_an_edit_learns_it_when_its_links_come_back(self):
        self.group.online.discard(2)
        self.group.edit(0, glow_colour="aurora")
        self.group.online.add(2)
        self.group.link(2, 0)
        self.group.link(2, 1)
        self.assertEqual(self.old.values()["glow_colour"], "aurora")
        self.group.agree(OLD_KEYS)

    def test_a_new_machine_away_for_an_old_machines_edit_learns_it_when_back(self):
        self.group.online.discard(1)
        time.sleep(1.1)
        self.group.old_edit(2, effect_length="short")
        self.group.online.add(1)
        self.group.link(1, 0)
        self.group.link(1, 2)
        self.assertEqual(self.pc.values()["effect_length"], "short")
        self.group.agree(OLD_KEYS)


class OldMachineTurnsItOn(unittest.TestCase):
    """Same off everywhere; a person turns it on on the 1.5.1 machine, which sends no groups."""

    def setUp(self):
        self.group = Group(self, ("mac", "win", "win"), old=(2,))
        self.mac, self.pc, self.old = self.group.apps
        self.group.link_all()
        self.assertFalse(any(app.cfg().same_on_both for app in (self.mac, self.pc)))

    def test_both_new_machines_share_every_group_and_take_its_values(self):
        time.sleep(1.1)
        self.group.old_edit(2, glow_colour="mono", trigger_style="hold")
        self.old.on = True
        self.group.old_edit(2)
        for index, app in ((0, self.mac), (1, self.pc)):
            with self.subTest(desk=index):
                self.assertTrue(app.cfg().same_on_both)
                self.assertEqual(tuple(app.cfg().same_groups), settings_sync.ALL_GROUPS,
                                 "on from a peer that sends no groups shares every group, as turning it on here does")
                self.assertEqual(self.group.shared(index, ("glow_colour", "trigger_style")),
                                 {"glow_colour": "mono", "trigger_style": "hold"})


class TwoAtOnce(unittest.TestCase):
    """A person on each of two machines changes a shared value in the same moment: both messages are
    in flight before either lands."""

    def setUp(self):
        self.group = Group(self, ("mac", "win"))
        self.group.apps[0]._set_same(True)
        self.group.apps[0].routed.clear()
        self.group.link_all()
        self.group.edit(0, **CHOICES)

    def edit_unheard(self, index, **values):
        online = set(self.group.online)
        self.group.online.clear()
        self.group.edit(index, **values)
        self.group.online |= online

    def test_different_values_both_stand(self):
        time.sleep(1.1)
        self.edit_unheard(0, glow_colour="sunset")
        self.edit_unheard(1, trigger_style="double_tap")
        self.group.deliver_crossed(0, 1)
        expected = dict(CHOICES, glow_colour="sunset", trigger_style="double_tap")
        for index in (0, 1):
            self.assertEqual(self.group.shared(index), expected, f"desk {index}")

    def test_the_same_value_settles_on_one_choice_on_both(self):
        time.sleep(1.1)
        self.edit_unheard(0, glow_colour="sunset")
        self.edit_unheard(1, glow_colour="mono")
        self.group.deliver_crossed(0, 1)
        settled = self.group.agree(("glow_colour",))
        self.assertIn(settled["glow_colour"], ("sunset", "mono"))
        self.assertEqual(self.group.shared(0, ("trigger_style",)), {"trigger_style": "hold"})


class FourDesks(unittest.TestCase):
    def setUp(self):
        # A fourth desk for this case only: IDS is shared, and other suites assert on its length.
        IDS.append(FOURTH)
        self.addCleanup(IDS.remove, FOURTH)
        self.group = Group(self, ("mac", "win", "win", "win"))
        self.group.apps[0]._set_same(True)
        self.group.apps[0].routed.clear()
        self.group.link_all()

    def test_edits_on_three_machines_while_one_is_away_all_land_everywhere(self):
        self.group.edit(0, **CHOICES)
        self.group.agree(CHOICES)
        self.group.online.discard(3)
        time.sleep(1.1)
        self.group.edit(1, glow_colour="sunset")
        self.group.edit(2, trigger_style="double_tap")
        self.group.online.add(3)
        for other in range(3):
            self.group.link(3, other)
        expected = dict(CHOICES, glow_colour="sunset", trigger_style="double_tap")
        for index in range(4):
            self.assertEqual(self.group.shared(index), expected, f"desk {index}")

    def test_the_away_machines_own_edit_is_kept_and_it_takes_the_rest(self):
        self.group.edit(0, **CHOICES)
        self.group.online.discard(3)
        time.sleep(1.1)
        self.group.edit(1, glow_colour="sunset")
        time.sleep(1.1)
        online = set(self.group.online)
        self.group.online.clear()
        self.group.edit(3, effect_length="short")
        self.group.online |= online | {3}
        for other in range(3):
            self.group.link(3, other)
        expected = dict(CHOICES, glow_colour="sunset", effect_length="short")
        for index in range(4):
            self.assertEqual(self.group.shared(index), expected, f"desk {index}")


class PairedAgain(unittest.TestCase):
    def setUp(self):
        self.group = Group(self, ("mac", "win", "win"))
        self.group.apps[0]._set_same(True)
        self.group.apps[0].routed.clear()
        self.group.link_all()
        self.group.edit(0, **CHOICES)

    def test_a_machine_forgotten_and_paired_again_takes_what_changed_meanwhile(self):
        self.group.unlink(2)
        time.sleep(1.1)
        self.group.edit(1, glow_colour="sunset")
        self.group.link(2, 0)
        self.group.link(2, 1)
        for index in range(3):
            self.assertEqual(self.group.shared(index), dict(CHOICES, glow_colour="sunset"), f"desk {index}")

    def test_a_reinstalled_machine_adopts_the_group_and_changes_nobody(self):
        self.group.unlink(2)
        fresh = fixture("win", IDS[2])
        self.group.apps[2] = fresh
        fresh.routed = []
        fresh._send_same = lambda data=None, source=None: fresh.routed.append(
            (data if data is not None else fresh.state(), source))
        self.group.link(2, 0)
        self.group.link(2, 1)
        for index in range(3):
            self.assertEqual(self.group.shared(index), CHOICES, f"desk {index}")
        self.assertTrue(fresh.cfg().same_on_both)


if __name__ == "__main__":
    unittest.main()
