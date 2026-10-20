"""Same on all machines across three desks, value by value, through each app's own arrival code
(settings_behaviour's fixtures): a Mac and a PC sharing non-default choices, a fresh third machine
pairing in, and a machine that missed an edit making one of its own (rc14, 10-10-2026)."""

import time
import unittest

from core import settings_sync
from core.tests.settings_behaviour import IDS, fixture, mac_adapter

CHOICES = dict(trigger_style="hold", glow_colour="ocean", effect_length="long", resistance_px=300,
               shortcut_goes_to="next")


class Desks:
    def __init__(self, test, platforms):
        self.test = test
        self.apps = [fixture(platform, IDS[index]) for index, platform in enumerate(platforms)]
        self.platforms = platforms
        self.online = set(range(len(self.apps)))
        self.links = set()

    def link(self, one, other):
        """A link comes up: each end announces its state to the other."""
        self.links |= {(one, other), (other, one)}
        self.run([(one, self.apps[one].state(), {other}), (other, self.apps[other].state(), {one})])

    def run(self, queue):
        delivered = 0
        while queue:
            source, data, targets = queue.pop(0)
            for target in sorted(targets):
                if target == source or target not in self.online or (source, target) not in self.links:
                    continue
                delivered += 1
                self.test.assertLess(delivered, 60, "the desks kept announcing")
                app = self.apps[target]
                # Names have their own per-entry stamps, and the fixtures hold no name to rename.
                app.receive(IDS[source], {key: value for key, value in data.items() if key != "names"})
                queue.extend((target, message, set(range(len(self.apps))) - {target}) for message in app.sent)
                app.sent.clear()

    def edit(self, index, **values):
        """A person changes `values` on desk `index`, as its settings page saves and sends them."""
        app, cfg = self.apps[index], self.apps[index].cfg()
        before = app.values()
        held = settings_sync.held_stamps(cfg.same_stamps, cfg.same_set_at, cfg.same_by)
        on = cfg.same_on_both
        if self.platforms[index] == "mac":
            config, to_raw = mac_adapter()
            raw = settings_sync.apply_mac(to_raw(cfg), values)
            after = settings_sync.mac_values(raw)
            stamps, stamp = settings_sync.stamp_changes(held, before, after, IDS[index], floor=cfg.same_set_at,
                                                        now=time.time())
            raw["same_stamps"] = settings_sync.stored_stamps(stamps)
            if on:
                raw.update(same_set_at=stamp, same_by=IDS[index])
            app.controller.apply_settings(config.parse_config(raw))
        else:
            settings_sync.apply_pc(cfg, values)
            stamps, stamp = settings_sync.stamp_changes(held, before, settings_sync.pc_values(cfg), IDS[index],
                                                        floor=cfg.same_set_at, now=time.time())
            cfg.same_stamps = settings_sync.stored_stamps(stamps)
            if on:
                cfg.same_set_at, cfg.same_by = stamp, IDS[index]
        # While Same is off a change is stamped for later but travels nowhere.
        if on:
            self.run([(index, app.state(), set(range(len(self.apps))) - {index})])

    def shared(self, index, keys=tuple(CHOICES)):
        values = self.apps[index].values()
        return {key: values[key] for key in keys}


class ThreeDesks(unittest.TestCase):
    def setUp(self):
        self.desks = Desks(self, ("mac", "win", "win"))
        mac, pc, _fresh = self.desks.apps
        mac._set_same(True)
        mac.sent.clear()
        self.desks.link(0, 1)
        self.desks.edit(0, **CHOICES)
        self.assertEqual(self.desks.shared(1), CHOICES)

    def test_a_fresh_third_machine_adopts_the_groups_choices_and_changes_nobodys(self):
        defaults = self.desks.shared(2)
        self.assertNotEqual(defaults, CHOICES)
        self.desks.link(2, 0)
        self.desks.link(2, 1)
        for index in range(3):
            self.assertEqual(self.desks.shared(index), CHOICES, f"desk {index}")
        self.assertTrue(all(app.cfg().same_on_both for app in self.desks.apps))

    def test_a_machine_that_missed_an_edit_sends_only_its_own_change(self):
        self.desks.link(2, 0)
        self.desks.link(2, 1)
        self.desks.online.discard(1)
        self.desks.edit(0, glow_colour="sunset")
        self.assertEqual(self.desks.shared(2)["glow_colour"], "sunset")
        self.assertEqual(self.desks.shared(1)["glow_colour"], "ocean", "the PC was away")
        self.desks.online.add(1)
        # Back, still holding the old colour, someone changes its style before any link announces.
        self.desks.edit(1, trigger_style="double_tap")
        expected = dict(CHOICES, glow_colour="sunset", trigger_style="double_tap")
        for index in range(3):
            self.assertEqual(self.desks.shared(index), expected, f"desk {index}")

    def test_an_edit_while_same_is_off_wins_when_it_is_turned_on(self):
        mac, pc, _fresh = self.desks.apps
        pc._set_same(False)
        self.desks.run([(1, pc.state(), {0})])
        pc.sent.clear()
        self.assertFalse(mac.cfg().same_on_both)
        self.desks.edit(1, glow_colour="mono")
        self.assertEqual(self.desks.shared(0)["glow_colour"], "ocean", "off: nothing travels")
        mac._set_same(True)
        self.desks.run([(0, message, {1}) for message in mac.sent])
        mac.sent.clear()
        for index in (0, 1):
            self.assertEqual(self.desks.shared(index)["glow_colour"], "mono", f"desk {index}")
            self.assertEqual(self.desks.shared(index)["trigger_style"], "hold", f"desk {index}")


if __name__ == "__main__":
    unittest.main()
